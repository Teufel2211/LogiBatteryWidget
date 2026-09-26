"""Design-Editor für LogiBatteryWidget – Tabs: Farben / Schrift & Größe / Verhalten.

Wird aus app.py via App.open_settings() geöffnet. Schreibt direkt in
app.cfg["theme"] und ruft app.apply_theme() für Live-Vorschau auf.
Das Einstellungsfenster selbst trägt die gewählte Vorlage.
"""
import tkinter as tk
from tkinter import ttk, colorchooser


COLOR_ROWS = [
    ("bg", "Hintergrund"),
    ("card", "Karten"),
    ("header_bg", "Titelzeile"),
    ("fg", "Text"),
    ("dim", "Sekundär-Text"),
    ("accent", "Akzent"),
    ("bar_high", "Balken voll (>50%)"),
    ("bar_mid", "Balken mittel (20-50%)"),
    ("bar_low", "Balken niedrig (<20%)"),
    ("bar_charging", "Balken lädt"),
    ("bar_track", "Balken-Hintergrund"),
]

FONTS = ["Segoe UI", "Arial", "Calibri", "Verdana", "Tahoma", "Consolas",
         "Courier New", "Georgia"]


def open_settings(app):
    if getattr(app, "_settings_win", None) is not None:
        try:
            if app._settings_win.winfo_exists():
                app._settings_win.lift()
                app._settings_win.focus_force()
                return
        except Exception:
            pass

    from app import THEMES, save_config, is_autostart_enabled, set_autostart

    win = tk.Toplevel(app.root)
    app._settings_win = win
    win.title("Design anpassen")
    win.geometry("480x720")
    win.minsize(460, 620)
    try:
        win.attributes("-topmost", True)
    except Exception:
        pass

    th = app.cfg.get("theme", {})

    # Widget-Register für Theming des Fensters selbst
    frames: list = []
    labels: list = []
    buttons: list = []
    checks: list = []
    entries: list = []

    def reg(w, kind):
        try:
            {"frame": frames, "label": labels,
             "button": buttons, "check": checks}[kind].append(w)
        except Exception:
            pass
        return w

    # ---------- Fenster-Theming ----------
    style = ttk.Style(win)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    def apply_win_theme():
        t = app.cfg.get("theme", {})
        bg = t.get("bg", "#1a1d21")
        card = t.get("card", "#24282e")
        fg = t.get("fg", "#f2f2f2")
        dim = t.get("dim", "#9aa0a6")
        accent = t.get("accent", "#00b4ff")
        ff = t.get("font_family", "Segoe UI")
        try:
            win.configure(bg=bg)
        except Exception:
            pass
        for f in frames:
            try:
                f.configure(bg=bg)
            except Exception:
                pass
        for lb in labels:
            try:
                lb.configure(bg=bg, fg=fg, font=(ff, 9))
            except Exception:
                pass
        try:
            title_lbl.configure(bg=bg, fg=fg, font=(ff, 10, "bold"))
        except Exception:
            pass
        for b in buttons:
            try:
                b.configure(bg=card, fg=fg, activebackground=card,
                            activeforeground=fg, font=(ff, 9))
            except Exception:
                pass
        for c in checks:
            try:
                c.configure(bg=bg, fg=fg, activebackground=bg,
                            activeforeground=fg, selectcolor=card, font=(ff, 9))
            except Exception:
                pass
        for sc in scales:
            try:
                sc.configure(bg=bg, fg=fg, troughcolor=card,
                             highlightbackground=bg, activebackground=accent)
            except Exception:
                pass
        for sp in spinboxes:
            try:
                sp.configure(bg=card, fg=fg, buttonbackground=card,
                             insertbackground=fg, font=(ff, 9))
            except Exception:
                pass
        for en in entries:
            try:
                en.configure(bg=card, fg=fg, insertbackground=fg,
                             font=(ff, 9))
            except Exception:
                pass
        try:
            style.configure("TNotebook", background=bg, borderwidth=0)
            style.configure("TNotebook.Tab", background=card, foreground=fg,
                            padding=(10, 4), font=(ff, 9))
            style.map("TNotebook.Tab", background=[("selected", accent)],
                      foreground=[("selected", bg)])
            style.configure("TCombobox", fieldbackground=card,
                            background=card, foreground=fg,
                            arrowcolor=fg, font=(ff, 9))
            style.map("TCombobox",
                      fieldbackground=[("readonly focus", card),
                                       ("readonly", card)],
                      foreground=[("readonly focus", fg),
                                  ("readonly", fg)],
                      background=[("readonly", card)],
                      arrowcolor=[("readonly", fg)])
            # Dropdown-Liste (Listbox-Popup) folgt sonst nicht dem Theme
            # und wird z.B. weiß auf weiß dargestellt:
            win.option_add("*TCombobox*Listbox.background", card)
            win.option_add("*TCombobox*Listbox.foreground", fg)
            win.option_add("*TCombobox*Listbox.selectBackground", accent)
            win.option_add("*TCombobox*Listbox.selectForeground", bg)
            win.option_add("*TCombobox*Listbox.font", (ff, 9))
        except Exception:
            pass
        try:
            btn_bar.configure(bg=bg)
        except Exception:
            pass

    # ---------- Preset-Zeile ----------
    top = reg(tk.Frame(win, pady=8), "frame")
    top.pack(fill="x", padx=12)
    title_lbl = tk.Label(top, text="Vorlage:")
    title_lbl.pack(side="left")
    labels.append(title_lbl)
    preset_var = tk.StringVar(value="Benutzerdefiniert")
    for name, vals in THEMES.items():
        if all(th.get(k) == v for k, v in vals.items() if k in th):
            preset_var.set(name)
            break
    combo = ttk.Combobox(top, textvariable=preset_var,
                         values=list(THEMES.keys()), state="readonly", width=22)
    combo.pack(side="left", padx=8)

    def on_preset(_e=None):
        name = preset_var.get()
        if name in THEMES:
            app.cfg["theme"].update(THEMES[name])
            save_and_preview()
            rebuild_color_buttons()
            sync_all_controls()
            apply_win_theme()

    combo.bind("<<ComboboxSelected>>", on_preset)

    nb = ttk.Notebook(win)
    nb.pack(fill="both", expand=True, padx=8, pady=4)

    scales: list = []
    spinboxes: list = []

    # ---------- Tab: Farben ----------
    tab_c = tk.Frame(nb)
    nb.add(tab_c, text="Farben")
    frames.append(tab_c)
    inner_c = tk.Frame(tab_c)
    inner_c.pack(fill="both", expand=True, padx=6, pady=6)
    frames.append(inner_c)
    inner_c.columnconfigure(0, weight=1)
    inner_c.columnconfigure(1, weight=0)
    color_btns = {}

    def pick(key):
        cur = app.cfg["theme"].get(key, "#ffffff")
        c = colorchooser.askcolor(color=cur, title=key)
        if c and c[1]:
            app.cfg["theme"][key] = c[1]
            try:
                color_btns[key].configure(bg=c[1])
            except Exception:
                pass
            save_and_preview()
            apply_win_theme()  # Fenster folgt z.B. neuem Hintergrund live

    for i, (key, label) in enumerate(COLOR_ROWS):
        lb = tk.Label(inner_c, text=label, anchor="w")
        lb.grid(row=i, column=0, sticky="ew", padx=(12, 4), pady=4)
        labels.append(lb)
        b = tk.Button(inner_c, text="        ",
                      bg=app.cfg["theme"].get(key, "#ffffff"),
                      relief="solid", bd=1, width=10,
                      command=lambda k=key: pick(k))
        b.grid(row=i, column=1, padx=(4, 12), pady=4, sticky="e")
        color_btns[key] = b

    def rebuild_color_buttons():
        for k, b in color_btns.items():
            try:
                b.configure(bg=app.cfg["theme"].get(k))
            except Exception:
                pass

    # ---------- Tab: Schrift & Größe ----------
    tab_f = tk.Frame(nb)
    nb.add(tab_f, text="Schrift & Größe")
    frames.append(tab_f)
    inner_f = tk.Frame(tab_f)
    inner_f.pack(fill="both", expand=True, padx=6, pady=6)
    frames.append(inner_f)
    inner_f.columnconfigure(0, weight=1)
    inner_f.columnconfigure(1, weight=0)

    r = 0
    lb = tk.Label(inner_f, text="Schriftart:", anchor="w")
    lb.grid(row=r, column=0, sticky="ew", padx=(12, 4), pady=5)
    labels.append(lb)
    font_var = tk.StringVar(value=th.get("font_family", "Segoe UI"))
    fc = ttk.Combobox(inner_f, textvariable=font_var, values=FONTS, width=20)
    fc.grid(row=r, column=1, padx=(4, 12), pady=5, sticky="e")

    def on_font(_e=None):
        app.cfg["theme"]["font_family"] = font_var.get()
        save_and_preview()
        apply_win_theme()

    fc.bind("<<ComboboxSelected>>", on_font)
    r += 1

    spins = {}

    def add_spin(label, key, lo, hi):
        nonlocal r
        lb2 = tk.Label(inner_f, text=label, anchor="w")
        lb2.grid(row=r, column=0, sticky="ew", padx=(12, 4), pady=5)
        labels.append(lb2)
        v = tk.IntVar(value=int(th.get(key, 10)))
        s = tk.Spinbox(inner_f, from_=lo, to=hi, textvariable=v, width=8,
                       command=lambda: (app.cfg["theme"].__setitem__(key, int(v.get())),
                                        save_and_preview()))
        s.grid(row=r, column=1, padx=(4, 12), pady=5, sticky="e")
        spinboxes.append(s)
        spins[key] = v
        r += 1

    add_spin("Titelgröße:", "font_size_title", 8, 20)
    add_spin("Gerätename:", "font_size_name", 8, 20)
    add_spin("Prozentgröße:", "font_size_pct", 8, 24)
    add_spin("Balkenhöhe:", "bar_height", 6, 30)
    add_spin("Widget-Breite:", "widget_width", 240, 520)

    op_var = tk.DoubleVar(value=float(app.cfg.get("opacity", 0.93)))

    def on_opacity(_v=None):
        app.cfg["opacity"] = round(float(op_var.get()), 2)
        save_and_preview()

    lb3 = tk.Label(inner_f, text="Transparenz:", anchor="w")
    lb3.grid(row=r, column=0, sticky="ew", padx=(12, 4), pady=5)
    labels.append(lb3)
    sc = tk.Scale(inner_f, from_=0.3, to=1.0, resolution=0.01,
                  orient="horizontal", variable=op_var,
                  command=on_opacity, length=150,
                  showvalue=True, sliderrelief="flat", bd=0,
                  highlightthickness=0)
    sc.grid(row=r, column=1, padx=(4, 12), pady=5, sticky="e")
    scales.append(sc)
    r += 1

    show_vars = {}
    for label, key in [("Restlaufzeit zeigen", "show_mileage"),
                       ("Kopfzeile zeigen", "show_header"),
                       ("Fußzeile zeigen", "show_footer"),
                       ("Statuszeile zeigen", "show_status")]:
        v = tk.BooleanVar(value=bool(th.get(key, True)))
        cb = tk.Checkbutton(inner_f, text=label, variable=v, anchor="w",
                            command=lambda k=key, vv=v: (
                                app.cfg["theme"].__setitem__(k, bool(vv.get())),
                                save_and_preview()))
        cb.grid(row=r, column=0, columnspan=2, sticky="ew",
                padx=12, pady=3)
        checks.append(cb)
        show_vars[key] = v
        r += 1

    def sync_controls():
        font_var.set(app.cfg["theme"].get("font_family", "Segoe UI"))
        for k, v in spins.items():
            try:
                v.set(int(app.cfg["theme"].get(k, v.get())))
            except Exception:
                pass
        try:
            op_var.set(float(app.cfg.get("opacity", 0.93)))
        except Exception:
            pass
        for k, v in show_vars.items():
            v.set(bool(app.cfg["theme"].get(k, True)))
        beh_sync()

    # ---------- Tab: Verhalten ----------
    tab_b = tk.Frame(nb)
    nb.add(tab_b, text="Verhalten")
    frames.append(tab_b)
    inner_b = tk.Frame(tab_b)
    inner_b.pack(fill="both", expand=True, padx=6, pady=6)
    frames.append(inner_b)
    inner_b.columnconfigure(0, weight=1)
    inner_b.columnconfigure(1, weight=0)
    br = 0
    lb4 = tk.Label(inner_b, text="Refresh (Sek.):", anchor="w")
    lb4.grid(row=br, column=0, sticky="ew", padx=(12, 4), pady=5)
    labels.append(lb4)
    ref_var = tk.IntVar(value=int(app.cfg.get("refresh_seconds", 30)))
    sp_ref = tk.Spinbox(inner_b, from_=10, to=300, textvariable=ref_var,
                        width=8,
                        command=lambda: (app.cfg.__setitem__(
                            "refresh_seconds", int(ref_var.get())),
                            save_and_preview()))
    sp_ref.grid(row=br, column=1, padx=(4, 12), pady=5, sticky="e")
    spinboxes.append(sp_ref)
    br += 1
    lb5 = tk.Label(inner_b, text="Warnung unter (%):", anchor="w")
    lb5.grid(row=br, column=0, sticky="ew", padx=(12, 4), pady=5)
    labels.append(lb5)
    low_var = tk.IntVar(value=int(app.cfg.get("low_threshold", 20)))
    sp_low = tk.Spinbox(inner_b, from_=5, to=50, textvariable=low_var,
                        width=8,
                        command=lambda: (app.cfg.__setitem__(
                            "low_threshold", int(low_var.get())),
                            save_and_preview()))
    sp_low.grid(row=br, column=1, padx=(4, 12), pady=5, sticky="e")
    spinboxes.append(sp_low)
    br += 1

    top_var = tk.BooleanVar(value=bool(app.cfg.get("always_on_top", False)))
    back_var = tk.BooleanVar(value=bool(app.cfg.get("pin_background", True)))

    def on_top():
        app.cfg["always_on_top"] = bool(top_var.get())
        if top_var.get():
            app.cfg["pin_background"] = False
            back_var.set(False)
        save_and_preview(apply_win_flags=True)

    def on_back():
        app.cfg["pin_background"] = bool(back_var.get())
        if back_var.get():
            app.cfg["always_on_top"] = False
            top_var.set(False)
        save_and_preview(apply_win_flags=True)

    cb_top = tk.Checkbutton(inner_b, text="Immer im Vordergrund",
                            variable=top_var, command=on_top, anchor="w")
    cb_top.grid(row=br, column=0, columnspan=2, sticky="ew", padx=12, pady=3)
    checks.append(cb_top)
    br += 1
    cb_back = tk.Checkbutton(inner_b, text="Im Hintergrund (unter Apps)",
                             variable=back_var, command=on_back, anchor="w")
    cb_back.grid(row=br, column=0, columnspan=2, sticky="ew", padx=12, pady=3)
    checks.append(cb_back)
    br += 1

    auto_var = tk.BooleanVar(value=is_autostart_enabled())
    cb_auto = tk.Checkbutton(inner_b, text="Autostart mit Windows",
                             variable=auto_var, anchor="w",
                             command=lambda: set_autostart(bool(auto_var.get())))
    cb_auto.grid(row=br, column=0, columnspan=2, sticky="ew", padx=12, pady=3)
    checks.append(cb_auto)
    br += 1

    def beh_sync():
        try:
            ref_var.set(int(app.cfg.get("refresh_seconds", 30)))
        except Exception:
            pass
        try:
            low_var.set(int(app.cfg.get("low_threshold", 20)))
        except Exception:
            pass
        top_var.set(bool(app.cfg.get("always_on_top", False)))
        back_var.set(bool(app.cfg.get("pin_background", True)))
        try:
            auto_var.set(is_autostart_enabled())
        except Exception:
            pass

    # ---------- Tab: Geräte ----------
    tab_d = tk.Frame(nb)
    nb.add(tab_d, text="Geräte")
    frames.append(tab_d)
    inner_d = tk.Frame(tab_d)
    inner_d.pack(fill="both", expand=True, padx=6, pady=6)
    frames.append(inner_d)

    dev_rows = []  # (dev_id, alias_var, low_var, hid_var)

    def rebuild_device_tab():
        for w in inner_d.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass
        dev_rows.clear()
        known = {}
        for d in (app.devices or []):
            if d.get("id"):
                known[d["id"]] = d.get("name", d["id"])
        if not known:
            lb = tk.Label(inner_d,
                          text="Keine Geräte bekannt.\nVerbinde G HUB und "
                               "aktualisiere, dann erscheinen sie hier.")
            lb.pack(pady=20)
            labels.append(lb)
            apply_win_theme()
            return
        r = 0
        hdr = tk.Label(inner_d, text="Gerät / Anzeigename / Warnung ab % / Ausblenden",
                       anchor="w")
        hdr.grid(row=r, column=0, columnspan=3, sticky="ew", padx=12, pady=4)
        labels.append(hdr)
        r += 1
        for did, dname in known.items():
            cfg_d = (app.cfg.get("devices_cfg", {}).get(did)
                     or app.cfg.get("devices_cfg", {}).get(dname) or {})
            lb = tk.Label(inner_d, text=dname, anchor="w")
            lb.grid(row=r, column=0, sticky="ew", padx=(12, 4), pady=4)
            labels.append(lb)
            av = tk.StringVar(value=str(cfg_d.get("alias", "")))
            ae = tk.Entry(inner_d, textvariable=av, width=16)
            ae.grid(row=r, column=1, padx=4, pady=4, sticky="ew")
            entries.append(ae)
            lv = tk.StringVar(value="" if cfg_d.get("low") is None
                              else str(cfg_d.get("low")))
            se = tk.Entry(inner_d, textvariable=lv, width=5)
            se.grid(row=r, column=2, padx=(4, 2), pady=4)
            entries.append(se)
            hv = tk.BooleanVar(value=bool(cfg_d.get("hidden", False)))
            cb = tk.Checkbutton(inner_d, text="aus", variable=hv,
                                command=lambda _d=did, _a=av, _l=lv, _h=hv: (
                                    save_device(_d, _a, _l, _h)))
            cb.grid(row=r, column=3, padx=(2, 12), pady=4)
            checks.append(cb)
            ae.bind("<FocusOut>", lambda _e, _d=did, _a=av, _l=lv, _h=hv: (
                save_device(_d, _a, _l, _h)))
            ae.bind("<Return>", lambda _e, _d=did, _a=av, _l=lv, _h=hv: (
                save_device(_d, _a, _l, _h)))
            se.bind("<FocusOut>", lambda _e, _d=did, _a=av, _l=lv, _h=hv: (
                save_device(_d, _a, _l, _h)))
            se.bind("<Return>", lambda _e, _d=did, _a=av, _l=lv, _h=hv: (
                save_device(_d, _a, _l, _h)))
            dev_rows.append((did, av, lv, hv))
            r += 1
        hint = tk.Label(inner_d,
                        text="Leere Warnung = globaler Wert. "
                             "Alias erscheint in Widget, Tray und Overlay.",
                        anchor="w")
        hint.grid(row=r, column=0, columnspan=4, sticky="ew",
                  padx=12, pady=6)
        labels.append(hint)
        b_rel = tk.Button(inner_d, text="↻ Neu laden",
                          command=rebuild_device_tab)
        b_rel.grid(row=r + 1, column=0, columnspan=4, sticky="ew",
                   padx=12, pady=4)
        buttons.append(b_rel)
        inner_d.columnconfigure(0, weight=1)
        inner_d.columnconfigure(1, weight=1)
        apply_win_theme()

    def save_device(did, av, lv, hv):
        try:
            low = None
            t = lv.get().strip()
            if t != "":
                low = max(1, min(99, int(t)))
                lv.set(str(low))
        except Exception:
            lv.set("")
            low = None
        all_d = app.cfg.setdefault("devices_cfg", {})
        all_d[did] = {"alias": av.get().strip(), "hidden": bool(hv.get()),
                      "low": low}
        save_and_preview()

    # ---------- Tab: Extras ----------
    tab_x = tk.Frame(nb)
    nb.add(tab_x, text="Extras")
    frames.append(tab_x)
    inner_x = tk.Frame(tab_x)
    inner_x.pack(fill="both", expand=True, padx=6, pady=6)
    frames.append(inner_x)
    inner_x.columnconfigure(0, weight=1)
    xr = 0

    def section(title):
        nonlocal xr
        lb = tk.Label(inner_x, text=title, anchor="w")
        lb.grid(row=xr, column=0, columnspan=2, sticky="ew",
                padx=12, pady=(8, 2))
        labels.append(lb)
        try:
            th0 = app.cfg.get("theme", {})
            lb.configure(font=(th0.get("font_family", "Segoe UI"), 9, "bold"))
        except Exception:
            pass
        xr += 1

    def add_check(label, get, set_):
        nonlocal xr
        v = tk.BooleanVar(value=bool(get()))
        cb = tk.Checkbutton(inner_x, text=label, variable=v, anchor="w",
                            command=lambda: (set_(bool(v.get())),
                                             save_and_preview()))
        cb.grid(row=xr, column=0, columnspan=2, sticky="ew", padx=12, pady=2)
        checks.append(cb)
        xr += 1
        return v

    section("Warnungen")
    snd_var = add_check("Ton bei Warnungen",
                        lambda: app.cfg.get("warn_sound", True),
                        lambda val: app.cfg.__setitem__("warn_sound", val))
    full_var = add_check("„Voll geladen“ melden",
                         lambda: app.cfg.get("warn_full", True),
                         lambda val: app.cfg.__setitem__("warn_full", val))

    section("Fenster")
    from app import set_click_through as _sct

    def set_ct(val):
        app.cfg["click_through"] = bool(val)
        try:
            _sct(app.root, bool(val))
        except Exception:
            pass

    ct_var = add_check("Klicks durchlassen (Click-Through)",
                       lambda: app.cfg.get("click_through", False), set_ct)
    snap_var = add_check("An Bildschirmrändern einrasten",
                         lambda: app.cfg.get("snap_edges", True),
                         lambda val: app.cfg.__setitem__("snap_edges", val))
    game_var = add_check("Gaming-Modus (bei Vollbild verstecken)",
                         lambda: app.cfg.get("game_mode", False),
                         lambda val: app.cfg.__setitem__("game_mode", val))
    hk_on_var = tk.BooleanVar(value=bool(app.cfg.get("hotkey_enabled", True)))
    hk_var = tk.StringVar(value=app.cfg.get("hotkey", "ctrl+alt+l"))

    def apply_hotkey(_e=None):
        app.cfg["hotkey_enabled"] = bool(hk_on_var.get())
        app.cfg["hotkey"] = hk_var.get().strip().lower() or "ctrl+alt+l"
        try:
            app._register_hotkey()
        except Exception:
            pass
        save_and_preview()

    lb_hk = tk.Label(inner_x, text="Hotkey (vorholen/verstecken):", anchor="w")
    lb_hk.grid(row=xr, column=0, sticky="ew", padx=(12, 4), pady=4)
    labels.append(lb_hk)
    hk_entry = tk.Entry(inner_x, textvariable=hk_var, width=16)
    hk_entry.grid(row=xr, column=1, padx=(4, 12), pady=4, sticky="e")
    try:
        th_hk = app.cfg.get("theme", {})
        hk_entry.configure(bg=th_hk.get("card", "#24282e"),
                           fg=th_hk.get("fg", "#f2f2f2"),
                           insertbackground=th_hk.get("fg", "#f2f2f2"))
    except Exception:
        pass
    xr += 1
    entries.append(hk_entry)
    hk_entry.bind("<FocusOut>", apply_hotkey)
    hk_entry.bind("<Return>", apply_hotkey)
    cb_hk = tk.Checkbutton(inner_x, text="Hotkey aktiv", variable=hk_on_var,
                           anchor="w", command=apply_hotkey)
    cb_hk.grid(row=xr, column=0, columnspan=2, sticky="ew", padx=12, pady=2)
    checks.append(cb_hk)
    xr += 1

    section("Erscheinungsbild")
    auto_var2 = add_check("Windows Hell/Dunkel automatisch folgen",
                          lambda: app.cfg.get("auto_theme", False),
                          lambda val: app.cfg.__setitem__("auto_theme", val))
    det_var = add_check("Geräte-Details zeigen (Verbindung, Firmware)",
                        lambda: app.cfg.get("show_details", True),
                        lambda val: app.cfg.__setitem__("show_details",
                                                       val))

    section("MQTT Export (Home Assistant)")
    mq_on_var = add_check("An MQTT-Broker senden",
                          lambda: app.cfg.get("mqtt_enabled", False),
                          lambda val: app.cfg.__setitem__("mqtt_enabled",
                                                         val))
    mq_host_var = tk.StringVar(value=app.cfg.get("mqtt_host", "localhost"))
    mq_port_var = tk.StringVar(value=str(app.cfg.get("mqtt_port", 1883)))
    mq_user_var = tk.StringVar(value=app.cfg.get("mqtt_user", ""))
    mq_pw_var = tk.StringVar(value=app.cfg.get("mqtt_password", ""))
    mq_topic_var = tk.StringVar(value=app.cfg.get("mqtt_topic",
                                                  "logi-akku"))
    mq_entries = []

    _mqr = [xr]

    def mq_row(label, var, show=None):
        lb = tk.Label(inner_x, text=label, anchor="w")
        lb.grid(row=_mqr[0], column=0, sticky="ew", padx=(12, 4), pady=3)
        labels.append(lb)
        en = tk.Entry(inner_x, textvariable=var, width=22,
                      show=show or "")
        en.grid(row=_mqr[0], column=1, padx=(4, 12), pady=3, sticky="e")
        entries.append(en)
        mq_entries.append(en)
        _mqr[0] += 1

    mq_row("Broker-Host:", mq_host_var)
    mq_row("Port:", mq_port_var)
    mq_row("Benutzer:", mq_user_var)
    mq_row("Passwort:", mq_pw_var, show="•")
    mq_row("Topic-Basis:", mq_topic_var)
    xr = _mqr[0]

    def apply_mqtt(_e=None):
        try:
            app.cfg["mqtt_host"] = mq_host_var.get().strip() or "localhost"
            app.cfg["mqtt_port"] = int(mq_port_var.get().strip() or 1883)
            mq_port_var.set(str(app.cfg["mqtt_port"]))
        except Exception:
            mq_port_var.set("1883")
            app.cfg["mqtt_port"] = 1883
        app.cfg["mqtt_user"] = mq_user_var.get()
        app.cfg["mqtt_password"] = mq_pw_var.get()
        app.cfg["mqtt_topic"] = mq_topic_var.get().strip() or "logi-akku"
        mq_topic_var.set(app.cfg["mqtt_topic"])
        save_and_preview()

    for _en in mq_entries:
        _en.bind("<FocusOut>", apply_mqtt)
        _en.bind("<Return>", apply_mqtt)
    mq_ha_var = add_check("Home-Assistant-Auto-Discovery",
                          lambda: app.cfg.get("mqtt_ha", True),
                          lambda val: app.cfg.__setitem__("mqtt_ha", val))

    section("Web-Dashboard (Browser)")
    web_on_var = add_check("Lokale Webseite aktivieren",
                           lambda: app.cfg.get("web_enabled", True),
                           lambda val: (app.cfg.__setitem__("web_enabled",
                                                           val),
                                        app.restart_web()))
    web_port_var = tk.StringVar(value=str(app.cfg.get("web_port", 8321)))
    lb_wp = tk.Label(inner_x, text="Port (nur dieser PC):", anchor="w")
    lb_wp.grid(row=xr, column=0, sticky="ew", padx=(12, 4), pady=3)
    labels.append(lb_wp)
    en_wp = tk.Entry(inner_x, textvariable=web_port_var, width=10)
    en_wp.grid(row=xr, column=1, padx=(4, 12), pady=3, sticky="e")
    entries.append(en_wp)
    xr += 1

    def apply_web(_e=None):
        try:
            app.cfg["web_port"] = int(web_port_var.get().strip() or 8321)
            web_port_var.set(str(app.cfg["web_port"]))
        except Exception:
            web_port_var.set("8321")
            app.cfg["web_port"] = 8321
        try:
            app.restart_web()
        except Exception:
            pass
        save_and_preview()

    en_wp.bind("<FocusOut>", apply_web)
    en_wp.bind("<Return>", apply_web)
    b_web = tk.Button(inner_x, text="🌐 Dashboard im Browser öffnen …",
                      command=lambda: app.open_dashboard())
    b_web.grid(row=xr, column=0, columnspan=2, sticky="ew", padx=12, pady=3)
    buttons.append(b_web)
    xr += 1

    section("Sicherung")
    b_exp = tk.Button(inner_x, text="💾 Einstellungen exportieren …",
                      command=lambda: export_cfg())
    b_exp.grid(row=xr, column=0, columnspan=2, sticky="ew", padx=12, pady=3)
    buttons.append(b_exp)
    xr += 1
    b_imp = tk.Button(inner_x, text="📂 Einstellungen importieren …",
                      command=lambda: import_cfg())
    b_imp.grid(row=xr, column=0, columnspan=2, sticky="ew", padx=12, pady=3)
    buttons.append(b_imp)
    xr += 1

    def export_cfg():
        try:
            from tkinter import filedialog
            from app import export_config as _exp
            p = filedialog.asksaveasfilename(
                defaultextension=".json",
                filetypes=[("JSON", "*.json")],
                initialfile="logi-widget-backup.json",
                title="Einstellungen exportieren")
            if p:
                save_and_preview()
                _exp(p)
        except Exception as ex:
            print("Export-Fehler:", ex)

    def import_cfg():
        try:
            from tkinter import filedialog
            from app import import_config as _imp
            p = filedialog.askopenfilename(
                filetypes=[("JSON", "*.json")],
                title="Einstellungen importieren")
            if p:
                app.cfg = _imp(p)
                try:
                    app._register_hotkey()
                except Exception:
                    pass
                rebuild_color_buttons()
                sync_all_controls()
                extras_sync()
                try:
                    rebuild_device_tab()
                except Exception:
                    pass
                save_and_preview(apply_win_flags=True)
                apply_win_theme()
        except Exception as ex:
            print("Import-Fehler:", ex)

    section("Backup bei G-HUB-Problemen")
    gh_auto_var = add_check("G HUB automatisch starten wenn aus",
                            lambda: app.cfg.get("ghub_autostart", True),
                            lambda val: app.cfg.__setitem__("ghub_autostart",
                                                           val))
    gh_rep_var = add_check("G HUB bei Hängen automatisch neu starten",
                           lambda: app.cfg.get("ghub_auto_repair", True),
                           lambda val: app.cfg.__setitem__("ghub_auto_repair",
                                                          val))
    db_var = add_check("G-HUB-Datei als Quelle nutzen",
                       lambda: app.cfg.get("ghub_db", True),
                       lambda val: app.cfg.__setitem__("ghub_db", val))
    ext_var = add_check("Externe Tools (Port 12321) nutzen",
                        lambda: app.cfg.get("ext_fallback", True),
                        lambda val: app.cfg.__setitem__("ext_fallback",
                                                       val))
    hid_var = add_check("HID-Direktabfrage (experimentell)",
                        lambda: app.cfg.get("hid_direct", True),
                        lambda val: app.cfg.__setitem__("hid_direct", val))
    lt_var = add_check("logitray.exe als Quelle (ohne G HUB, live)",
                       lambda: app.cfg.get("logitray_enabled", True),
                       lambda val: app.cfg.__setitem__("logitray_enabled",
                                                      val))
    cache_var = add_check("Letzten Stand aus Cache zeigen",
                          lambda: app.cfg.get("cache_fallback", True),
                          lambda val: app.cfg.__setitem__("cache_fallback",
                                                         val))

    section("Verlauf & Stream-Overlay")
    hist_var = add_check("Akku-Verlauf mitschreiben",
                         lambda: app.cfg.get("history_enabled", True),
                         lambda val: app.cfg.__setitem__("history_enabled", val))
    b_hist = tk.Button(inner_x, text="📈 Verlauf anzeigen …",
                       command=lambda: app.open_history())
    b_hist.grid(row=xr, column=0, columnspan=2, sticky="ew", padx=12, pady=4)
    buttons.append(b_hist)
    xr += 1
    ov_var = add_check("Overlay-Datei für OBS schreiben",
                       lambda: app.cfg.get("overlay_enabled", False),
                       lambda val: (app.cfg.__setitem__("overlay_enabled", val),
                                    app._write_overlay()))
    lb_ov = tk.Label(inner_x, text="Datei:", anchor="w")
    lb_ov.grid(row=xr, column=0, sticky="ew", padx=(12, 4), pady=3)
    labels.append(lb_ov)
    ov_path_var = tk.StringVar(value=app.cfg.get("overlay_path", "overlay.txt"))
    ov_path = tk.Entry(inner_x, textvariable=ov_path_var, width=24)
    ov_path.grid(row=xr, column=1, padx=(4, 12), pady=3, sticky="e")
    xr += 1
    lb_tpl = tk.Label(inner_x, text="Format:", anchor="w")
    lb_tpl.grid(row=xr, column=0, sticky="ew", padx=(12, 4), pady=3)
    labels.append(lb_tpl)
    ov_tpl_var = tk.StringVar(
        value=app.cfg.get("overlay_template", "{name}: {pct}%"))
    ov_tpl = tk.Entry(inner_x, textvariable=ov_tpl_var, width=24)
    ov_tpl.grid(row=xr, column=1, padx=(4, 12), pady=3, sticky="e")
    xr += 1

    def apply_overlay(_e=None):
        app.cfg["overlay_path"] = ov_path_var.get().strip() or "overlay.txt"
        app.cfg["overlay_template"] = (ov_tpl_var.get().strip()
                                       or "{name}: {pct}%")
        try:
            app._write_overlay()
        except Exception:
            pass
        save_and_preview()

    entries.append(ov_path)
    entries.append(ov_tpl)
    ov_path.bind("<FocusOut>", apply_overlay)
    ov_tpl.bind("<FocusOut>", apply_overlay)
    ov_path.bind("<Return>", apply_overlay)
    ov_tpl.bind("<Return>", apply_overlay)
    try:
        th_ov = app.cfg.get("theme", {})
        for _e in (ov_path, ov_tpl, hk_entry):
            _e.configure(bg=th_ov.get("card", "#24282e"),
                         fg=th_ov.get("fg", "#f2f2f2"),
                         insertbackground=th_ov.get("fg", "#f2f2f2"))
    except Exception:
        pass

    def extras_sync():
        try:
            snd_var.set(bool(app.cfg.get("warn_sound", True)))
        except Exception:
            pass
        try:
            gh_auto_var.set(bool(app.cfg.get("ghub_autostart", True)))
        except Exception:
            pass
        try:
            gh_rep_var.set(bool(app.cfg.get("ghub_auto_repair", True)))
        except Exception:
            pass
        try:
            db_var.set(bool(app.cfg.get("ghub_db", True)))
        except Exception:
            pass
        try:
            ext_var.set(bool(app.cfg.get("ext_fallback", True)))
        except Exception:
            pass
        try:
            hid_var.set(bool(app.cfg.get("hid_direct", True)))
        except Exception:
            pass
        try:
            lt_var.set(bool(app.cfg.get("logitray_enabled", True)))
        except Exception:
            pass
        for _v, _k, _d in ((game_var, "game_mode", False),
                           (det_var, "show_details", True),
                           (mq_on_var, "mqtt_enabled", False),
                           (mq_ha_var, "mqtt_ha", True),
                           (web_on_var, "web_enabled", True)):
            try:
                _v.set(bool(app.cfg.get(_k, _d)))
            except Exception:
                pass
        try:
            web_port_var.set(str(app.cfg.get("web_port", 8321)))
        except Exception:
            pass
        for _v, _k in ((mq_host_var, "mqtt_host"),
                       (mq_port_var, "mqtt_port"),
                       (mq_user_var, "mqtt_user"),
                       (mq_pw_var, "mqtt_password"),
                       (mq_topic_var, "mqtt_topic")):
            try:
                _v.set(str(app.cfg.get(_k, _v.get())))
            except Exception:
                pass
        try:
            cache_var.set(bool(app.cfg.get("cache_fallback", True)))
        except Exception:
            pass
        try:
            full_var.set(bool(app.cfg.get("warn_full", True)))
        except Exception:
            pass
        try:
            ct_var.set(bool(app.cfg.get("click_through", False)))
        except Exception:
            pass
        try:
            snap_var.set(bool(app.cfg.get("snap_edges", True)))
        except Exception:
            pass
        try:
            hk_on_var.set(bool(app.cfg.get("hotkey_enabled", True)))
            hk_var.set(app.cfg.get("hotkey", "ctrl+alt+l"))
        except Exception:
            pass
        try:
            auto_var2.set(bool(app.cfg.get("auto_theme", False)))
        except Exception:
            pass
        try:
            hist_var.set(bool(app.cfg.get("history_enabled", True)))
        except Exception:
            pass
        try:
            ov_var.set(bool(app.cfg.get("overlay_enabled", False)))
            ov_path_var.set(app.cfg.get("overlay_path", "overlay.txt"))
            ov_tpl_var.set(app.cfg.get("overlay_template",
                                       "{name}: {pct}%"))
        except Exception:
            pass

    _orig_sync = sync_controls

    def sync_all_controls():
        _orig_sync()
        extras_sync()

    # ---------- Bottom-Buttons ----------
    def save_and_preview(apply_win_flags=False):
        save_config(app.cfg)
        try:
            app.apply_theme(apply_win_flags=apply_win_flags)
        except Exception:
            pass

    btn_bar = tk.Frame(win, pady=8)
    btn_bar.pack(fill="x", padx=12)
    b_reset = tk.Button(btn_bar, text="Zurücksetzen",
                        command=lambda: (app.cfg["theme"].update(THEMES["Dunkel"]),
                                         preset_var.set("Dunkel"),
                                         rebuild_color_buttons(),
                                         sync_all_controls(),
                                         save_and_preview(), apply_win_theme()))
    b_reset.pack(side="left")
    buttons.append(b_reset)
    b_save = tk.Button(btn_bar, text="Speichern & Schließen",
                       command=lambda: (save_and_preview(), on_close()))
    b_save.pack(side="right")
    buttons.append(b_save)
    b_apply = tk.Button(btn_bar, text="Übernehmen",
                        command=lambda: save_and_preview())
    b_apply.pack(side="right", padx=6)
    buttons.append(b_apply)

    def on_close():
        app._settings_win = None
        win.destroy()

    win.protocol("WM_DELETE_WINDOW", on_close)
    apply_win_theme()
    try:
        rebuild_device_tab()
    except Exception:
        pass
