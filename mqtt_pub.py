"""MQTT-Export für LogiBatteryWidget (z.B. Home Assistant).

publish(devices, cfg): sendet %- und Lade-Status je Gerät + optional
HA-Discovery. Niemals Exceptions nach außen, gedrosselt (bei Änderung
oder max 1x/120s je Gerät). Verbindet bei Bedarf (neu).
"""
import json
import re
import time

_state = {"client": None, "key": None, "last": {}, "ha_sent": set(),
          "connected": False}


def _slug(name):
    s = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")
    return s or "geraet"


def _connect(cfg):
    import paho.mqtt.client as mqtt
    host = cfg.get("mqtt_host", "localhost") or "localhost"
    try:
        port = int(cfg.get("mqtt_port", 1883))
    except Exception:
        port = 1883
    user = cfg.get("mqtt_user", "") or ""
    pw = cfg.get("mqtt_password", "") or ""
    try:
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except Exception:
        c = mqtt.Client()

    def _on_conn(client, userdata, flags, rc, *args):
        _state["connected"] = (rc == 0)

    def _on_disc(client, userdata, flags, rc, *args):
        _state["connected"] = False

    try:
        c.on_connect = _on_conn
        c.on_disconnect = _on_disc
    except Exception:
        pass
    if user:
        c.username_pw_set(user, pw)
    _state["connected"] = False
    c.connect_async(host, port, keepalive=60)
    c.loop_start()
    return c


def _client(cfg):
    key = (cfg.get("mqtt_host"), cfg.get("mqtt_port"),
           cfg.get("mqtt_user"), cfg.get("mqtt_password"))
    if _state["client"] is None or _state["key"] != key:
        try:
            if _state["client"] is not None:
                try:
                    _state["client"].loop_stop()
                    _state["client"].disconnect()
                except Exception:
                    pass
            _state["client"] = _connect(cfg)
            _state["key"] = key
            _state["ha_sent"] = set()
        except Exception:
            _state["client"] = None
            return None
    return _state["client"]


def publish(devices, cfg, disp_name=None):
    """devices: App-Gerätedicts. disp_name(dev)->Anzeigename (optional)."""
    if not cfg.get("mqtt_enabled", False):
        return False
    c = _client(cfg)
    if c is None:
        return False
    base = (cfg.get("mqtt_topic", "logi-akku") or "logi-akku").strip("/")
    ha = bool(cfg.get("mqtt_ha", True))
    now = time.time()
    ok = False
    try:
        for d in devices or []:
            pct = d.get("percentage")
            if pct is None:
                continue
            name = disp_name(d) if disp_name else d.get("name", "?")
            slug = _slug(d.get("id") or name)
            last = _state["last"].get(slug)
            if last and last[0] == pct and last[1] == bool(d.get("charging")) \
                    and now - last[2] < 120:
                continue
            _state["last"][slug] = (pct, bool(d.get("charging")), now)
            t_state = f"{base}/{slug}/state"
            payload = json.dumps({
                "percentage": pct,
                "charging": bool(d.get("charging", False)),
                "name": name})
            try:
                c.publish(t_state, payload, retain=True)
                c.publish(f"{base}/{slug}/percentage", str(pct), retain=True)
                ok = True
            except Exception:
                pass
            if ha and slug not in _state["ha_sent"]:
                try:
                    disc = {
                        "name": f"{name} Akku",
                        "unique_id": f"logi_{slug}_battery",
                        "state_topic": t_state,
                        "value_template": "{{ value_json.percentage }}",
                        "unit_of_measurement": "%",
                        "device_class": "battery",
                        "device": {"identifiers": [f"logi_{slug}"],
                                   "name": name,
                                   "manufacturer": "Logitech"}}
                    c.publish(f"homeassistant/sensor/logi_{slug}_battery/"
                              "config", json.dumps(disc), retain=True)
                    _state["ha_sent"].add(slug)
                except Exception:
                    pass
        # publish() selbst wirft bei fehlendem Broker nichts (async);
        # verbunden melden wir nur bei bestätigtem CONNACK
        return bool(_state.get("connected"))
    except Exception:
        return False


def disconnect():
    try:
        if _state["client"] is not None:
            _state["client"].loop_stop()
            _state["client"].disconnect()
    except Exception:
        pass
    _state["client"] = None
