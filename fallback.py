"""Redundante Quellen – wenn der G HUB Websocket ausfällt:

1. G HUB Datei-DB (settings.db): G HUBs eigene Batterie-Stände
   ("battery/<slug>/percentage" + "battery/<slug>/warning" mit deviceId).
   Read-only per Dateikopie, stört G HUB nicht.
2. Externe Tools (LGSTrayBattery o.ä. auf Port 12321, falls installiert).
3. HID-Direktabfrage (hidpp.py, experimentell).
"""
import json
import os
import re
import shutil
import tempfile
import time

PCT_RE = re.compile(
    r'"battery/([^"/]+)/percentage"\s*:\s*\{\s*"percentage"\s*:\s*(\d+)')
TIME_RE = re.compile(r'"time"\s*:\s*"([^"]+)"')
WARN_RE = re.compile(r'"battery/([^"/]+)/warning"\s*:\s*\{([^}]{0,500})')
DID_RE = re.compile(r'"deviceId"\s*:\s*"([^"]+)"')
LVL_RE = re.compile(r'"level"\s*:\s*"([^"]+)"')


def _scan_text(text):
    """Extrahiert Batterie-Einträge aus dem settings-JSON-Text."""
    out = {}
    for m in PCT_RE.finditer(text):
        slug, pct = m.group(1), int(m.group(2))
        tail = text[m.end():m.end() + 300]
        tm = TIME_RE.search(tail)
        e = out.setdefault(slug, {"slug": slug})
        e["percentage"] = pct
        if tm:
            e["time"] = tm.group(1)
    for m in WARN_RE.finditer(text):
        slug, chunk = m.group(1), m.group(2)
        e = out.setdefault(slug, {"slug": slug})
        dm = DID_RE.search(chunk)
        lm = LVL_RE.search(chunk)
        pm = re.search(r'"percentage"\s*:\s*(\d+)', chunk)
        tm = TIME_RE.search(chunk)
        if dm:
            e["deviceId"] = dm.group(1)
        if lm:
            e["level"] = lm.group(1)
        if pm and "percentage" not in e:
            e["percentage"] = int(pm.group(1))
        if tm and "time" not in e:
            e["time"] = tm.group(1)
    return [v for v in out.values() if "percentage" in v]


def _db_paths():
    base = os.environ.get("LOCALAPPDATA", "")
    db = os.path.join(base, "LGHUB", "settings.db")
    return db


def read_db_batteries():
    """Liest Batterie-Stände aus G HUBs settings.db. Liste von Dicts."""
    db = _db_paths()
    if not db or not os.path.isfile(db):
        return []
    tmpd = tempfile.mkdtemp(prefix="logiw_db_")
    try:
        for suffix in ("", "-wal", "-shm"):
            src = db + suffix
            if os.path.isfile(src):
                try:
                    shutil.copy(src, os.path.join(
                        tmpd, "settings.db" + suffix))
                except Exception:
                    pass
        blob = None
        try:
            import sqlite3
            con = sqlite3.connect(os.path.join(tmpd, "settings.db"))
            try:
                row = con.execute(
                    "SELECT FILE FROM DATA ORDER BY _id DESC LIMIT 1"
                ).fetchone()
                if row:
                    blob = row[0]
            finally:
                con.close()
        except Exception:
            blob = None
        if blob:
            text = blob.decode("utf-8", "ignore") \
                if isinstance(blob, (bytes, bytearray)) else str(blob)
            found = _scan_text(text)
            if found:
                return found
        # Fallback: roher Byte-Scan der DB-Kopie
        try:
            with open(os.path.join(tmpd, "settings.db"),
                      "rb") as f:
                raw = f.read().decode("utf-8", "ignore")
            return _scan_text(raw)
        except Exception:
            return []
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)


def db_time_to_epoch(ts):
    try:
        s = str(ts).strip()
        if re.fullmatch(r"\d{9,11}", s):
            return int(s)
        # "2026-09-25T22:25:14Z"
        import calendar
        st = time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")
        return calendar.timegm(st)
    except Exception:
        return None


def ext_available(timeout=0.4):
    """Port 12321 offen? (LGSTrayBattery o.ä.)"""
    try:
        import socket
        with socket.create_connection(("127.0.0.1", 12321),
                                      timeout=timeout):
            return True
    except OSError:
        return False


def read_ext_batteries(timeout=2.5):
    """Externe Tools via HTTP :12321. Liste [{name, percentage, charging}]."""
    import socket
    import urllib.request
    try:
        with socket.create_connection(("127.0.0.1", 12321), timeout=0.5):
            pass
    except OSError:
        return []
    out = []

    def get(path):
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:12321{path}",
                headers={"User-Agent": "LogiBatteryWidget"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception:
            return ""

    devs = get("/devices")
    ids = []
    if devs.strip().startswith(("{", "[")):
        try:
            data = json.loads(devs)
            if isinstance(data, dict):
                data = data.get("devices", data.get("deviceInfos", []))
            for d in (data or []):
                if isinstance(d, dict):
                    did = d.get("id") or d.get("device_id") \
                        or d.get("deviceId")
                    if did:
                        ids.append((str(did), d.get("name")
                                    or d.get("displayName") or str(did)))
                elif isinstance(d, str):
                    ids.append((d, d))
        except Exception:
            pass
    if not ids:
        for m in re.finditer(
                r'(?:device[_/]?(?:id)?["\s:=>]+)(dev[0-9a-zA-Z_-]+|\d+)',
                devs):
            if m.group(1) not in [i for i, _ in ids]:
                ids.append((m.group(1), m.group(1)))
    for did, name in ids[:16]:
        xml = get(f"/device/{did}")
        if not xml:
            continue
        pm = re.search(r'battery_percent[^0-9]{0,10}(\d{1,3})', xml)
        if not pm:
            pm = re.search(r'percent[^0-9]{0,10}(\d{1,3})', xml)
        if not pm:
            continue
        nm = re.search(r'device_name[^a-zA-Z0-9]{0,10}([^<"\']+)', xml)
        cm = re.search(r'charging[^a-zA-Z0-9]{0,10}(true|1)', xml,
                       re.IGNORECASE)
        out.append({"id": f"ext-{did}",
                    "name": (nm.group(1).strip() if nm else name),
                    "percentage": max(0, min(100, int(pm.group(1)))),
                    "charging": bool(cm)})
    return out


def read_hid_batteries(timeout_total=8.0):
    """HID-Direkt (experimentell). Liste wie hidpp.read_all()."""
    try:
        import hidpp
        return hidpp.read_all(timeout_total=timeout_total)
    except Exception:
        return []


def logitray_exe():
    import sys
    base = os.path.dirname(os.path.abspath(sys.argv[0])) \
        if getattr(sys, "frozen", False) else os.path.dirname(
            os.path.abspath(__file__))
    cands = [os.path.join(base, "logitray.exe"),
             os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "logitray.exe")]
    for c in cands:
        if os.path.isfile(c):
            return c
    return None


def read_logitray(timeout=30):
    """logitray.exe --once (HID direkt, ohne G HUB).

    Liste [{name, percentage, charging}]. Langsam beim ersten Mal
    (Geräte-Erkennung), danach schneller.
    """
    import subprocess
    exe = logitray_exe()
    if not exe:
        return []
    try:
        si = subprocess.STARTUPINFO()
        try:
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        except Exception:
            pass
        p = subprocess.run(
            [exe, "--once"], capture_output=True, text=True,
            timeout=timeout, startupinfo=si)
        out = (p.stdout or "") + "\n" + (p.stderr or "")
    except Exception:
        return []
    res = []
    for line in out.splitlines():
        m = re.match(r"^\s*(.+?)\s*:\s*(\d{1,3})\s*%\s*(.*)$", line)
        if not m:
            continue
        rest = m.group(3).lower()
        charging = any(k in rest for k in
                       ("charg", "lädt", "lad", "⚡", "full", "voll"))
        res.append({"name": m.group(1).strip(),
                    "percentage": max(0, min(100, int(m.group(2)))),
                    "charging": charging})
    return res
