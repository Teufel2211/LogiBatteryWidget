# 🔋 LogiBatteryWidget

Windows-Widget + Tray-App für den Akkustand aller Logitech-Geräte –
mit Live-Updates, ausfallsicherer Fallback-Kette (funktioniert **auch ohne
laufendes G HUB**), frei anpassbarem Design, Verlauf, Stream-Overlay,
Web-Dashboard und MQTT-Export.

Getestet mit: **G502 LIGHTSPEED Wireless Gaming Mouse** (USB-Dongle, G HUB).

## Start

**Variante A – Python:**
```
pip install -r requirements.txt
python app.py
```
(`start.bat` macht genau das per Doppelklick. `python app.py --demo`
startet eine Demo ohne Hardware.)

**Variante B – .exe bauen:**
```
pip install pyinstaller
python -m PyInstaller --noconfirm --clean --onefile --windowed --name LogiBatteryWidget app.py
```
Danach liegt `LogiBatteryWidget.exe` in `dist/` (ohne Konsolenfenster,
mit Autostart per Registry möglich).

**logitray.exe (optional, für Messwerte ohne G HUB):**
`get-logitray.bat` lädt es von
[Ithilias/logitray](https://github.com/Ithilias/logitray) in den
Programmordner. Ohne die Datei entfallen nur die HID-Live-Werte –
alles andere läuft trotzdem.

## Funktionen

- **Widget + Tray:** rahmenloses Widget (Hintergrund- oder Vordergrund-Modus),
  frei verschiebbar mit Ecken-Snap, Position wird gespeichert; Tray-Icon mit
  Batterie-Symbol, Tooltip und Warnungen (Ton + „voll geladen"-Meldung)
- **Sofort-Updates:** G-HUB-Live-Push (`⚡live`) statt nur Timer-Polling
- **Redundante Quellen** (Fallback-Kette, aktive Quelle wird angezeigt):
  G HUB Websocket → externe Tools (Port 12321) → logitray/HID direkt →
  G-HUB-Datei-DB → Cache. Dazu Diagnose-Dialog mit
  G-HUB-Start/Neustart und automatischer Reparatur bei Hängern
- **🎨 Design-Editor:** 4 Vorlagen (Dunkel, Hell, Neon, Minimal), alle Farben,
  Schriften, Größen, Transparenz – mit Live-Vorschau; folgt auf Wunsch dem
  Windows Hell/Dunkel-Modus
- **📈 Verlauf & Prognose:** `history.csv` + Diagramm (Min/Max/Ø),
  Lade-Prognose („leer in ~Xh", „voll in ~X")
- **Extras:** Click-Through, Hotkey (`Strg+Alt+L`), Gaming-Modus
  (versteckt sich bei Vollbild), Pro-Gerät-Einstellungen
  (Alias, eigene Warnschwelle, Ausblenden), Einstellungen Ex-/Import
- **🌐 Web-Dashboard:** `http://127.0.0.1:8321/` (nur dieser PC) –
  auch als OBS-Browserquelle nutzbar; dazu `overlay.txt`-Export und
  **MQTT-Export** mit Home-Assistant-Discovery
- **Autostart:** Registry-Run-Key (`autostart_an.bat` / `autostart_aus.bat`
  oder per Rechtsklick/Tray)

## Dateien

| Datei | Zweck |
|---|---|
| `app.py` | Widget + Tray + Logik |
| `ghub.py` | G-HUB-Websocket (`ws://localhost:9010`) |
| `hidpp.py` | HID++-Direktabfrage (experimentell) |
| `fallback.py` | Datei-DB-, Extern- und logitray-Quellen |
| `mqtt_pub.py` | MQTT-Export |
| `webdash.py` | Web-Dashboard + JSON-API |
| `settings_ui.py` / `history_ui.py` / `diag_ui.py` | Dialoge |
| `requirements.txt` | Python-Abhängigkeiten |

Persönliche Daten (`config.json`, `cache.json`, `history.csv`,
`overlay.txt`, `*.exe`) stehen **nicht** im Repo (siehe `.gitignore`).

## Credits

- [Ithilias/logitray](https://github.com/Ithilias/logitray) – HID++ ohne G HUB
- G-HUB-Protokoll-Recherche u.a.: `bmrussell/LGBattery`,
  `andyvorld/LGSTrayBattery`, Solaar, OpenLogi-Docs

## Lizenz

MIT – siehe `LICENSE`.
