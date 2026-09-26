"""G HUB Reader – liest Logitech-Geräte + Akkustand über ws://localhost:9010.

Getestet mit G HUB + G502 LIGHTSPEED (44 %, Stand 25.09.2026).
Protokoll ist inoffiziell/reverse-engineered, funktioniert aber stabil.
"""
import asyncio
import json
import socket

GHUB_HOST = "127.0.0.1"
GHUB_PORT = 9010


def ghub_running(timeout: float = 1.0) -> bool:
    """Prüft ob der G HUB Websocket-Port offen ist."""
    try:
        with socket.create_connection((GHUB_HOST, GHUB_PORT), timeout=timeout):
            return True
    except OSError:
        return False


async def _ws_recv_path(ws, want_path: str, timeout: float = 5.0):
    """Liest Nachrichten bis die gewünschte path-Antwort kommt."""
    import websockets as _ws_mod  # noqa
    end = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = end - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise asyncio.TimeoutError(f"Timeout waiting for {want_path}")
        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        try:
            msg = json.loads(raw)
        except Exception:
            continue
        if msg.get("path") == want_path:
            return msg
        # OPTIONS "/" Nachrichten ignorieren, weiter warten


async def _connect():
    import websockets
    # websockets>=14: kein extra_headers mehr nötig, subprotocols reicht
    return await websockets.connect(
        f"ws://{GHUB_HOST}:{GHUB_PORT}",
        subprotocols=["json"],  # type: ignore[arg-type]
        max_size=10 * 1024 * 1024,
    )


async def get_devices_async(timeout: float = 6.0):
    """Liste aller Geräte: [{id, name, hasBattery, state}]"""
    async with await _connect() as ws:
        await ws.send(json.dumps({"msgId": "", "verb": "GET", "path": "/devices/list"}))
        msg = await _ws_recv_path(ws, "/devices/list", timeout=timeout)
        infos = msg.get("payload", {}).get("deviceInfos", [])
        out = []
        for d in infos:
            name = (
                d.get("extendedDisplayName")
                or d.get("displayName")
                or d.get("name")
                or d.get("id")
            )
            out.append(
                {
                    "id": d.get("id"),
                    "name": str(name).strip(),
                    "hasBattery": bool(
                        (d.get("capabilities") or {}).get("hasBatteryStatus")
                    ),
                    "state": d.get("state", "UNKNOWN"),
                    "connection": d.get("displayConnectionType")
                    or d.get("connectionType", ""),
                    "devtype": d.get("deviceType", ""),
                    "firmware": next(
                        (a.get("firmwareVersion", "")
                         for a in (d.get("activeInterfaces") or [])
                         if a.get("firmwareVersion")), ""),
                    "lighting": bool(
                        (d.get("capabilities") or {}).get(
                            "lightingSupport")),
                }
            )
        return out


async def get_battery_async(device_id: str, timeout: float = 6.0):
    """Batterie für ein device: {percentage, charging, mileage, ...} oder None."""
    async with await _connect() as ws:
        await ws.send(
            json.dumps(
                {"msgId": "", "verb": "GET", "path": f"/battery/{device_id}/state"}
            )
        )
        msg = await _ws_recv_path(
            ws, f"/battery/{device_id}/state", timeout=timeout
        )
        p = msg.get("payload") or {}
        if "percentage" not in p:
            return None
        return {
            "percentage": int(p.get("percentage", 0)),
            "charging": bool(p.get("charging", False)),
            "mileage": p.get("mileage"),
            "critical": bool(p.get("criticalLevel", False)),
            "fullyCharged": bool(p.get("fullyCharged", False)),
        }


async def get_all_batteries_async():
    """Alle Geräte mit Batterie + Status. Offline-Geräte bekommen percentage=None."""
    devices = await get_devices_async()
    batt_devices = [d for d in devices if d.get("hasBattery")]
    results = []
    for d in batt_devices:
        # NOT_CONNECTED Geräte trotzdem anzeigen, aber ohne Abfrage
        if d.get("state") not in ("ACTIVE", "CONNECTED", "ONLINE", None, "", "UNKNOWN"):
            # Trotzdem versuchen, manche Headsets melden NOT_CONNECTED mit letztem Stand
            pass
        try:
            b = await get_battery_async(d["id"])
        except Exception:
            b = None
        entry = dict(d)
        if b:
            entry.update(b)
        else:
            entry.update(
                {"percentage": None, "charging": False, "mileage": None}
            )
        results.append(entry)
    return results


# ---- Sync-Wrapper für Tkinter (einfach via asyncio.run) ----

def get_devices_sync(timeout: float = 6.0):
    return asyncio.run(get_devices_async(timeout=timeout))


def get_battery_sync(device_id: str, timeout: float = 6.0):
    return asyncio.run(get_battery_async(device_id, timeout=timeout))


def get_all_batteries_sync():
    return asyncio.run(get_all_batteries_async())


# ---- Live-Push: Batterie-Events sofort statt Polling ----

BATTERY_CHANGED_PATH = "/battery/state/changed"


def parse_battery_broadcast(msg):
    """Wertet eine BROADCAST-Nachricht aus. Gibt dict oder None zurück."""
    try:
        if msg.get("path") != BATTERY_CHANGED_PATH:
            return None
        p = msg.get("payload") or {}
        if "deviceId" not in p or "percentage" not in p:
            return None
        return {
            "deviceId": p.get("deviceId"),
            "percentage": int(p.get("percentage", 0)),
            "charging": bool(p.get("charging", False)),
            "mileage": p.get("mileage"),
            "critical": bool(p.get("criticalLevel", False)),
            "fullyCharged": bool(p.get("fullyCharged", False)),
        }
    except Exception:
        return None


async def subscribe_loop(on_event, stop_event, on_status=None,
                         reconnect_delay: float = 5.0):
    """Dauerhafte Verbindung: pusht Batterie-Änderungen sofort via on_event.

    on_event(evt_dict), on_status(connected: bool). Läuft bis stop_event.
    Verbindet automatisch neu (z.B. bei G HUB Neustart).
    """
    import threading
    sub_msg = json.dumps(
        {"msgId": "", "verb": "SUBSCRIBE", "path": BATTERY_CHANGED_PATH}
    )
    while not stop_event.is_set():
        try:
            async with await _connect() as ws:
                if on_status:
                    try:
                        on_status(True)
                    except Exception:
                        pass
                await ws.send(sub_msg)
                last_sub = asyncio.get_event_loop().time()
                while not stop_event.is_set():
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=70)
                    except asyncio.TimeoutError:
                        # Keepalive: neu subscriben
                        try:
                            await ws.send(sub_msg)
                        except Exception:
                            break
                        continue
                    try:
                        msg = json.loads(raw)
                    except Exception:
                        continue
                    evt = parse_battery_broadcast(msg)
                    if evt is not None:
                        try:
                            on_event(evt)
                        except Exception:
                            pass
                    else:
                        # Antwort/OTHERS: Subscription ggf. erneuern (max 1x/10s)
                        now = asyncio.get_event_loop().time()
                        if now - last_sub > 10:
                            try:
                                await ws.send(sub_msg)
                                last_sub = now
                            except Exception:
                                break
        except Exception:
            pass
        if on_status:
            try:
                on_status(False)
            except Exception:
                pass
        # Reconnect-Wartezeit (abbrechbar)
        if isinstance(stop_event, threading.Event):
            stop_event.wait(reconnect_delay)
        else:
            try:
                await asyncio.sleep(reconnect_delay)
            except Exception:
                break


def start_battery_listener(on_event, stop_event, on_status=None):
    """Startet den Live-Listener in einem Daemon-Thread. Gibt Thread zurück."""
    import threading

    def _run():
        try:
            asyncio.run(subscribe_loop(on_event, stop_event,
                                       on_status=on_status))
        except Exception:
            pass

    t = threading.Thread(target=_run, daemon=True,
                         name="ghub-live-listener")
    t.start()
    return t


DEMO_DEVICES = [
    {"id": "dev-demo-1", "name": "G502 LIGHTSPEED (Demo)", "hasBattery": True,
     "state": "ACTIVE", "percentage": 44, "charging": False, "mileage": 11.3,
     "critical": False, "fullyCharged": False},
    {"id": "dev-demo-2", "name": "G915 TKL (Demo)", "hasBattery": True,
     "state": "ACTIVE", "percentage": 82, "charging": True, "mileage": 30.0,
     "critical": False, "fullyCharged": False},
]
