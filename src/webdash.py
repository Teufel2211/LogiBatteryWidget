"""Web-Dashboard für LogiBatteryWidget – lokale Seite + JSON-API.

Nur stdlib (http.server), läuft auf 127.0.0.1 (kein Netzwerkzugriff).
- GET /      -> Dashboard-Seite (Auto-Refresh, auch als OBS-Browserquelle)
- GET /api   -> {"devices": [...], "updated": "...", "source": "..."}
"""
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_state: dict = {"server": None, "thread": None, "port": None,
                 "data_fn": None}

PAGE = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Logi Akku</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #1a1d21; color: #f2f2f2;
         font-family: 'Segoe UI', Arial, sans-serif; padding: 24px; }
  h1 { font-size: 20px; margin-bottom: 4px; }
  .sub { color: #9aa0a6; font-size: 12px; margin-bottom: 16px; }
  .grid { display: grid; gap: 12px;
          grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); }
  .card { background: #24282e; border-radius: 10px; padding: 14px 16px; }
  .row { display: flex; justify-content: space-between; align-items: baseline;
         margin-bottom: 8px; }
  .name { font-weight: bold; font-size: 15px; }
  .pct { font-weight: bold; font-size: 20px; }
  .bar { background: #14161a; border-radius: 6px; height: 12px;
         overflow: hidden; }
  .fill { height: 100%; border-radius: 6px; transition: width .5s; }
  .meta { color: #9aa0a6; font-size: 12px; margin-top: 6px; }
  .ok { color: #2ecc71; } .mid { color: #f39c12; } .low { color: #e74c3c; }
  .err { color: #e74c3c; text-align: center; padding: 40px; }
</style>
</head>
<body>
<h1>&#128267; Logitech Akku</h1>
<div class="sub" id="sub">verbinde …</div>
<div class="grid" id="grid"></div>
<script>
async function load() {
  try {
    const r = await fetch('/api', {cache: 'no-store'});
    const j = await r.json();
    document.getElementById('sub').textContent =
      'Quelle: ' + (j.source || '–') + ' • Stand: ' + (j.updated || '–');
    const g = document.getElementById('grid');
    g.innerHTML = '';
    (j.devices || []).forEach(d => {
      const p = d.percentage;
      const cls = p == null ? '' : (d.charging ? 'ok'
                    : (p < 20 ? 'low' : (p < 50 ? 'mid' : 'ok')));
      const col = p == null ? '#555' : (d.charging ? '#2ecc71'
                    : (p < 20 ? '#e74c3c' : (p < 50 ? '#f39c12' : '#2ecc71')));
      const card = document.createElement('div');
      card.className = 'card';
      card.innerHTML =
        '<div class="row"><span class="name"></span>' +
        '<span class="pct ' + cls + '">' +
        (p == null ? '–' : ((d.charging ? '&#9889; ' : '') + p + '%')) +
        '</span></div>' +
        '<div class="bar"><div class="fill" style="width:' +
        (p == null ? 0 : p) + '%;background:' + col + '"></div></div>' +
        '<div class="meta">' + (d.info || '') + '</div>';
      card.querySelector('.name').textContent = d.name || '?';
      card.querySelector('.meta').textContent = d.info || '';
      g.appendChild(card);
    });
    if (!(j.devices || []).length) {
      g.innerHTML = '<div class="err">Keine Ger\u00e4te – l\u00e4uft G HUB?</div>';
    }
  } catch (e) {
    document.getElementById('sub').textContent = 'keine Verbindung';
  }
}
load();
setInterval(load, 2000);
</script>
</body>
</html>
"""


class _Handler(BaseHTTPRequestHandler):
    server_version = "LogiAkku/1"

    def log_message(self, format, *args):  # noqa: A002 (stdlib-Signatur)
        pass

    def _send(self, code, ctype, body):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        try:
            if self.path == "/" or self.path.startswith("/?"):
                self._send(200, "text/html", PAGE)
            elif self.path == "/api":
                fn = _state.get("data_fn")
                try:
                    payload = fn() if fn else {"devices": []}
                except Exception:
                    payload = {"devices": []}
                self._send(200, "application/json",
                           json.dumps(payload, ensure_ascii=False))
            else:
                self._send(404, "text/plain", "nix hier")
        except Exception:
            pass


def is_running():
    srv = _state.get("server")
    return srv is not None


def port():
    return _state.get("port")


def start(port, data_fn):
    """Startet (neu) auf 127.0.0.1:port. Gibt True/False zurück."""
    stop()
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", int(port)), _Handler)
    except Exception:
        return False
    _state["server"] = srv
    _state["port"] = int(port)
    _state["data_fn"] = data_fn
    th = threading.Thread(target=srv.serve_forever, daemon=True,
                          name="webdash")
    th.start()
    _state["thread"] = th
    return True


def stop():
    srv = _state.get("server")
    _state["server"] = None
    _state["port"] = None
    if srv is not None:
        try:
            srv.shutdown()
        except Exception:
            pass
        try:
            srv.server_close()
        except Exception:
            pass


def open_browser(port=None):
    try:
        webbrowser.open(f"http://127.0.0.1:{port or _state.get('port')}/")
        return True
    except Exception:
        return False
