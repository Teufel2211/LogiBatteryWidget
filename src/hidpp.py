"""HID++ Direktabfrage – Logitech Akku ohne G HUB lesen (redundante Quelle).

Protokoll (HID++ 2.0, via Solaar/logibar/OpenLogi/logitray verifiziert):
- KURZE Nachrichten (Report 0x10) auf usage 0x01-Kanal,
  LANGE (Report 0x11) auf usage 0x02-Kanal desselben Receivers.
- Root getFeature (0x0000, fn 0) kurz:
    [0x10, dev, 0x00, swid, featHi, featLo, 0x00]
  Antwort: [0x10|0x11, dev, 0x00, swid, featIdx, ...], idx 0 = fehlt.
- Batterie-Features (Reihenfolge): 0x1004 unified (fn 1, präzise %),
  0x1001 Spannung (fn 0: mV-BE-u16 + Flags; G502/G915 nutzen dieses!),
  0x1000 (fn 0, Byte 0 = %).
"""
import time

VID_LOGITECH = 0x046D
SWID = 0x08

F_UNIFIED = 0x1004
F_BATT_VOLT = 0x1001
F_BATT_STATUS = 0x1000

# LiPo-Kurve (mV -> % grob, 1 Zelle): unter Last sackt die Spannung,
# daher ist % daraus eine Schätzung – mV selbst sind exakt.
LIPO_CURVE = (
    (4200, 100), (4150, 95), (4100, 88), (4050, 81), (4000, 75),
    (3950, 68), (3900, 60), (3850, 50), (3800, 40), (3750, 28),
    (3700, 15), (3650, 7), (3600, 3), (3550, 1), (3500, 0),
)


def voltage_to_pct(mv):
    try:
        mv = int(mv)
    except Exception:
        return None
    if mv >= LIPO_CURVE[0][0]:
        return 100
    if mv <= LIPO_CURVE[-1][0]:
        return 0
    for (hi_mv, hi_pc), (lo_mv, lo_pc) in zip(LIPO_CURVE, LIPO_CURVE[1:]):
        if lo_mv <= mv <= hi_mv:
            f = (mv - lo_mv) / (hi_mv - lo_mv)
            return int(round(lo_pc + f * (hi_pc - lo_pc)))
    return None


DEVICE_INDICES = (0x01, 0x02, 0x03, 0x04, 0x05, 0x06)


def find_receivers():
    """Gruppiert FF00-Kanäle je Receiver: [{pid, short, long, info}]."""
    groups = {}
    try:
        import hid as _hid
        devs = _hid.enumerate(VID_LOGITECH)
    except Exception:
        return []
    for d in devs or []:
        try:
            if d.get("usage_page") != 0xFF00 or not d.get("path"):
                continue
            key = (d.get("product_id"), d.get("interface_number"))
            g = groups.setdefault(key, {"pid": d.get("product_id"),
                                        "short": None, "long": None,
                                        "info": d})
            if d.get("usage") == 0x01:
                g["short"] = d["path"]
            elif d.get("usage") == 0x02:
                g["long"] = d["path"]
            elif g["short"] is None:
                g["short"] = d["path"]
        except Exception:
            continue
    return list(groups.values())


def find_channels():
    """Kompatibilität: flache Kanal-Liste (usage 0x02 zuerst)."""
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


def _open(path, retries=2):
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
            time.sleep(0.3)
    raise last_ex


def _close(h):
    try:
        h.close()
    except Exception:
        pass


class _Link:
    """Kurzer + langer Handle desselben Receivers."""

    def __init__(self, short_h, long_h):
        self.s = short_h or long_h
        self.l = long_h or short_h

    def close(self):
        if self.s is not None and self.s is not self.l:
            _close(self.s)
        if self.l is not None:
            _close(self.l)


def _drain(h, tries=6, timeout=60):
    if h is None:
        return
    for _ in range(tries):
        try:
            r = h.read(64, timeout_ms=timeout)
        except Exception:
            break
        if not r:
            break


def _req_short(link, dev, feat_idx, func_byte, p1=0, p2=0, p3=0,
               reads=6, timeout=500):
    """Kurze Anfrage auf dem Kurz-Kanal, swid-korrelierte Antwort."""
    h = link.s
    if h is None:
        return None
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
                and r[1] == dev and r[2] == feat_idx \
                and r[3] == func_byte:
            return bytes(r)
    return None


def _req_long(link, dev, feat_idx, func_byte, reads=6, timeout=500):
    h = link.l
    if h is None:
        return None
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
                and r[1] == dev and r[2] == feat_idx \
                and r[3] == func_byte:
            return bytes(r)
    return None


def get_feature_index(link, dev, feature):
    r = _req_short(link, dev, 0x00, SWID,
                   (feature >> 8) & 0xFF, feature & 0xFF, 0x00)
    if not r or len(r) < 7:
        return None
    idx = r[4]
    if r[2] == 0xFF or idx == 0:
        return None
    return idx


def query_unified(link, dev, idx):
    fn = 0x10 | SWID  # fn 1 = getBatteryInfo
    r = _req_long(link, dev, idx, fn)
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


def query_voltage(link, dev, idx):
    """0x1001 fn 0: Spannung mV (exakt) + % (Kurven-Schätzung)."""
    fn = 0x00 | SWID  # fn 0 = getBatteryInfo
    r = _req_long(link, dev, idx, fn)
    if not r or len(r) < 7:
        return None
    mv = (r[4] << 8) | r[5]
    if mv < 2500 or mv > 5000:
        return None
    flags = r[6]
    if flags & 0x80 == 0:
        charging, full = False, False
    else:
        sub = flags & 0x03
        if sub in (0x01, 0x03):
            charging, full = False, True
        elif sub == 0x02:
            charging, full = False, False
        else:
            charging, full = True, False
    return {"percentage": voltage_to_pct(mv), "level": None,
            "charging": charging, "fullyCharged": full,
            "status_code": flags, "voltage_mv": int(mv),
            "critical": bool(flags & 0x20)}


def query_batt_status(link, dev, idx):
    fn = 0x00 | SWID  # fn 0
    r = _req_long(link, dev, idx, fn)
    if not r or len(r) < 5:
        return None
    pct = r[4]
    if pct > 100:
        return None
    return {"percentage": int(pct), "level": None,
            "charging": False, "fullyCharged": pct >= 100,
            "status_code": None}


def query_device(link, dev):
    """Ein Geräte-Index: 0x1004, dann 0x1001, dann 0x1000."""
    idx = get_feature_index(link, dev, F_UNIFIED)
    if idx:
        q = query_unified(link, dev, idx)
        if q:
            q["source_feature"] = "0x1004"
            return q
    idx = get_feature_index(link, dev, F_BATT_VOLT)
    if idx:
        q = query_voltage(link, dev, idx)
        if q:
            q["source_feature"] = "0x1001"
            return q
    idx = get_feature_index(link, dev, F_BATT_STATUS)
    if idx:
        q = query_batt_status(link, dev, idx)
        if q:
            q["source_feature"] = "0x1000"
            return q
    return None


def read_all(timeout_total=25.0):
    """Alle HID++-Batterien: [{pid, index, percentage, charging, ...}]."""
    found = []
    t_end = time.monotonic() + timeout_total
    for grp in find_receivers():
        if time.monotonic() > t_end:
            break
        link = None
        try:
            sh = _open(grp["short"]) if grp.get("short") else None
        except Exception:
            sh = None
        try:
            lo = _open(grp["long"]) if grp.get("long") else None
        except Exception:
            lo = None
        if sh is None and lo is None:
            continue
        link = _Link(sh, lo)
        try:
            for dev in DEVICE_INDICES:
                if time.monotonic() > t_end:
                    break
                try:
                    q = query_device(link, dev)
                except Exception:
                    q = None
                if q:
                    q["index"] = dev
                    q["pid"] = grp.get("pid")
                    found.append(q)
        finally:
            link.close()
        if found:
            break  # erster antwortender Receiver reicht
    return found


def read_one(timeout_total=20.0):
    """Bequemlichkeit: erstes gefundenes Gerät oder None."""
    all_devs = read_all(timeout_total=timeout_total)
    return all_devs[0] if all_devs else None
