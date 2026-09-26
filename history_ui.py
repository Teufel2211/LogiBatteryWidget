"""Verlaufs-Fenster für LogiBatteryWidget – Akku-Kurve pro Gerät (Tk Canvas).

Daten aus history.csv (geschrieben von app.append_history).
"""
import time
import tkinter as tk
from tkinter import ttk


def open_history(app):
    if getattr(app, "_history_win", None) is not None:
        try:
            if app._history_win.winfo_exists():
                app._history_win.lift()
                app._history_win.focus_force()
                return
        except Exception:
            pass

    from app import read_history

    win = tk.Toplevel(app.root)
    app._history_win = win
    win.title("Akku-Verlauf")
    win.geometry("560x440")
    win.minsize(480, 380)
    try:
        win.attributes("-topmost", True)
    except Exception:
        pass

    th = app.cfg.get("theme", {})
    bg = th.get("bg", "#1a1d21")
    card = th.get("card", "#24282e")
    fg = th.get("fg", "#f2f2f2")
    dim = th.get("dim", "#9aa0a6")
    accent = th.get("accent", "#00b4ff")
    ff = th.get("font_family", "Segoe UI")
    win.configure(bg=bg)

    top = tk.Frame(win, bg=bg)
    top.pack(fill="x", padx=12, pady=(10, 4))
    tk.Label(top, text="Gerät:", bg=bg, fg=fg,
             font=(ff, 10, "bold")).pack(side="left")
    dev_var = tk.StringVar()
    combo = ttk.Combobox(top, textvariable=dev_var, state="readonly",
                         width=34)
    combo.pack(side="left", padx=8)
    info = tk.Label(win, text="", bg=bg, fg=dim, font=(ff, 9),
                    anchor="w")
    info.pack(fill="x", padx=12)

    canvas = tk.Canvas(win, bg=card, highlightthickness=0)
    canvas.pack(fill="both", expand=True, padx=12, pady=8)
    bottom = tk.Frame(win, bg=bg)
    bottom.pack(fill="x", padx=12, pady=(0, 10))
    tk.Button(bottom, text="Aktualisieren", bg=card, fg=fg, bd=0,
              activebackground=card, font=(ff, 9),
              command=lambda: draw()).pack(side="left")
    tk.Button(bottom, text="Schließen", bg=card, fg=fg, bd=0,
              activebackground=card, font=(ff, 9),
              command=lambda: on_close()).pack(side="right")

    rows = []

    def reload():
        nonlocal rows
        rows = read_history()
        names = []
        seen = set()
        for r in rows:
            if r["name"] not in seen:
                seen.add(r["name"])
                names.append(r["name"])
        # aktuelle Geräte zuerst
        for d in app.devices:
            if d.get("name") not in names:
                names.append(d.get("name"))
        combo["values"] = names
        if names and (not dev_var.get() or dev_var.get() not in names):
            dev_var.set(names[0])

    def draw(_e=None):
        canvas.delete("all")
        W = canvas.winfo_width() or 500
        H = canvas.winfo_height() or 300
        name = dev_var.get()
        pts = [(r["ts"], r["pct"]) for r in rows
               if r["name"] == name and r["pct"] is not None]
        if len(pts) < 2:
            canvas.create_text(W // 2, H // 2,
                               text="Noch keine Verlaufsdaten\n(für dieses Gerät).\n\nWerte werden ab jetzt gesammelt.",
                               fill=dim, font=(ff, 10), justify="center")
            info.config(text="")
            return
        pts.sort()
        t0, t1 = pts[0][0], pts[-1][0]
        span = max(1, t1 - t0)
        pad_l, pad_r, pad_t, pad_b = 44, 12, 12, 26

        def X(ts):
            return pad_l + (ts - t0) / span * (W - pad_l - pad_r)

        def Y(p):
            return pad_t + (100 - p) / 100 * (H - pad_t - pad_b)

        # Raster + Labels
        for p in (0, 25, 50, 75, 100):
            y = Y(p)
            canvas.create_line(pad_l, y, W - pad_r, y, fill=dim)
            canvas.create_text(pad_l - 6, y, text=f"{p}%", fill=dim,
                               font=(ff, 8), anchor="e")
        for frac, fmt in ((0.0, None), (0.5, None), (1.0, None)):
            ts = t0 + span * frac
            x = X(ts)
            lbl = time.strftime("%H:%M", time.localtime(ts))
            if span > 86400:
                lbl = time.strftime("%d.%m %H:%M", time.localtime(ts))
            canvas.create_text(x, H - 8, text=lbl, fill=dim, font=(ff, 8))

        # Kurve (Ladepunkte grün markiert)
        coords = []
        for ts, p in pts:
            coords += [X(ts), Y(p)]
        canvas.create_line(*coords, fill=accent, width=2)
        for (ts, p), r in zip(pts, [x for x in rows if x["name"] == name
                                    and x["pct"] is not None]):
            if r.get("charging"):
                canvas.create_oval(X(ts) - 3, Y(p) - 3, X(ts) + 3, Y(p) + 3,
                                   fill="#2ecc71", outline="")
        # letzter Wert
        lx, ly = X(pts[-1][0]), Y(pts[-1][1])
        canvas.create_oval(lx - 4, ly - 4, lx + 4, ly + 4,
                           fill=accent, outline="")
        vals = [p for _, p in pts]
        try:
            from app import forecast_for, fmt_dauer
            _did = next((r["id"] for r in rows if r["name"] == name), None)
            _fc = forecast_for(_did, hours=24) if _did else {}
            extra = ""
            if _fc.get("empty_in_h") is not None:
                extra += f"  •  leer in ~{fmt_dauer(_fc['empty_in_h'])}"
            if _fc.get("full_in_h") is not None:
                extra += f"  •  voll in ~{fmt_dauer(_fc['full_in_h'])}"
            if _fc.get("trend") and _fc["trend"] != "–":
                extra += f"  •  {_fc['trend']}"
        except Exception:
            extra = ""
        info.config(
            text=f"{name}:  {vals[-1]}%  •  Min {min(vals)}%  •  "
                 f"Max {max(vals)}%  •  Ø {sum(vals)//len(vals)}%  •  "
                 f"{len(vals)} Punkte{extra}")

    combo.bind("<<ComboboxSelected>>", draw)
    canvas.bind("<Configure>", lambda e: canvas.after_idle(draw))

    def on_close():
        app._history_win = None
        win.destroy()

    win.protocol("WM_DELETE_WINDOW", on_close)
    reload()
    win.update_idletasks()
    draw()
