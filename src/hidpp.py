"""HID++ Direktabfrage – Logitech Akku ohne G HUB lesen (redundante Quelle).

Protokoll (HID++ 2.0, u.a. via Solaar/logibar/OpenLogi verifiziert):
- Root getFeature (0x0000, fn 0) als KURZE Nachricht 0x10:
    [0x10, dev, 0x00, swid, featHi, featLo, 0x00]
  Antwort: [0x10|0x11, dev, 0x00, swid, featIdx, featType, featVer, ...]
- getBatteryInfo (0x1004, fn 1) als LANGE Nachricht 0x11:
    [0x11, dev, featIdx, 0x10|swid, 0x00*16]
  Antwort-Payload: [prozent(0-100), level(1/2/4/8), status(0-7), ...]
  status: 0=entlädt, 1=lädt, 2=fast voll, 3=voll, 4=langsam, 5-7=Fehler
- Fallback 0x1000 (fn 0): Payload-Byte 0 = Prozent.
"""
import time

VID_LOGITECH = 0x046D
SWID = 0x08

F_UNIFIED = 0x1004
F_BATT_STATUS = 0x1000

DEVICE_INDICES = (0x01, 0x02, 0x03, 0x04, 0x05, 0x06)


def find_channels():
    """HID++-fähige Kanäle (usage_page 0xFF00), 0x02 zuerst."""
    out = []
    try:
        import hid as _hid
        for d in _hid.enumerate(VID_LOGITECH):
            if d.get("usage_page") == 0xFF00 and d.get("path"):
                out.append(d)
    except Exception:
        return []
    out.sort(key=lambda d: 0 if d.get("usage") == 0x02 else 1)
    return out


def _open(path, retries=3):
    import hid as _hid
    last_ex = OSError("open failed")
    for _ in range(retries):
        h = _hid.device()
        try:
            h.open_path(path)
            h.set_nonblocking(False)
            return h
        except Exception as ex:
            last_ex = ex
            try:
                h.close()
            except Exception:
                pass
            time.sleep(0.4)
    raise last_ex


def _drain(h, tries=8, timeout=60):
    for _ in range(tries):
        try:
            r = h.read(64, timeout_ms=timeout)
        except Exception:
            break
        if not r:
            break


def _req_short(h, dev, feat_idx, func_byte, p1=0, p2=0, p3=0,
               reads=8, timeout=600):
    """Kurze Anfrage, Antwort mit gleichem Header (dev/feat/func)."""
    _drain(h)
    try:
        h.write(bytes([0x10, dev, feat_idx, func_byte, p1, p2, p3]))
    except Exception:
        return None
    for _ in range(reads):
        try:
            r = h.read(64, timeout_ms=timeout)
        except Exception:
            return None
        if r and len(r) >= 7 and r[0] in (0x10, 0x11) \
                and r[1] == dev and r[2] == feat_idx and r[3] == func_byte:
            return bytes(r)
    return None


def _req_long(h, dev, feat_idx, func_byte, reads=8, timeout=600):
    _drain(h)
    try:
        h.write(bytes([0x11, dev, feat_idx, func_byte] + [0] * 16))
    except Exception:
        return None
    for _ in range(reads):
        try:
            r = h.read(64, timeout_ms=timeout)
        except Exception:
            return None
        if r and len(r) >= 7 and r[0] == 0x11 \
                and r[1] == dev and r[2] == feat_idx and r[3] == func_byte:
            return bytes(r)
    return None


def get_feature_index(h, dev, feature):
    r = _req_short(h, dev, 0x00, SWID,
                   (feature >> 8) & 0xFF, feature & 0xFF, 0x00)
    if not r or len(r) < 7:
        return None
    idx = r[4]
    # Fehlerantworten (0xFF-Marker) und Index 0 = nicht vorhanden
    if r[2] == 0xFF or idx == 0:
        return None
    return idx


def query_unified(h, dev, idx):
    fn = 0x10 | SWID  # fn 1 = getBatteryInfo
    r = _req_long(h, dev, idx, fn)
    if not r or len(r) < 7:
        return None
    pct, level, status = r[4], r[5], r[6]
    if pct > 100:
        return None
    charging = status in (1, 2, 4)
    return {"percentage": int(pct), "level": level,
            "charging": charging,
            "fullyCharged": status == 3,
            "status_code": status}


def query_batt_status(h, dev, idx):
    fn = 0x00 | SWID  # fn 0
    r = _req_long(h, dev, idx, fn)
    if not r or len(r) < 5:
        return None
    pct = r[4]
    if pct > 100:
        return None
    return {"percentage": int(pct), "level": None,
            "charging": False, "fullyCharged": pct >= 100,
            "status_code": None}


def query_device(h, dev):
    """Ein Geräte-Index: 0x1004 versuchen, dann 0x1000. None wenn nichts."""
    idx = get_feature_index(h, dev, F_UNIFIED)
    if idx:
        q = query_unified(h, dev, idx)
        if q:
            q["source_feature"] = "0x1004"
            return q
    idx = get_feature_index(h, dev, F_BATT_STATUS)
    if idx:
        q = query_batt_status(h, dev, idx)
        if q:
            q["source_feature"] = "0x1000"
            return q
    return None


def read_all(timeout_total=25.0):
    """Alle HID++-Batterien: [{channel, index, percentage, charging, ...}]."""
    found = []
    t_end = time.monotonic() + timeout_total
    for ch in find_channels():
        if time.monotonic() > t_end:
            break
        try:
            h = _open(ch["path"])
        except Exception:
            continue
        try:
            for dev in DEVICE_INDICES:
                if time.monotonic() > t_end:
                    break
                try:
                    q = query_device(h, dev)
                except Exception:
                    q = None
                if q:
                    q["channel"] = ch["path"].decode("utf-8", "ignore") \
                        if isinstance(ch["path"], bytes) else str(ch["path"])
                    q["index"] = dev
                    q["pid"] = ch.get("product_id")
                    found.append(q)
        finally:
            try:
                h.close()
            except Exception:
                pass
        if found:
            break  # erster antwortender Kanal reicht
    return found


def read_one(timeout_total=20.0):
    """Bequemlichkeit: erstes gefundenes Gerät oder None."""
    all_devs = read_all(timeout_total=timeout_total)
    return all_devs[0] if all_devs else None
