"""LogiBatteryWidget – Akkustand aller G HUB Geräte als Widget + Tray.

Start (aus Projektroot):  python src/app.py [--demo]
Benötigt: G HUB muss laufen (lghub_agent auf Port 9010).
"""
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk

if getattr(sys, "frozen", False):
    # Gebaute .exe: Daten liegen neben der Exe
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
    sys.path.insert(0, BASE_DIR)
else:
    # Dev: app.py liegt in src/, Daten im Projektroot
    BASE_DIR = os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(BASE_DIR, "src"))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

import ghub

try:
    import settings_ui  # für PyInstaller-Bundling + Design-Editor
except Exception:
    settings_ui = None  # type: ignore

try:
    import history_ui  # für PyInstaller-Bundling + Verlauf
except Exception:
    history_ui = None  # type: ignore

try:
    import diag_ui  # für PyInstaller-Bundling + Diagnose
except Exception:
    diag_ui = None  # type: ignore

try:
    import fallback  # redundante Quellen (DB, Extern, HID)
except Exception:
    fallback = None  # type: ignore

try:
    import mqtt_pub  # MQTT-Export (Home Assistant)
except Exception:
    mqtt_pub = None  # type: ignore

try:
    import webdash  # lokales Web-Dashboard
except Exception:
    webdash = None  # type: ignore

DEFAULT_CONFIG = {
    "refresh_seconds": 30,
    "low_threshold": 20,
    "always_on_top": False,
    "pin_background": True,
    "opacity": 0.93,
    "x": None,
    "y": None,
    # Warnungen
    "warn_sound": True,
    "warn_full": True,
    # Fenster-Extras
    "click_through": False,
    "snap_edges": True,
    "hotkey_enabled": True,
    "hotkey": "ctrl+alt+l",
    "auto_theme": False,
    # Verlauf + Overlay
    "history_enabled": True,
    "overlay_enabled": False,
    "overlay_path": "overlay.txt",
    "overlay_template": "{name}: {pct}%",
    # Backup-Systeme
    "ghub_autostart": True,
    "ghub_auto_repair": True,
    "cache_fallback": True,
    "ghub_db": True,
    "ext_fallback": True,
    "hid_direct": True,
    "logitray_enabled": True,
    # Pro-Gerät: {id-oder-name: {alias, hidden, low}}
    "devices_cfg": {},
    # Darstellung
    "show_details": True,
    # Gaming-Modus
    "game_mode": False,
    # MQTT
    "mqtt_enabled": False,
    "mqtt_host": "localhost",
    "mqtt_port": 1883,
    "mqtt_user": "",
    "mqtt_password": "",
    "mqtt_topic": "logi-akku",
    "mqtt_ha": True,
    # Web-Dashboard
    "web_enabled": True,
    "web_port": 8321,
}

HISTORY_PATH = os.path.join(BASE_DIR, "history.csv")
HISTORY_KEEP_DAYS = 30
CACHE_PATH = os.path.join(BASE_DIR, "cache.json")


def find_ghub_exe():
    """Sucht die G HUB Startdatei an bekannten Orten."""
    candidates = [
        r"C:\Program Files\LGHUB\lghub.exe",
        r"C:\Program Files\Logitech\LGHUB\lghub.exe",
        os.path.expandvars(r"%ProgramFiles%\LGHUB\lghub.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\LGHUB\lghub.exe"),
    ]
    for c in candidates:
        try:
            if c and os.path.isfile(c):
                return c
        except Exception:
            continue
    # Registry: Uninstall-Eintrag
    try:
        import winreg
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for key_path in (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                             r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"):
                try:
                    key = winreg.OpenKey(root, key_path, 0, winreg.KEY_READ)
                except OSError:
                    continue
                try:
                    i = 0
                    while True:
                        try:
                            sub = winreg.EnumKey(key, i)
                        except OSError:
                            break
                        i += 1
                        if "lghub" not in sub.lower() and "g hub" not in sub.lower():
                            continue
                        try:
                            sk = winreg.OpenKey(key, sub, 0, winreg.KEY_READ)
                            loc, _ = winreg.QueryValueEx(sk, "InstallLocation")
                            winreg.CloseKey(sk)
                            exe = os.path.join(loc, "lghub.exe")
                            if os.path.isfile(exe):
                                winreg.CloseKey(key)
                                return exe
                        except OSError:
                            continue
                finally:
                    winreg.CloseKey(key)
    except Exception:
        pass
    return None


def ghub_process_running():
    """True wenn ein lghub-Prozess läuft (auch wenn Port noch zu ist)."""
    try:
        import ctypes
        from ctypes import wintypes
        TH32CS_SNAPPROCESS = 0x00000002
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snap == wintypes.HANDLE(-1).value:
            return False
        class PE(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD),
                        ("cntUsage", wintypes.DWORD),
                        ("th32ProcessID", wintypes.DWORD),
                        ("th32DefaultHeapID", ctypes.c_ulonglong),
                        ("th32ModuleID", wintypes.DWORD),
                        ("cntThreads", wintypes.DWORD),
                        ("th32ParentProcessID", wintypes.DWORD),
                        ("pcPriClassBase", wintypes.LONG),
                        ("dwFlags", wintypes.DWORD),
                        ("szExeFile", wintypes.CHAR * 260)]
        try:
            pe = PE()
            pe.dwSize = ctypes.sizeof(PE)
            ok = kernel32.Process32First(snap, ctypes.byref(pe))
            while ok:
                try:
                    name = pe.szExeFile.decode(
                        "utf-8", "ignore").lower()
                except Exception:
                    name = ""
                if "lghub" in name:
                    return True
                ok = kernel32.Process32Next(snap, ctypes.byref(pe))
        finally:
            kernel32.CloseHandle(snap)
    except Exception:
        pass
    return False


def launch_ghub():
    """Startet G HUB (einmalig). Gibt True zurück wenn Start angestoßen."""
    exe = find_ghub_exe()
    if not exe:
        return False
    try:
        import subprocess
        subprocess.Popen([exe], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, close_fds=True)
        return True
    except Exception as ex:
        print("G HUB Start-Fehler:", ex)
        return False


def save_cache(devices):
    try:
        import time as _t
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump({"ts": int(_t.time()), "devices": devices}, f)
    except Exception:
        pass


def load_cache():
    """Gibt (devices, timestamp) oder ([], None) zurück."""
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        devs = data.get("devices", [])
        for d in devs:
            d["stale"] = True
        return devs, data.get("ts")
    except Exception:
        return [], None


def restart_ghub():
    """Startet den G HUB Agent neu (Reparatur bei hängendem G HUB)."""
    try:
        import subprocess
        import time as _t
        si = subprocess.STARTUPINFO()
        try:
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        except Exception:
            pass
        subprocess.run(["taskkill", "/F", "/IM", "lghub_agent.exe"],
                       capture_output=True, startupinfo=si, timeout=15)
        _t.sleep(2)
        return launch_ghub()
    except Exception as ex:
        print("G HUB Neustart-Fehler:", ex)
        return False


_hid_cache = {"ts": 0.0, "n": 0}


def hid_devices_present():
    """Anzahl Logitech HID-Geräte (5s gecacht). Unabhängig von G HUB."""
    try:
        import time as _t
        now = _t.monotonic()
        if now - _hid_cache["ts"] < 5:
            return _hid_cache["n"]
        n = 0
        try:
            import hid as _hid
            n = len(_hid.enumerate(0x046D))
        except Exception:
            n = 0
        _hid_cache["ts"] = now
        _hid_cache["n"] = n
        return n
    except Exception:
        return 0


def diagnose(app):
    """Liste (Name, ok, Detail) über alle Redundanz-Ebenen."""
    import ghub as _ghub
    rows = []
    try:
        n = hid_devices_present()
        rows.append(("USB/Dongle erkannt", n > 0,
                     f"{n} Logitech HID-Gerät(e)" if n else "kein Gerät – Kabel/Dongle prüfen"))
    except Exception:
        rows.append(("USB/Dongle erkannt", False, "Prüfung fehlgeschlagen"))
    try:
        p = ghub_process_running()
        rows.append(("G HUB Prozess", p,
                     "lghub läuft" if p else "nicht gestartet"))
    except Exception:
        rows.append(("G HUB Prozess", False, "?"))
    try:
        port = _ghub.ghub_running(timeout=1.0)
        rows.append(("G HUB Schnittstelle :9010", port,
                     "erreichbar" if port else "nicht erreichbar"))
    except Exception:
        rows.append(("G HUB Schnittstelle :9010", False, "?"))
    try:
        live = bool(getattr(app, "live_ok", False))
        rows.append(("Live-Push", live,
                     "verbunden" if live else "getrennt (Polling aktiv)"))
    except Exception:
        rows.append(("Live-Push", False, "?"))
    try:
        import fallback as _fb
        db = _fb.read_db_batteries()
        rows.append(("G HUB Datei-DB", bool(db),
                     f"{len(db)} Eintrag/Einträge" if db
                     else "keine Einträge"))
    except Exception:
        rows.append(("G HUB Datei-DB", False, "?"))
    try:
        import fallback as _fb2
        if _fb2.ext_available():
            rows.append(("Extern :12321", True, "Tool gefunden"))
        else:
            rows.append(("Extern :12321", False, "nicht installiert"))
    except Exception:
        rows.append(("Extern :12321", False, "?"))
    try:
        import webdash as _wd
        if _wd.is_running():
            rows.append(("Web-Dashboard", True,
                         f"http://127.0.0.1:{_wd.port()}/ läuft"))
        else:
            rows.append(("Web-Dashboard", False, "ausgeschaltet"))
    except Exception:
        rows.append(("Web-Dashboard", False, "?"))
    try:
        hid = getattr(app, "_last_hid", []) or []
        import time as _t2
        ts = getattr(app, "_last_hid_ts", None)
        fresh = ts and (_t2.time() - ts < 600)
        lt = getattr(app, "_last_logitray", []) or []
        lts = getattr(app, "_last_logitray_ts", None)
        lfresh = lts and (_t2.time() - lts < 600)
        if lt and lfresh:
            rows.append(("HID-Direkt (logitray)", True,
                         f"{len(lt)} Messwert(e) live"))
        elif hid and fresh:
            rows.append(("HID-Direkt", True,
                         f"{len(hid)} Messwert(e)"))
        else:
            import os as _os
            import fallback as _fb3
            bundled = bool(_fb3.logitray_exe())
            rows.append(("HID-Direkt", False,
                         "logitray bereit" if bundled
                         else "experimentell – kein Messwert"))
    except Exception:
        rows.append(("HID-Direkt", False, "?"))
    try:
        devs = getattr(app, "devices", []) or []
        fresh = [d for d in devs if not d.get("stale")]
        if fresh:
            rows.append(("Messwerte", True,
                         f"{len(fresh)} aktuelle(r) Wert(e)"))
        elif devs:
            rows.append(("Messwerte (Cache)", True,
                         f"{len(devs)} alte(r) Wert(e)"))
        else:
            rows.append(("Messwerte", False, "keine Werte"))
    except Exception:
        rows.append(("Messwerte", False, "?"))
    try:
        _devs, ts = load_cache()
        if ts:
            import time as _t
            rows.append(("Cache-Backup", True,
                         "Stand " + _t.strftime("%d.%m %H:%M",
                                                _t.localtime(ts))))
        else:
            rows.append(("Cache-Backup", False, "noch kein Stand"))
    except Exception:
        rows.append(("Cache-Backup", False, "?"))
    return rows

HISTORY_PATH = os.path.join(BASE_DIR, "history.csv")
HISTORY_KEEP_DAYS = 30


def play_sound(kind="low"):
    """Kurzer Hinweiston (Windows-Systemsound). Blockiert nicht."""
    def _beep():
        try:
            import winsound
            if kind == "low":
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            else:
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
        except Exception:
            pass
    try:
        import threading as _th
        _th.Thread(target=_beep, daemon=True).start()
    except Exception:
        pass


def set_click_through(tk_root, enable: bool):
    """Klicks gehen durchs Widget hindurch (bzw. wieder normal)."""
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetParent(tk_root.winfo_id())
        GWL_EXSTYLE = -20
        WS_EX_TRANSPARENT = 0x00000020
        WS_EX_LAYERED = 0x00080000
        user32 = ctypes.windll.user32
        ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if enable:
            ex |= WS_EX_TRANSPARENT | WS_EX_LAYERED
        else:
            ex &= ~WS_EX_TRANSPARENT
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex)
    except Exception as ex:
        print("click-through Fehler:", ex)


def windows_uses_light_theme():
    """True = Windows Apps im Hell-Modus, False = Dunkel, None = unbekannt."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            0, winreg.KEY_READ)
        try:
            val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return bool(val)
        finally:
            winreg.CloseKey(key)
    except Exception:
        return None


def append_history(device_id, name, pct, charging):
    """Hängt einen Messwert an history.csv an (max 1 Zeile/Sek.)."""
    try:
        import csv
        import time as _t
        with open(HISTORY_PATH, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([int(_t.time()), device_id, name,
                        pct if pct is not None else "",
                        1 if charging else 0])
    except Exception:
        pass


def read_history(days=HISTORY_KEEP_DAYS):
    """Liest Verlauf als Liste von Dicts (nur letzte N Tage)."""
    import csv
    import time as _t
    out = []
    try:
        cutoff = _t.time() - days * 86400
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            for row in csv.reader(f):
                try:
                    if len(row) < 5:
                        continue
                    ts = int(row[0])
                    if ts < cutoff:
                        continue
                    out.append({
                        "ts": ts, "id": row[1], "name": row[2],
                        "pct": int(row[3]) if str(row[3]).strip() != "" else None,
                        "charging": row[4] == "1",
                    })
                except Exception:
                    continue
    except FileNotFoundError:
        pass
    except Exception:
        pass
    return out


def write_overlay(path, devices, template):
    """Schreibt Akkustände für OBS/Stream als Textdatei (atomar)."""
    try:
        if not os.path.isabs(path):
            path = os.path.join(BASE_DIR, path)
        lines = []
        for d in devices:
            p = d.get("percentage")
            try:
                lines.append(template.format(
                    name=d.get("name", "?"),
                    pct="–" if p is None else p,
                    raw="" if p is None else p,
                    charging="⚡" if d.get("charging") else "",
                    state=d.get("state", ""),
                ))
            except Exception:
                continue
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        os.replace(tmp, path)
    except Exception as ex:
        print("Overlay-Fehler:", ex)


def fg_is_fullscreen():
    """True wenn das Vordergrundfenster den ganzen Bildschirm füllt."""
    try:
        import ctypes
        from ctypes import wintypes
        u32 = ctypes.windll.user32
        hwnd = u32.GetForegroundWindow()
        if not hwnd:
            return False
        r = wintypes.RECT()
        if not u32.GetWindowRect(hwnd, ctypes.byref(r)):
            return False
        sw = u32.GetSystemMetrics(0)
        sh = u32.GetSystemMetrics(1)
        # Toleranz 2px (echtes Vollbild/borderless), maximierte Fenster
        # ragen durch unsichtbare Rahmen weiter über und zählen nicht
        return (abs(r.left) <= 2 and abs(r.top) <= 2
                and abs((r.right - r.left) - sw) <= 2
                and abs((r.bottom - r.top) - sh) <= 2)
    except Exception:
        return False


def forecast_for(device_id, hours=8):
    """Lade-Prognose aus Verlauf: {rate_h, empty_in_h, full_in_h, trend}."""
    res = {"rate_h": None, "empty_in_h": None, "full_in_h": None,
           "trend": "–"}
    try:
        rows = [r for r in read_history(days=2)
                if r.get("id") == device_id and r.get("pct") is not None]
        if len(rows) < 4:
            return res
        import time as _t
        cutoff = _t.time() - hours * 3600
        rows = [r for r in rows if r["ts"] >= cutoff]
        if len(rows) < 4:
            return res
        rows.sort(key=lambda r: r["ts"])

        def slope(pts):
            n = len(pts)
            if n < 3:
                return None
            mx = sum(p[0] for p in pts) / n
            my = sum(p[1] for p in pts) / n
            den = sum((p[0] - mx) ** 2 for p in pts)
            if den <= 0:
                return None
            return sum((p[0] - mx) * (p[1] - my)
                       for p in pts) / den * 3600  # %/h

        dis = [(r["ts"], r["pct"]) for r in rows if not r["charging"]]
        chg = [(r["ts"], r["pct"]) for r in rows if r["charging"]]
        cur = rows[-1]["pct"]
        rs = slope(dis)
        if rs is not None and rs < -0.05:
            res["rate_h"] = round(rs, 1)
            res["empty_in_h"] = round(cur / -rs, 1)
        cs = slope(chg)
        if cs is not None and cs > 0.05:
            res["full_in_h"] = round((100 - cur) / cs, 1)
        t1 = _t.time() - 3600
        old = [r["pct"] for r in rows if r["ts"] < t1]
        new = [r["pct"] for r in rows if r["ts"] >= t1]
        if old and new:
            d = sum(new) / len(new) - sum(old) / len(old)
            res["trend"] = "↘ fallend" if d < -0.5 else (
                "↗ steigend" if d > 0.5 else "→ stabil")
        return res
    except Exception:
        return res


def fmt_dauer(stunden):
    try:
        h = int(stunden)
        m = int(round((stunden - h) * 60))
        if h <= 0:
            return f"{m} Min"
        return f"{h}h {m:02d}min"
    except Exception:
        return "–"


def export_config(path):
    import shutil
    shutil.copy(CONFIG_PATH, path)


def import_config(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("keine gültige Config")
    cfg = load_config()
    cfg.update(data)
    if isinstance(data.get("theme"), dict):
        cfg["theme"].update(data["theme"])
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    return cfg


def pin_window_to_bottom(tk_root):
    """Schiebt das Fenster ganz nach hinten (unter alle Apps).

    Nutzt Win32 SetWindowPos mit HWND_BOTTOM + NOACTIVATE, dazu
    Toolwindow-Style damit es nicht in Taskleiste/Alt-Tab auftaucht.
    """
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetParent(tk_root.winfo_id())
        # Ex-Style: TOOLWINDOW (kein Taskleisten-Button) + NOACTIVATE (kein Fokus-Klau)
        GWL_EXSTYLE = -20
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_NOACTIVATE = 0x08000000
        user32 = ctypes.windll.user32
        ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
        # Nach ganz hinten
        HWND_BOTTOM = 1
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_NOACTIVATE = 0x0010
        user32.SetWindowPos(hwnd, HWND_BOTTOM, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
    except Exception as ex:
        print("pin_to_bottom Fehler:", ex)
    try:
        tk_root.lower()
    except Exception:
        pass

BG = "#1a1d21"
CARD = "#24282e"
FG = "#f2f2f2"
DIM = "#9aa0a6"
ACCENT = "#00b4ff"

DEFAULT_THEME = {
    "bg": "#1a1d21",
    "card": "#24282e",
    "header_bg": "#111417",
    "fg": "#f2f2f2",
    "dim": "#9aa0a6",
    "accent": "#00b4ff",
    "bar_high": "#2ecc71",
    "bar_mid": "#f39c12",
    "bar_low": "#e74c3c",
    "bar_charging": "#2ecc71",
    "bar_track": "#14161a",
    "font_family": "Segoe UI",
    "font_size_title": 10,
    "font_size_name": 10,
    "font_size_pct": 11,
    "bar_height": 12,
    "widget_width": 320,
    "show_mileage": True,
    "show_header": True,
    "show_footer": True,
    "show_status": True,
}

THEMES = {
    "Dunkel": dict(DEFAULT_THEME),
    "Hell": {
        "bg": "#f2f2f2", "card": "#ffffff", "header_bg": "#e1e4e8",
        "fg": "#111111", "dim": "#666666", "accent": "#0078d4",
        "bar_high": "#107c10", "bar_mid": "#d83b01", "bar_low": "#a4262c",
        "bar_charging": "#107c10", "bar_track": "#d0d0d0",
        "font_family": "Segoe UI", "font_size_title": 10,
        "font_size_name": 10, "font_size_pct": 11, "bar_height": 12,
        "widget_width": 320, "show_mileage": True, "show_header": True,
        "show_footer": True, "show_status": True,
    },
    "Neon": {
        "bg": "#000000", "card": "#0d0d1a", "header_bg": "#000000",
        "fg": "#00ffcc", "dim": "#557777", "accent": "#ff00ff",
        "bar_high": "#00ffcc", "bar_mid": "#ffcc00", "bar_low": "#ff2266",
        "bar_charging": "#00ffcc", "bar_track": "#1a1a2e",
        "font_family": "Consolas", "font_size_title": 10,
        "font_size_name": 10, "font_size_pct": 12, "bar_height": 14,
        "widget_width": 340, "show_mileage": True, "show_header": True,
        "show_footer": True, "show_status": True,
    },
    "Minimal": {
        "bg": "#2b2b2b", "card": "#2b2b2b", "header_bg": "#2b2b2b",
        "fg": "#e8e8e8", "dim": "#a0a0a0", "accent": "#e8e8e8",
        "bar_high": "#e8e8e8", "bar_mid": "#e8e8e8", "bar_low": "#e8e8e8",
        "bar_charging": "#e8e8e8", "bar_track": "#3a3a3a",
        "font_family": "Segoe UI", "font_size_title": 9,
        "font_size_name": 9, "font_size_pct": 10, "bar_height": 6,
        "widget_width": 300, "show_mileage": False, "show_header": False,
        "show_footer": False, "show_status": False,
    },
}

AUTOSTART_NAME = "LogiBatteryWidget"

_single_mutex_handle = None


def ensure_single_instance(name="LogiBatteryWidget_SingleInstance"):
    """Verhindert Doppelstart (zweiter Start beendet sich sofort).

    Wichtig, damit nicht zwei Instanzen gleichzeitig die config.json
    (u.a. Position) überschreiben.
    """
    global _single_mutex_handle
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        h = kernel32.CreateMutexW(None, False, name)
        if not h:
            return True
        if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(h)
            return False
        _single_mutex_handle = h
        return True
    except Exception:
        return True


def autostart_command():
    # Als .exe (PyInstaller): direkt die Exe eintragen
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    # Unsichtbar starten via pythonw + src/app.py (kein Konsolenfenster)
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pyw):
        pyw = sys.executable
    return f'"{pyw}" "{os.path.join(BASE_DIR, "src", "app.py")}"'


def is_autostart_enabled():
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run",
                             0, winreg.KEY_READ)
        try:
            winreg.QueryValueEx(key, AUTOSTART_NAME)
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except Exception:
        return False


def set_autostart(enable: bool) -> bool:
    """Autostart via HKCU Run-Key an/aus. Gibt Erfolg zurück."""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run",
                             0, winreg.KEY_SET_VALUE)
        try:
            if enable:
                winreg.SetValueEx(key, AUTOSTART_NAME, 0, winreg.REG_SZ,
                                  autostart_command())
            else:
                try:
                    winreg.DeleteValue(key, AUTOSTART_NAME)
                except FileNotFoundError:
                    pass
        finally:
            winreg.CloseKey(key)
        return True
    except Exception as ex:
        print("Autostart-Fehler:", ex)
        return False


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    cfg["theme"] = dict(DEFAULT_THEME)
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            th = loaded.pop("theme", None)
            cfg.update(loaded)
            if isinstance(th, dict):
                cfg["theme"].update(th)
    except Exception:
        pass
    return cfg


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


def bar_color(pct, charging):
    if charging:
        return "#2ecc71"
    if pct is None:
        return "#555555"
    if pct < 20:
        return "#e74c3c"
    if pct < 50:
        return "#f39c12"
    return "#2ecc71"


def make_tray_icon_image(pct):
    """64x64 Batterie-Icon via Pillow erzeugen."""
    from PIL import Image, ImageDraw
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # Gehäuse
    d.rounded_rectangle([8, 20, 52, 48], radius=6, outline="white", width=4)
    d.rectangle([53, 28, 57, 40], fill="white")
    if pct is None:
        d.text((20, 26), "?", fill="white")
    else:
        w = int(40 * max(0, min(100, pct)) / 100)
        col = (46, 204, 113) if pct >= 20 else (231, 76, 60)
        if pct >= 50:
            col = (46, 204, 113)
        elif pct >= 20:
            col = (243, 156, 18)
        d.rectangle([11, 23, 11 + w, 45], fill=col)
    return img


class App:
    def __init__(self, demo=False):
        self.demo = demo or "--demo" in sys.argv
        self.cfg = load_config()
        self.devices = []
        self.last_update = "noch nie"
        self.ghub_ok = False
        self.warned = {}  # device_id -> True (schon niedrig-gewarnt)
        self.warned_full = {}  # device_id -> True (schon voll-gewarnt)
        self.hidden = False
        self._settings_win = None
        self._history_win = None
        self.live_ok = False
        self._live_stop = None
        self._ghub_launch_tried = False  # G-HUB-Autostart nur 1x/Sitzung
        self._ghub_note = ""
        self.cache_ts = None
        self.source = "-"  # live | ghub | ghub-db | ext | hid | cache | -
        self._ghub_fail_count = 0
        self._ghub_ever_ok = False
        self._ghub_repaired = False
        self._diag_win = None
        self._last_hid_try = 0.0
        self._last_hid = []
        self._last_hid_ts = None
        self._last_logitray_try = 0.0
        self._last_logitray = []
        self._last_logitray_ts = None
        self._game_hidden = False
        self._ui_queue = queue.Queue()
        self._last_hist_log = {}  # device_id -> timestamp
        self._hotkey_handle = None

        self.root = tk.Tk()
        self.root.title("Logi Akku")
        try:
            self.root.configure(bg=self.cfg.get("theme", {}).get("bg", BG))
        except Exception:
            self.root.configure(bg=BG)
        self.root.overrideredirect(True)
        # Hintergrund-Modus: NICHT topmost, sondern ganz nach hinten
        self.root.attributes("-topmost", bool(self.cfg.get("always_on_top", False)))
        try:
            # kein Taskleisten-Button
            self.root.attributes("-toolwindow", True)
        except Exception:
            pass
        try:
            self.root.attributes("-alpha", float(self.cfg.get("opacity", 0.93)))
        except Exception:
            pass
        self.root.geometry("320x200+100+100")
        if self.cfg.get("x") is not None and self.cfg.get("y") is not None:
            try:
                self.root.geometry(f"+{int(self.cfg['x'])}+{int(self.cfg['y'])}")
            except Exception:
                pass

        self._build_ui()
        self._drag_data = {"x": 0, "y": 0, "dragging": False,
                           "sx": 0, "sy": 0}
        self._last_pos_save = 0.0
        # Ziehen von überall (Toplevel-Bindung greift für alle Kinder,
        # auch bei ausgeblendeter Titelzeile). Klicks bleiben erhalten:
        # erst ab 4px Bewegung wird gezogen.
        self.root.bind("<ButtonPress-1>", self._drag_start)
        self.root.bind("<B1-Motion>", self._drag_move)
        self.root.bind("<ButtonRelease-1>", self._drag_end)
        # Rechtsklick-Menü: Vordergrund/Hintergrund umschalten
        self.root.bind("<Button-3>", self._show_context_menu)

        # direkt nach hinten schieben + dort halten
        self.root.update_idletasks()
        if self.cfg.get("pin_background", True):
            pin_window_to_bottom(self.root)
        self.root.after(2000, self._keep_at_bottom)

        # Tray in eigenem Thread
        self.tray = None
        self.tray_thread = None
        self._start_tray()

        # Live-Push: Batterie-Events sofort (Fallback bleibt das Polling)
        if not self.demo:
            try:
                import threading as _th
                self._live_stop = _th.Event()
                ghub.start_battery_listener(
                    self._on_battery_push,
                    self._live_stop,
                    on_status=self._on_live_status,
                )
            except Exception as ex:
                print("Live-Listener Fehler:", ex)

        self.root.after(500, lambda: self.refresh_async(first=True))
        self.root.after(15000, self._save_pos_loop)
        self.root.after(60000, self._auto_theme_loop)
        self.root.after(5000, self._game_mode_loop)
        self.root.after(250, self._poll_ui_queue)
        self.root.protocol("WM_DELETE_WINDOW", self.quit_app)

        # Web-Dashboard starten
        try:
            self.restart_web()
        except Exception:
            pass

        # gespeicherter Click-Through + Hotkey aktivieren
        try:
            if self.cfg.get("click_through"):
                self.root.update_idletasks()
                set_click_through(self.root, True)
        except Exception:
            pass
        self._register_hotkey()

    # ---------- Hotkey ----------
    def _register_hotkey(self):
        try:
            import keyboard
        except Exception:
            return
        try:
            if self._hotkey_handle is not None:
                try:
                    import keyboard as _kb
                    _kb.remove_hotkey(self._hotkey_handle)
                except Exception:
                    pass
                self._hotkey_handle = None
            if self.cfg.get("hotkey_enabled", True):
                import keyboard as _kb
                hk = (self.cfg.get("hotkey") or "ctrl+alt+l").strip().lower()
                self._hotkey_handle = _kb.add_hotkey(
                    hk, lambda: self._hotkey_pressed())
        except Exception as ex:
            print("Hotkey-Fehler:", ex)

    def _hotkey_pressed(self):
        self._ui_call(self.toggle_window)

    # ---------- Auto-Theme (Windows Hell/Dunkel folgen) ----------
    def _auto_theme_loop(self):
        try:
            if self.cfg.get("auto_theme"):
                light = windows_uses_light_theme()
                if light is not None:
                    want = "Hell" if light else "Dunkel"
                    cur_bg = self.cfg.get("theme", {}).get("bg")
                    if cur_bg != THEMES[want].get("bg"):
                        self.cfg["theme"].update(THEMES[want])
                        save_config(self.cfg)
                        self.apply_theme()
        except Exception:
            pass
        try:
            self.root.after(60000, self._auto_theme_loop)
        except Exception:
            pass

    # ---------- Live-Push ----------
    def _on_live_status(self, connected: bool):
        self.live_ok = bool(connected)
        self._ui_call(self._update_status_only)

    def _update_status_only(self):
        try:
            n = len(self.devices)
            base = (f"G HUB ✓ • {n} Gerät(e) • {self.last_update}"
                    if self.ghub_ok else f"G HUB ✗ • {self.last_update}")
            if self.live_ok and self.ghub_ok:
                base += " • ⚡live"
            self.status_lbl.config(text=base)
        except Exception:
            pass

    def _on_battery_push(self, evt):
        # läuft im Listener-Thread -> über Queue in den UI-Thread
        self._ui_call(lambda e=dict(evt): self._apply_battery_push(e))

    def _apply_battery_push(self, evt):
        try:
            did = evt.get("deviceId")
            hit = False
            for d in self.devices:
                if d.get("id") == did:
                    d["percentage"] = evt.get("percentage")
                    d["charging"] = evt.get("charging", False)
                    if evt.get("mileage") is not None:
                        d["mileage"] = evt.get("mileage")
                    d["critical"] = evt.get("critical", False)
                    d["fullyCharged"] = evt.get("fullyCharged", False)
                    hit = True
                    break
            self.live_ok = True
            self.source = "live"
            self.last_update = time.strftime("%H:%M:%S")
            if hit:
                self._update_ui()
            else:
                # unbekanntes/neues Gerät -> einmal voll laden
                self.refresh_async()
        except Exception:
            pass

    # ---------- Theme ----------
    def T(self, key, default=None):
        try:
            return self.cfg.get("theme", {}).get(key, default)
        except Exception:
            return default

    def theme_bar_color(self, pct, charging):
        th = self.cfg.get("theme", {})
        if charging:
            return th.get("bar_charging", "#2ecc71")
        if pct is None:
            return "#555555"
        if pct < 20:
            return th.get("bar_low", "#e74c3c")
        if pct < 50:
            return th.get("bar_mid", "#f39c12")
        return th.get("bar_high", "#2ecc71")

    def apply_theme(self, apply_win_flags=False):
        th = self.cfg.get("theme", {})
        try:
            self.root.configure(bg=th.get("bg", BG))
            self.root.attributes("-alpha", float(self.cfg.get("opacity", 0.93)))
            w = int(th.get("widget_width", 320))
            try:
                h = self.root.winfo_height()
                if h < 50:
                    h = 200
                self.root.geometry(f"{w}x{h}")
            except Exception:
                pass
            if apply_win_flags:
                self.root.attributes("-topmost", bool(self.cfg.get("always_on_top", False)))
                if self.cfg.get("pin_background", True) and not self.cfg.get("always_on_top", False):
                    pin_window_to_bottom(self.root)
                elif self.cfg.get("always_on_top", False):
                    try:
                        self.root.lift()
                    except Exception:
                        pass
        except Exception:
            pass
        self._update_ui()

    def open_settings(self):
        try:
            import settings_ui as _sui
            _sui.open_settings(self)
        except Exception as ex:
            print("Settings-Fehler:", ex)

    # ---------- UI ----------
    def _build_ui(self):
        th = self.cfg.get("theme", {})
        bg = th.get("bg", BG)
        card = th.get("card", CARD)
        hbg = th.get("header_bg", "#111417")
        fg = th.get("fg", FG)
        dim = th.get("dim", DIM)
        ff = th.get("font_family", "Segoe UI")
        ftitle = int(th.get("font_size_title", 10))
        self.header = tk.Frame(self.root, bg=hbg, height=32)
        self.header.pack(fill="x", side="top")
        self.title_lbl = tk.Label(
            self.header, text="  🔋 Logitech Akku", bg=hbg,
            fg=fg, font=(ff, ftitle, "bold"), anchor="w",
        )
        self.title_lbl.pack(side="left", fill="y")

        btn_style = {"bg": hbg, "fg": dim, "bd": 0,
                     "font": (ff, 10), "width": 3,
                     "activebackground": card, "cursor": "hand2"}
        self.btn_hide = tk.Button(self.header, text="–", command=self.hide_to_tray, **btn_style)
        self.btn_hide.pack(side="right")
        self.btn_design = tk.Button(self.header, text="⚙", command=self.open_settings, **btn_style)
        self.btn_design.pack(side="right")
        self.btn_close = tk.Button(self.header, text="✕", command=self.quit_app, **btn_style)
        self.btn_close.pack(side="right")

        self.body = tk.Frame(self.root, bg=bg)
        self.body.pack(fill="both", expand=True, padx=10, pady=8)

        self.status_lbl = tk.Label(self.root, text="", bg=bg, fg=dim, font=(ff, 8))
        self.status_lbl.pack(side="bottom", fill="x", padx=10, pady=(0, 4))

        self.footer = tk.Frame(self.root, bg=bg)
        self.footer.pack(side="bottom", fill="x", padx=10, pady=(0, 8))
        self.refresh_btn = tk.Button(
            self.footer, text="↻ Aktualisieren", command=lambda: self.refresh_async(),
            bg=card, fg=fg, bd=0, font=(ff, 9),
            activebackground=card, cursor="hand2", padx=8, pady=4,
        )
        self.refresh_btn.pack(side="left")
        self.info_lbl = tk.Label(self.footer, text="", bg=bg, fg=dim, font=(ff, 8))
        self.info_lbl.pack(side="right")
        if not th.get("show_header", True):
            self.header.pack_forget()

    def _drag_start(self, e):
        self._drag_data["x"] = e.x_root - self.root.winfo_x()
        self._drag_data["y"] = e.y_root - self.root.winfo_y()
        self._drag_data["sx"] = e.x_root
        self._drag_data["sy"] = e.y_root
        self._drag_data["dragging"] = False

    def _drag_move(self, e):
        # erst ab 4px als Ziehen werten (sonst normale Klicks)
        if not self._drag_data["dragging"]:
            if abs(e.x_root - self._drag_data["sx"]) < 4 \
                    and abs(e.y_root - self._drag_data["sy"]) < 4:
                return
            self._drag_data["dragging"] = True
        x = e.x_root - self._drag_data["x"]
        y = e.y_root - self._drag_data["y"]
        # Ecken-/Kanten-Snap
        if self.cfg.get("snap_edges", True):
            try:
                sw = self.root.winfo_screenwidth()
                sh = self.root.winfo_screenheight()
                ww = self.root.winfo_width() or 320
                wh = self.root.winfo_height() or 200
                m = 15
                if abs(x) < m:
                    x = 0
                if abs(x + ww - sw) < m:
                    x = sw - ww
                if abs(y) < m:
                    y = 0
                if abs(y + wh - sh) < m:
                    y = sh - wh
            except Exception:
                pass
        self.root.geometry(f"+{x}+{y}")
        self.cfg["x"], self.cfg["y"] = x, y
        # gedrosselt mitschreiben (max 1x/2s), Rest beim Loslassen
        now = time.monotonic()
        if now - getattr(self, "_last_pos_save", 0) > 2:
            self._last_pos_save = now
            save_config(self.cfg)

    def _drag_end(self, _e=None):
        try:
            self.cfg["x"] = self.root.winfo_x()
            self.cfg["y"] = self.root.winfo_y()
            save_config(self.cfg)
            self._last_pos_save = time.monotonic()
        except Exception:
            pass

    def _keep_at_bottom(self):
        """Hält das Widget im Hintergrund unter allen Apps (alle 5s)."""
        try:
            if self.cfg.get("pin_background", True) and not self.cfg.get("always_on_top", False):
                pin_window_to_bottom(self.root)
        except Exception:
            pass
        try:
            self.root.after(5000, self._keep_at_bottom)
        except Exception:
            pass

    def _show_context_menu(self, e):
        m = tk.Menu(self.root, tearoff=0, bg=CARD, fg=FG, activebackground="#2f353c")
        bg_txt = "✓ Im Hintergrund (unter Apps)" if self.cfg.get("pin_background", True) else "Im Hintergrund (unter Apps)"
        fg_txt = "✓ Immer im Vordergrund" if self.cfg.get("always_on_top", False) else "Immer im Vordergrund"
        auto_txt = "✓ Autostart mit Windows" if is_autostart_enabled() else "Autostart mit Windows"
        m.add_command(label=bg_txt, command=self._toggle_background)
        m.add_command(label=fg_txt, command=self._toggle_foreground)
        m.add_command(label=auto_txt, command=self._toggle_autostart)
        m.add_separator()
        m.add_command(label="🎨 Design anpassen …", command=self.open_settings)
        m.add_command(label="📈 Verlauf anzeigen …", command=self.open_history)
        m.add_command(label="🔧 Diagnose & Reparatur …",
                      command=self.open_diagnose)
        m.add_command(label="🌐 Dashboard im Browser öffnen",
                      command=self.open_dashboard)
        ct_txt = ("✓ Klicks durchlassen" if self.cfg.get("click_through")
                  else "Klicks durchlassen")
        m.add_command(label=ct_txt, command=self.toggle_click_through)
        m.add_command(label="Widget nach vorne holen", command=self.bring_to_front)
        m.add_command(label="Aktualisieren", command=lambda: self.refresh_async())
        m.add_command(label="Ins Tray minimieren", command=self.hide_to_tray)
        m.add_command(label="Beenden", command=self.quit_app)
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    def _toggle_background(self):
        self.cfg["pin_background"] = not self.cfg.get("pin_background", True)
        if self.cfg["pin_background"]:
            self.cfg["always_on_top"] = False
            self.root.attributes("-topmost", False)
            pin_window_to_bottom(self.root)
        save_config(self.cfg)

    def _toggle_foreground(self):
        self.cfg["always_on_top"] = not self.cfg.get("always_on_top", False)
        if self.cfg["always_on_top"]:
            self.cfg["pin_background"] = False
            self.root.attributes("-topmost", True)
            try:
                self.root.lift()
            except Exception:
                pass
        else:
            self.root.attributes("-topmost", False)
            if self.cfg.get("pin_background", True):
                pin_window_to_bottom(self.root)
        save_config(self.cfg)

    def _toggle_autostart(self):
        target = not is_autostart_enabled()
        ok = set_autostart(target)
        try:
            self._notify("Autostart",
                         "Autostart aktiviert ✓" if (target and ok)
                         else ("Autostart deaktiviert" if (not target and ok)
                               else "Konnte Autostart nicht ändern"))
        except Exception:
            pass

    def bring_to_front(self):
        """Holt das Hintergrund-Widget kurz nach vorne (geht nach ~5s wieder zurück)."""
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
            # kurz topmost an, dann wieder runter damit es klickbar ist
            if not self.cfg.get("always_on_top", False):
                self.root.attributes("-topmost", True)
                self.root.after(1500, lambda: self.root.attributes(
                    "-topmost", bool(self.cfg.get("always_on_top", False))))
        except Exception:
            pass

    def _save_pos_loop(self):
        try:
            self.cfg["x"] = self.root.winfo_x()
            self.cfg["y"] = self.root.winfo_y()
            save_config(self.cfg)
        except Exception:
            pass
        self.root.after(15000, self._save_pos_loop)

    # ---------- Thread-sichere UI-Aufrufe ----------
    # Tk-Aufrufe aus Threads sind unzuverlässig ("main thread is not in
    # main loop"). Darum: Threads legen nur in eine Queue, der
    # Hauptthread holt per after-Schleife ab (250 ms).
    def _ui_call(self, fn):
        try:
            self._ui_queue.put(fn)
        except Exception:
            pass

    def _poll_ui_queue(self):
        try:
            while True:
                fn = self._ui_queue.get_nowait()
                try:
                    fn()
                except Exception as ex:
                    print("UI-Fehler:", ex)
        except Exception:
            pass
        try:
            self.root.after(250, self._poll_ui_queue)
        except Exception:
            pass

    # ---------- Daten ----------
    def refresh_async(self, first=False):
        threading.Thread(target=self._refresh_worker, daemon=True).start()

    def _refresh_worker(self):
        try:
            if self.demo:
                time.sleep(0.3)
                self.devices = list(ghub.DEMO_DEVICES)
                self.ghub_ok = True
            else:
                ok = ghub.ghub_running()
                if not ok:
                    # Backup 1: G HUB automatisch starten (einmal pro Sitzung)
                    if (self.cfg.get("ghub_autostart", True)
                            and not self._ghub_launch_tried
                            and not ghub_process_running()):
                        self._ghub_launch_tried = True
                        if launch_ghub():
                            self._ghub_note = "G HUB wird gestartet …"
                    # Backup 2: hängt G HUB? (lief schon mal, jetzt weg)
                    self._ghub_fail_count += 1
                    if (self.cfg.get("ghub_auto_repair", True)
                            and self._ghub_ever_ok
                            and not self._ghub_repaired
                            and self._ghub_fail_count >= 4
                            and ghub_process_running()):
                        self._ghub_repaired = True
                        if restart_ghub():
                            self._ghub_note = "G HUB hängt – wird neu gestartet …"
                            self._ghub_fail_count = 0
                    self.ghub_ok = False
                    # Redundante Quellen: Extern -> Datei-DB -> HID
                    fb = self._fallback_devices()
                    if fb:
                        self.devices, self.source, self.cache_ts = fb
                    elif self.cfg.get("cache_fallback", True):
                        # Backup: letzten bekannten Stand aus Cache zeigen
                        cached, ts = load_cache()
                        self.devices = cached
                        self.cache_ts = ts
                        self.source = "cache" if cached else "-"
                    else:
                        self.devices = []
                        self.cache_ts = None
                        self.source = "-"
                        self.source = "-"
                else:
                    self._ghub_note = ""
                    self.ghub_ok = True
                    self._ghub_fail_count = 0
                    self._ghub_ever_ok = True
                    self.devices = ghub.get_all_batteries_sync()
                    # Lücken aus Datei-DB füllen (falls ws leere Werte liefert)
                    try:
                        missing = [d for d in self.devices
                                   if d.get("percentage") is None]
                        if missing and self.cfg.get("ghub_db", True):
                            import fallback as _fb2
                            by_id = {e.get("deviceId"): e
                                     for e in _fb2.read_db_batteries()
                                     if e.get("deviceId")}
                            for d in missing:
                                if d.get("id") in by_id:
                                    d["percentage"] = by_id[
                                        d["id"]]["percentage"]
                    except Exception:
                        pass
                    # frische Werte cachen + Stale-Markierung entfernen
                    for d in self.devices:
                        d.pop("stale", None)
                    save_cache(self.devices)
                    self.cache_ts = None
                    if self.devices:
                        self.source = "live" if self.live_ok else "ghub"
            self.last_update = time.strftime("%H:%M:%S")
        except Exception as ex:
            print("Refresh-Fehler:", ex)
            self.ghub_ok = False
            if self.cfg.get("cache_fallback", True) and not self.devices:
                cached, ts = load_cache()
                self.devices = cached
                self.cache_ts = ts
                self.source = "cache" if cached else "-"
        try:
            self._ui_call(self._update_ui)
        except Exception:
            pass
        # bei Ausfall schneller erneut versuchen (15s), sonst Intervall
        if self.ghub_ok or self.demo:
            secs = int(self.cfg.get("refresh_seconds", 30))
            nxt = max(10, secs)
        else:
            nxt = 15
        try:
            self._ui_call(lambda: self.root.after(
                nxt * 1000, lambda: self.refresh_async()))
        except Exception:
            pass

    def _update_ui(self):
        th = self.cfg.get("theme", {})
        bg = th.get("bg", BG)
        fg = th.get("fg", FG)
        dim = th.get("dim", DIM)
        ff = th.get("font_family", "Segoe UI")
        w = int(th.get("widget_width", 320))
        for wdg in self.body.winfo_children():
            wdg.destroy()
        try:
            self.body.configure(bg=bg)
            self.root.configure(bg=bg)
            self.footer.configure(bg=bg)
            self.status_lbl.configure(bg=bg, fg=dim, font=(ff, 8))
            self.info_lbl.configure(bg=bg, fg=dim, font=(ff, 8))
            self.refresh_btn.configure(bg=th.get("card", CARD), fg=fg,
                                       font=(ff, 9),
                                       activebackground=th.get("card", CARD))
            # Sichtbarkeiten
            if th.get("show_header", True):
                try:
                    self.header.pack(fill="x", side="top", before=self.body)
                except Exception:
                    pass
            else:
                try:
                    self.header.pack_forget()
                except Exception:
                    pass
            if th.get("show_footer", True):
                try:
                    self.footer.pack(side="bottom", fill="x", padx=10, pady=(0, 8))
                except Exception:
                    pass
            else:
                try:
                    self.footer.pack_forget()
                except Exception:
                    pass
            if th.get("show_status", True):
                try:
                    self.status_lbl.pack(side="bottom", fill="x", padx=10, pady=(0, 4))
                except Exception:
                    pass
            else:
                try:
                    self.status_lbl.pack_forget()
                except Exception:
                    pass
        except Exception:
            pass

        if not self.ghub_ok and not self.demo and not self.devices:
            note = getattr(self, "_ghub_note", "")
            txt = "⚠ G HUB läuft nicht"
            if ghub_process_running():
                txt += "\n\nG HUB startet gerade …\nVerbindung wird aufgebaut."
            elif note:
                txt += f"\n\n{note}"
            else:
                txt += ("\n\nBitte Logitech G HUB starten\n"
                        "und dann Aktualisieren.")
            tk.Label(
                self.body,
                text=txt,
                bg=bg, fg="#f39c12", font=(ff, 10),
                justify="center",
            ).pack(expand=True, pady=20)
        elif not self.devices:
            tk.Label(
                self.body, text="Keine Geräte mit Akku gefunden.",
                bg=bg, fg=dim, font=(ff, 10),
            ).pack(expand=True, pady=20)
        else:
            for dev in self.visible_devices():
                self._device_card(self.body, dev)
            if not self.ghub_ok and not self.demo:
                # Cache-Hinweis unter den alten Werten
                try:
                    import time as _t
                    when = ""
                    if self.cache_ts:
                        when = _t.strftime("Stand %H:%M",
                                           _t.localtime(self.cache_ts))
                    tk.Label(self.body,
                             text=f"⚠ {when} – warte auf G HUB …".strip(),
                             bg=bg, fg="#f39c12",
                             font=(ff, 8)).pack(pady=(2, 0))
                except Exception:
                    pass

        # Statuszeile
        n = len(self.devices)
        if self.demo:
            st = f"Demo-Modus • {n} Gerät(e) • {self.last_update}"
        elif self.ghub_ok:
            st = f"G HUB ✓ • {n} Gerät(e) • {self.last_update}"
            if self.live_ok:
                st += " • ⚡live"
        else:
            st = f"G HUB ✗ • {self.last_update}"
            tag = {"ghub-db": "Datei-DB", "ext": "Extern",
                   "logitray": "HID live", "hid": "HID",
                   "cache": "Cache"}.get(self.source)
            if self.devices and tag:
                st += f" • {tag}"
        self.status_lbl.config(text=st)
        self.info_lbl.config(
            text=f"Warnung < {self.cfg.get('low_threshold', 20)}%"
        )
        # Fenstergröße anpassen (Breite aus Theme)
        try:
            per = 74 if th.get("show_mileage", True) else 62
            nvis = len(self.visible_devices())
            h = 130 + max(0, nvis) * per
            self.root.geometry(f"{w}x{min(h, 600)}")
        except Exception:
            pass

        self._update_tray()
        self._check_low_battery()
        self._log_history()
        self._write_overlay()
        self._publish_mqtt()

    def _device_card(self, parent, dev):
        th = self.cfg.get("theme", {})
        card = th.get("card", CARD)
        fg = th.get("fg", FG)
        dim = th.get("dim", DIM)
        track = th.get("bar_track", "#14161a")
        ff = th.get("font_family", "Segoe UI")
        fname = int(th.get("font_size_name", 10))
        fpct = int(th.get("font_size_pct", 11))
        bh = int(th.get("bar_height", 12))
        name = dev.get("name", "?")
        pct = dev.get("percentage")
        charging = dev.get("charging", False)
        mileage = dev.get("mileage")
        state = dev.get("state", "")
        stale = bool(dev.get("stale"))

        cardf = tk.Frame(parent, bg=card, bd=0)
        cardf.pack(fill="x", pady=4)

        top = tk.Frame(cardf, bg=card)
        top.pack(fill="x", padx=8, pady=(6, 2))

        # kurzer Name (G502 LIGHTSPEED Wireless Gaming Mouse -> G502 LIGHTSPEED)
        shown = self.disp_name(dev)
        short = shown if len(shown) <= 26 else shown[:24] + "…"
        if stale:
            short = "🕓 " + short
        tk.Label(top, text=short, bg=card, fg=dim if stale else fg,
                 font=(ff, fname, "bold"), anchor="w").pack(side="left")

        if pct is None:
            right = "offline" if state not in ("ACTIVE",) else "–"
            fg_r = dim
        else:
            right = f"{'⚡ ' if charging and not stale else ''}{pct}%"
            fg_r = dim if stale else self.theme_bar_color(pct, charging)
        tk.Label(top, text=right, bg=card, fg=fg_r,
                 font=(ff, fpct, "bold")).pack(side="right")

        # Balken
        bar = tk.Canvas(cardf, height=bh, bg=track, highlightthickness=0)
        bar.pack(fill="x", padx=8, pady=2)
        bar.update_idletasks()
        bw = bar.winfo_width() or 280
        bar.delete("all")
        bar.create_rectangle(0, 0, bw, bh, fill=track, outline="")
        if pct is not None:
            fw = int(bw * max(0, min(100, pct)) / 100)
            fill = dim if stale else self.theme_bar_color(pct, charging)
            bar.create_rectangle(0, 0, fw, bh, fill=fill, outline="")

        sub = ""
        if charging and pct is not None and not stale:
            sub = "lädt…"
            try:
                fc = forecast_for(dev.get("id"))
                if fc.get("full_in_h") is not None:
                    sub += f" • voll in ~{fmt_dauer(fc['full_in_h'])}"
            except Exception:
                pass
        elif mileage and th.get("show_mileage", True) and not stale:
            try:
                sub = f"noch ca. {float(mileage):.0f}h"
            except Exception:
                sub = ""
        elif pct is not None and not charging and not stale:
            try:
                fc = forecast_for(dev.get("id"))
                if fc.get("empty_in_h") is not None:
                    sub = f"leer in ~{fmt_dauer(fc['empty_in_h'])}"
            except Exception:
                pass
        if state not in ("ACTIVE", None, "", "UNKNOWN"):
            sub = (sub + " • " if sub else "") + "getrennt" if pct is None else sub
        if self.cfg.get("show_details", True) and not stale:
            try:
                bits = []
                if dev.get("connection"):
                    bits.append(str(dev["connection"]).title())
                if dev.get("firmware"):
                    bits.append(f"FW {dev['firmware']}")
                if dev.get("lighting"):
                    bits.append("RGB")
                if bits:
                    sub = ((sub + " • ") if sub else "") + " · ".join(bits)
            except Exception:
                pass
        if sub:
            tk.Label(cardf, text=sub, bg=card, fg=dim,
                     font=(ff, 8), anchor="w").pack(fill="x", padx=8, pady=(0, 6))
        else:
            tk.Frame(cardf, bg=card, height=6).pack()

    # ---------- Low Battery + Voll ----------
    def _check_low_battery(self):
        sound = bool(self.cfg.get("warn_sound", True))
        for dev in self.devices:
            # keine Warnungen auf alte Cache-Werte oder ausgeblendete Geräte
            if (dev.get("stale") and not self.ghub_ok) \
                    or self.dev_cfg(dev)["hidden"]:
                continue
            thr = self.dev_threshold(dev)
            pct = dev.get("percentage")
            if pct is None:
                continue
            did = dev.get("id")
            charging = bool(dev.get("charging"))
            # niedrig
            if pct < thr and not charging:
                if did not in self.warned:
                    self.warned[did] = True
                    msg = f"{dev.get('name')}: nur noch {pct}%!"
                    self._notify("🔋 Akku niedrig", msg)
                    if sound:
                        play_sound("low")
            elif pct >= thr + 5:
                self.warned.pop(did, None)
            # voll geladen
            if self.cfg.get("warn_full", True):
                full = bool(dev.get("fullyCharged")) or pct >= 100
                if full and charging:
                    if did not in self.warned_full:
                        self.warned_full[did] = True
                        self._notify("🔋 Voll geladen",
                                     f"{dev.get('name')}: 100 % – Kabel kann ab!")
                        if sound:
                            play_sound("full")
                elif pct is not None and pct < 95:
                    self.warned_full.pop(did, None)

    # ---------- Verlauf + Overlay ----------
    def _log_history(self):
        if not self.cfg.get("history_enabled", True):
            return
        try:
            import time as _t
            now = _t.time()
            for d in self.devices:
                did = d.get("id")
                last = self._last_hist_log.get(did, 0)
                if now - last < 60:
                    continue
                self._last_hist_log[did] = now
                append_history(did, d.get("name", "?"),
                               d.get("percentage"), bool(d.get("charging")))
        except Exception:
            pass

    def _write_overlay(self):
        if not self.cfg.get("overlay_enabled", False):
            return
        devs = []
        for d in self.visible_devices():
            nd = dict(d)
            nd["name"] = self.disp_name(d)
            devs.append(nd)
        write_overlay(self.cfg.get("overlay_path", "overlay.txt"),
                      devs,
                      self.cfg.get("overlay_template", "{name}: {pct}%"))

    def open_history(self):
        try:
            import history_ui as _hui
            _hui.open_history(self)
        except Exception as ex:
            print("Verlauf-Fehler:", ex)

    def open_diagnose(self):
        try:
            import diag_ui as _dui
            _dui.open_diagnose(self)
        except Exception as ex:
            print("Diagnose-Fehler:", ex)

    def source_label(self):
        return {"live": "G HUB Live-Push ⚡",
                "ghub": "G HUB Abfrage",
                "ghub-db": "G HUB Datei-DB",
                "ext": "Externes Tool (:12321)",
                "logitray": "HID direkt (logitray)",
                "hid": "HID direkt",
                "cache": "Cache (alte Werte)"}.get(self.source, "–")

    # ---------- Pro-Gerät ----------
    def dev_cfg(self, dev):
        try:
            all_c = self.cfg.get("devices_cfg", {})
            c = all_c.get(dev.get("id")) or all_c.get(dev.get("name")) or {}
            low = c.get("low", None)
            try:
                low = int(low) if low is not None else None
            except Exception:
                low = None
            return {"alias": str(c.get("alias", "") or ""),
                    "hidden": bool(c.get("hidden", False)),
                    "low": low}
        except Exception:
            return {"alias": "", "hidden": False, "low": None}

    def disp_name(self, dev):
        try:
            a = self.dev_cfg(dev)["alias"].strip()
            return a if a else dev.get("name", "?")
        except Exception:
            return dev.get("name", "?")

    def dev_threshold(self, dev):
        low = self.dev_cfg(dev)["low"]
        if low is not None:
            return low
        return int(self.cfg.get("low_threshold", 20))

    def visible_devices(self):
        try:
            return [d for d in (self.devices or [])
                    if not self.dev_cfg(d)["hidden"]]
        except Exception:
            return list(self.devices or [])

    # ---------- Gaming-Modus ----------
    def _game_mode_loop(self):
        try:
            if self.cfg.get("game_mode", False):
                if fg_is_fullscreen():
                    if self.root.winfo_viewable() and not self._game_hidden:
                        self._game_hidden = True
                        self.root.withdraw()
                else:
                    if self._game_hidden:
                        self._game_hidden = False
                        try:
                            self.root.deiconify()
                            if self.cfg.get("pin_background", True) \
                                    and not self.cfg.get("always_on_top",
                                                         False):
                                pin_window_to_bottom(self.root)
                        except Exception:
                            pass
            else:
                self._game_hidden = False
        except Exception:
            pass
        try:
            self.root.after(5000, self._game_mode_loop)
        except Exception:
            pass

    # ---------- MQTT ----------
    def _publish_mqtt(self):
        if not self.cfg.get("mqtt_enabled", False):
            return
        try:
            import threading as _th
            import mqtt_pub as _mq
            devs = []
            for d in self.visible_devices():
                nd = dict(d)
                nd["name"] = self.disp_name(d)
                devs.append(nd)
            _th.Thread(target=_mq.publish,
                       args=(devs, dict(self.cfg), None),
                       daemon=True).start()
        except Exception:
            pass

    # ---------- Web-Dashboard ----------
    def web_data(self):
        try:
            devs = []
            for d in self.visible_devices():
                info = ""
                try:
                    bits = []
                    if d.get("connection"):
                        bits.append(str(d["connection"]).title())
                    if d.get("firmware"):
                        bits.append(f"FW {d['firmware']}")
                    if d.get("charging"):
                        bits.append("lädt")
                    info = " · ".join(bits)
                except Exception:
                    pass
                devs.append({"name": self.disp_name(d),
                             "percentage": d.get("percentage"),
                             "charging": bool(d.get("charging", False)),
                             "info": info})
            return {"devices": devs, "updated": self.last_update,
                    "source": self.source_label()}
        except Exception:
            return {"devices": []}

    def restart_web(self):
        try:
            import webdash as _wd
            if self.cfg.get("web_enabled", True):
                try:
                    port = int(self.cfg.get("web_port", 8321))
                except Exception:
                    port = 8321
                return _wd.start(port, self.web_data)
            _wd.stop()
            return True
        except Exception:
            return False

    def open_dashboard(self):
        try:
            import webdash as _wd
            try:
                port = int(self.cfg.get("web_port", 8321))
            except Exception:
                port = 8321
            if not _wd.is_running():
                self.restart_web()
            _wd.open_browser(port)
        except Exception:
            pass

    def _fallback_devices(self):
        """Redundante Quellen wenn Websocket down: (devices, source, ts).

        Reihenfolge: Extern -> logitray (HID live) -> Datei-DB -> HID.
        Gibt None zurück wenn nichts liefert (dann Cache aus _refresh_worker).
        """
        import fallback as _fb
        import time as _t
        known = {}
        for d in (self.devices or []):
            if d.get("id"):
                known[d["id"]] = d
        try:
            cache_devs, _ts = load_cache()
            for d in cache_devs:
                if d.get("id"):
                    known.setdefault(d["id"], d)
        except Exception:
            pass
        # 1) externe Tools (live, z.B. LGSTrayBattery)
        if self.cfg.get("ext_fallback", True):
            try:
                ext = _fb.read_ext_batteries()
            except Exception:
                ext = []
            if ext:
                devs = []
                for e in ext:
                    match = None
                    for _kid, kd in known.items():
                        try:
                            if (kd.get("name", "").lower()
                                    == e["name"].lower()):
                                match = kd
                                break
                        except Exception:
                            continue
                    base = dict(match) if match else {
                        "id": e["id"], "name": e["name"],
                        "hasBattery": True, "state": "ACTIVE"}
                    base.update({"percentage": e["percentage"],
                                 "charging": e["charging"],
                                 "mileage": (match.get("mileage")
                                             if match else None)})
                    base.pop("stale", None)
                    devs.append(base)
                return devs, "ext", None
        # 2) logitray (HID direkt, live, ohne G HUB) – gedrosselt 1x/60s
        if self.cfg.get("logitray_enabled", True):
            if _t.monotonic() - getattr(self, "_last_logitray_try",
                                        0) > 60:
                self._last_logitray_try = _t.monotonic()
                try:
                    lt = _fb.read_logitray(timeout=30)
                except Exception:
                    lt = []
                self._last_logitray = lt or []
                self._last_logitray_ts = _t.time()
                if lt:
                    import re as _re
                    devs = []
                    for e in lt:
                        match = None
                        for _kid, kd in known.items():
                            try:
                                if (kd.get("name", "").lower()
                                        == e["name"].lower()):
                                    match = kd
                                    break
                            except Exception:
                                continue
                        if match:
                            base = dict(match)
                        else:
                            slug = _re.sub(r"[^a-z0-9]+", "-",
                                           e["name"].lower()).strip("-")
                            base = {"id": f"logitray-{slug}",
                                    "name": e["name"],
                                    "hasBattery": True, "state": "ACTIVE"}
                        base.update(
                            {"percentage": e["percentage"],
                             "charging": e["charging"],
                             "mileage": (match.get("mileage")
                                         if match else None)})
                        base.pop("stale", None)
                        devs.append(base)
                    return devs, "logitray", None
        # 3) G HUB Datei-DB
        if self.cfg.get("ghub_db", True):
            try:
                entries = _fb.read_db_batteries()
            except Exception:
                entries = []
            if entries:
                by_id = {e.get("deviceId"): e for e in entries
                         if e.get("deviceId")}
                devs = []
                for kid, kd in known.items():
                    if kid in by_id:
                        e = by_id[kid]
                        nd = dict(kd)
                        nd.update({"percentage": e["percentage"],
                                   "charging": kd.get("charging", False),
                                   "mileage": kd.get("mileage")})
                        nd.pop("stale", None)
                        devs.append(nd)
                for e in entries:
                    did = e.get("deviceId")
                    if did and did not in known:
                        devs.append({"id": did, "name": e.get("slug", did),
                                     "hasBattery": True, "state": "UNKNOWN",
                                     "percentage": e["percentage"],
                                     "charging": False, "mileage": None})
                if devs:
                    ts = None
                    for e in entries:
                        ep = _fb.db_time_to_epoch(e.get("time", ""))
                        if ep and (ts is None or ep > ts):
                            ts = ep
                    return devs, "ghub-db", ts
        # 3) HID direkt (gedrosselt, max 1x/5min)
        if self.cfg.get("hid_direct", True):
            if _t.monotonic() - getattr(self, "_last_hid_try", 0) > 300:
                self._last_hid_try = _t.monotonic()
                try:
                    hid = _fb.read_hid_batteries(timeout_total=8.0)
                except Exception:
                    hid = []
                self._last_hid = hid or []
                self._last_hid_ts = _t.time()
                if hid:
                    devs = []
                    for h in hid:
                        devs.append({
                            "id": f"hid-{h.get('index')}",
                            "name": f"HID-Gerät {h.get('index')}",
                            "hasBattery": True, "state": "ACTIVE",
                            "percentage": h["percentage"],
                            "charging": h.get("charging", False),
                            "mileage": None})
                    return devs, "hid", None
        return None

    def toggle_click_through(self):
        on = not self.cfg.get("click_through", False)
        self.cfg["click_through"] = on
        save_config(self.cfg)
        set_click_through(self.root, on)
        try:
            self._notify("Click-Through",
                         "Klicks gehen jetzt hindurch (umschalten via Tray/Hotkey)"
                         if on else "Widget wieder klickbar")
        except Exception:
            pass

    def _notify(self, title, msg):
        try:
            if self.tray is not None:
                self.tray.notify(msg, title)
                return
        except Exception:
            pass
        # Fallback: Titel blinken
        try:
            self.title_lbl.config(text=f"  ⚠ {msg}")
            self.root.after(5000, lambda: self.title_lbl.config(text="  🔋 Logitech Akku"))
        except Exception:
            pass

    # ---------- Tray ----------
    def _start_tray(self):
        try:
            import pystray
            from pystray import MenuItem as Item, Menu
        except Exception as ex:
            print("pystray fehlt, nur Widget:", ex)
            return

        def get_icon():
            # Minimum aller Prozente für Icon-Farbe
            pcts = [d.get("percentage") for d in self.devices
                    if d.get("percentage") is not None]
            pct = min(pcts) if pcts else None
            return make_tray_icon_image(pct)

        def get_tooltip():
            if not self.devices:
                return "Logi Akku – keine Daten"
            lines = []
            for d in self.devices:
                p = d.get("percentage")
                c = " ⚡" if d.get("charging") else ""
                lines.append(f"{d.get('name')}: {p}%{c}" if p is not None else f"{d.get('name')}: offline")
            return "\n".join(lines)

        import pystray as ps
        menu = ps.Menu(
            ps.MenuItem("Aktualisieren", lambda ic, it: self.refresh_async()),
            ps.MenuItem("🎨 Design anpassen …", lambda ic, it: self.open_settings()),
            ps.MenuItem("📈 Verlauf anzeigen …", lambda ic, it: self.open_history()),
            ps.MenuItem("🔧 Diagnose & Reparatur …",
                        lambda ic, it: self.open_diagnose()),
            ps.MenuItem("🌐 Dashboard im Browser öffnen",
                        lambda ic, it: self.open_dashboard()),
            ps.MenuItem("Klicks durchlassen an/aus",
                        lambda ic, it: self.toggle_click_through()),
            ps.MenuItem("Widget nach vorne holen", lambda ic, it: self.bring_to_front()),
            ps.MenuItem("Anzeigen / Verstecken", lambda ic, it: self.toggle_window()),
            ps.MenuItem("Autostart an/aus", lambda ic, it: self._toggle_autostart()),
            ps.MenuItem("Beenden", lambda ic, it: self.quit_app()),
        )
        try:
            self.tray = ps.Icon("LogiAkku", get_icon(), "Logi Akku", menu)
        except Exception as ex:
            print("Tray-Init Fehler:", ex)
            return

        def run():
            try:
                self.tray.run()
            except Exception as ex:
                print("Tray-Fehler:", ex)

        self.tray_thread = threading.Thread(target=run, daemon=True)
        self.tray_thread.start()

    def _update_tray(self):
        if self.tray is None:
            return
        try:
            vis = self.visible_devices()
            pcts = [d.get("percentage") for d in vis
                    if d.get("percentage") is not None]
            pct = min(pcts) if pcts else None
            self.tray.icon = make_tray_icon_image(pct)
            lines = []
            for d in vis:
                p = d.get("percentage")
                c = " ⚡" if d.get("charging") else ""
                nm = self.disp_name(d)
                lines.append(f"{nm}: {p}%{c}" if p is not None else f"{nm}: offline")
            if self._game_hidden:
                lines.append("🎮 Gaming-Modus")
            self.tray.title = " • ".join(lines) if lines else "Logi Akku"
        except Exception:
            pass

    def toggle_window(self):
        try:
            self._game_hidden = False
            if self.root.winfo_viewable():
                self.root.withdraw()
            else:
                self.root.deiconify()
                self.bring_to_front()
        except Exception:
            pass

    def hide_to_tray(self):
        self.root.withdraw()

    def quit_app(self):
        try:
            if self._live_stop is not None:
                self._live_stop.set()
        except Exception:
            pass
        try:
            import keyboard as _kb
            _kb.unhook_all()
        except Exception:
            pass
        try:
            import mqtt_pub as _mq
            _mq.disconnect()
        except Exception:
            pass
        try:
            import webdash as _wd
            _wd.stop()
        except Exception:
            pass
        try:
            self.cfg["x"] = self.root.winfo_x()
            self.cfg["y"] = self.root.winfo_y()
            save_config(self.cfg)
        except Exception:
            pass
        try:
            if self.tray is not None:
                self.tray.stop()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass
        os._exit(0)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    if not ensure_single_instance():
        sys.exit(0)
    App().run()
