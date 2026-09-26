"""Diagnose-Dialog für LogiBatteryWidget – zeigt Gesundheit aller
Redundanz-Ebenen und bietet Reparatur-Aktionen (G HUB starten/neu starten).
"""
import tkinter as tk


def open_diagnose(app):
    if getattr(app, "_diag_win", None) is not None:
        try:
            if app._diag_win.winfo_exists():
                app._diag_win.lift()
                app._diag_win.focus_force()
                return
        except Exception:
            pass

    from app import (diagnose, launch_ghub, restart_ghub,
                     ghub_process_running, save_config)
    import ghub as _ghub

    win = tk.Toplevel(app.root)
    app._diag_win = win
    win.title("Diagnose & Reparatur")
    win.geometry("460x480")
    win.minsize(420, 420)
    try:
        win.attributes("-topmost", True)
    except Exception:
        pass

    th = app.cfg.get("theme", {})
    bg = th.get("bg", "#1a1d21")
    card = th.get("card", "#24282e")
    fg = th.get("fg", "#f2f2f2")
    dim = th.get("dim", "#9aa0a6")
    ff = th.get("font_family", "Segoe UI")
    win.configure(bg=bg)

    tk.Label(win, text="🔧 Systemstatus", bg=bg, fg=fg,
             font=(ff, 12, "bold")).pack(anchor="w", padx=12, pady=(10, 2))
    src_lbl = tk.Label(win, text="", bg=bg, fg=dim, font=(ff, 9))
    src_lbl.pack(anchor="w", padx=12)

    rows_frame = tk.Frame(win, bg=bg)
    rows_frame.pack(fill="both", expand=True, padx=12, pady=8)
    row_widgets = []

    def refresh():
        for w in row_widgets:
            try:
                w.destroy()
            except Exception:
                pass
        row_widgets.clear()
        try:
            src_lbl.config(text=f"Aktive Quelle: {app.source_label()}")
        except Exception:
            pass
        for name, ok, detail in diagnose(app):
            r = tk.Frame(rows_frame, bg=card)
            r.pack(fill="x", pady=3)
            icon = "✓" if ok else "✗"
            col = "#2ecc71" if ok else "#e74c3c"
            tk.Label(r, text=f" {icon} ", bg=card, fg=col,
                     font=(ff, 11, "bold")).pack(side="left")
            tk.Label(r, text=name, bg=card, fg=fg,
                     font=(ff, 10, "bold")).pack(side="left")
            tk.Label(r, text=detail or "", bg=card, fg=dim,
                     font=(ff, 9)).pack(side="left", padx=(8, 0))
            row_widgets.append(r)
        win.update_idletasks()

    btn = tk.Frame(win, bg=bg, pady=8)
    btn.pack(fill="x", padx=12)

    def on_close():
        app._diag_win = None
        win.destroy()

    win.protocol("WM_DELETE_WINDOW", on_close)

    def mk_btn_left(text, cmd):
        return tk.Button(btn, text=text, bg=card, fg=fg, bd=0,
                         activebackground=card, font=(ff, 9), padx=8,
                         pady=4, command=cmd).pack(side="left", padx=2)

    def do_start():
        if launch_ghub():
            app._ghub_note = "G HUB wird gestartet …"
        refresh()

    def do_restart():
        if restart_ghub():
            app._ghub_note = "G HUB wird neu gestartet …"
            app._ghub_repaired = True
        try:
            app.refresh_async()
        except Exception:
            pass
        refresh()

    mk_btn_left("G HUB starten", do_start)
    mk_btn_left("G HUB neu starten", do_restart)
    mk_btn_left("Erneut prüfen",
                lambda: (app.refresh_async(), refresh()))
    tk.Button(btn, text="Schließen", bg=card, fg=fg, bd=0,
              activebackground=card, font=(ff, 9), padx=8, pady=4,
              command=on_close).pack(side="right", padx=2)

    refresh()
