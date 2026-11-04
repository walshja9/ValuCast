"""Local replay server for MLB Stats API calls. Throwaway branch only.

Every variant in a job reads the same answers, and fault scenarios can break a
call on a real socket while the product code runs unmodified.
"""
import json
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = "https://statsapi.mlb.com/"
EMPTY = {"schedule": '{"dates": []}', "logs": '{"stats": []}'}


def kind(path):
    if "/schedule?" in path:
        return "schedule"
    if "/stats?" in path:
        return "logs"
    if "/transactions?" in path:
        return "transactions"
    return "other"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, body):
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        replay = self.server.replay
        path = self.path.lstrip("/")
        with replay.lock:
            replay.calls.append(path)
            action = replay.fault(path, replay) if replay.fault else None
        try:
            if action is None:
                self._send(200, replay.lookup(path).encode("utf-8"))
            elif action == "500":
                self._send(500, b"injected")
            elif action == "garbage":
                self._send(200, b"not json")
            elif action == "hang":
                time.sleep(120)
            elif action == "drip":
                # Each byte beats the socket timeout, so only the step limit can stop this.
                self.send_response(200)
                self.send_header("Content-Length", "1000000")
                self.end_headers()
                for _ in range(400):
                    self.wfile.write(b" ")
                    self.wfile.flush()
                    time.sleep(5)
            elif isinstance(action, tuple):
                time.sleep(action[1])
                self._send(200, replay.lookup(path).encode("utf-8"))
            else:
                self._send(200, action)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:  # noqa: BLE001
            try:
                self._send(502, str(exc).encode("utf-8"))
            except OSError:
                pass


class Replay:
    def __init__(self, store=None, fault=None, record=True):
        self.store = {} if store is None else store
        self.fault = fault
        self.record = record
        self.calls = []
        self.lock = threading.Lock()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.server.replay = self
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def lookup(self, path):
        if path in self.store:
            return self.store[path]
        if self.record:
            with urllib.request.urlopen(UPSTREAM + path, timeout=30) as response:
                body = response.read().decode("utf-8")
            with self.lock:
                self.store[path] = body
            return body
        # Scenarios may ask for a date range or season the control run never did.
        which = kind(path)
        if which == "transactions":
            return next(body for key, body in self.store.items() if kind(key) == which)
        return EMPTY[which]

    def count(self, which):
        return sum(1 for path in self.calls if kind(path) == which)

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def dump(self, path):
        path.write_text(json.dumps(self.store), encoding="utf-8")
