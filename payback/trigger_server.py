#!/usr/bin/env python3
"""
Tiny HTTP trigger server for Payback activation.
Runs as a systemd service on the Pi host.

Endpoints:
  POST /activate  — starts activation in background, returns immediately
  GET  /status    — returns last activation result
"""
import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 7654
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATUS_FILE = os.path.join(SCRIPT_DIR, "last_result.json")
VENV_PYTHON = os.path.join(SCRIPT_DIR, "..", "venv", "bin", "python3")
ACTIVATE_SCRIPT = os.path.join(SCRIPT_DIR, "activate.py")

_lock = threading.Lock()
_running = False


def _run_activation():
    global _running
    python = VENV_PYTHON if os.path.exists(VENV_PYTHON) else "python3"
    result = subprocess.run(
        [python, ACTIVATE_SCRIPT],
        capture_output=True,
        text=True,
        cwd=os.path.join(SCRIPT_DIR, ".."),
    )
    status = {
        "exit_code": result.returncode,
        "success": result.returncode == 0,
        "stdout": result.stdout[-2000:],
        "stderr": result.stderr[-500:] if result.returncode != 0 else "",
        "timestamp": __import__("datetime").datetime.now().isoformat(),
    }
    with open(STATUS_FILE, "w") as f:
        json.dump(status, f, indent=2)
    with _lock:
        _running = False


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        global _running
        if self.path == "/activate":
            with _lock:
                if _running:
                    self._respond(409, {"status": "already_running"})
                    return
                _running = True
            threading.Thread(target=_run_activation, daemon=True).start()
            self._respond(202, {"status": "started"})
        else:
            self._respond(404, {"error": "not found"})

    def do_GET(self):
        if self.path == "/status":
            if os.path.exists(STATUS_FILE):
                with open(STATUS_FILE) as f:
                    data = json.load(f)
            else:
                data = {"status": "no_run_yet"}
            with _lock:
                data["running"] = _running
            self._respond(200, data)
        else:
            self._respond(404, {"error": "not found"})

    def _respond(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print(f"Payback trigger server listening on port {PORT}")
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
