from __future__ import annotations
import json, secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse, parse_qs

FILES_DIR = Path("fixtures/files")
SESS = {}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        return

    def _sid(self):
        raw = self.headers.get("Cookie") or ""
        for part in raw.split(";"):
            part = part.strip()
            if part.startswith("sg_sid="):
                return part.split("=", 1)[1]
        return None

    def _send(self, st, body, ctype="application/json", cookie=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(st)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def _read(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        try:
            return json.loads(raw.decode() or "{}")
        except json.JSONDecodeError:
            return {}

    def do_POST(self):
        path = unquote(urlparse(self.path).path)
        if path == "/login":
            body = self._read()
            if body.get("username") != "sheet-bot" or body.get("password") != "sheet-fixture-only":
                return self._send(401, {"error": "bad login"})
            sid = secrets.token_hex(8)
            tok = secrets.token_hex(8)
            SESS[sid] = {"token": tok, "uses": 0}
            return self._send(200, {"download_token": tok}, cookie=f"sg_sid={sid}; Path=/; HttpOnly")
        if path == "/token/refresh":
            sid = self._sid()
            sess = SESS.get(sid)
            if not sess:
                return self._send(401, {"error": "no session"})
            tok = secrets.token_hex(8)
            sess["token"] = tok
            sess["uses"] = 0
            return self._send(200, {"download_token": tok})
        return self._send(404, {"error": "no"})

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        qs = parse_qs(urlparse(self.path).query)
        sid = self._sid()
        sess = SESS.get(sid)
        if path == "/files":
            if not sess:
                return self._send(401, {"error": "no session"})
            names = sorted(p.name for p in FILES_DIR.glob("*.xlsx"))
            return self._send(200, {"files": names})
        if path.startswith("/download/"):
            if not sess:
                return self._send(401, {"error": "no session"})
            token = qs.get("token", [None])[0]
            if token != sess["token"]:
                return self._send(401, {"error": "bad token"})
            if sess["uses"] >= 2:
                return self._send(401, {"error": "token_expired"})
            name = path.split("/")[-1]
            fp = FILES_DIR / name
            if not fp.is_file():
                return self._send(404, {"error": "no file"})
            data = fp.read_bytes()
            sess["uses"] += 1
            return self._send(200, data, ctype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        return self._send(404, {"error": "no"})

def serve(host="127.0.0.1", port=8769, files="fixtures/files"):
    global FILES_DIR
    FILES_DIR = Path(files)
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"sheetgate fixture portal on http://{host}:{port} files={FILES_DIR}")
    httpd.serve_forever()
