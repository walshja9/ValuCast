"""Private runner-local replay; adapted from rehearsal/injury-final 460f388e.

Only counts leave this server. Its TemporaryDirectory must never be uploaded.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

HOSTS = {"statsapi.mlb.com", "www.fangraphs.com", "baseballsavant.mlb.com",
         "harryknowsball.com", "www.milb.com",
         "diamonddynastiesleagueanalyzer.onrender.com"}


class FeedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urlsplit(newurl)
        if target.scheme != "https" or target.hostname not in HOSTS:
            raise ValueError("uncaptured redirect is blocked")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(request):
    url = urlsplit(request["url"])
    if url.scheme != "https" or url.hostname not in HOSTS or url.username or url.password:
        raise ValueError("uncaptured upstream is blocked")
    if request["method"] != "GET" or request.get("body"):
        raise ValueError("only read-only feed GET requests are permitted")
    headers = dict(request["headers"])
    if any(key.lower() in {"authorization", "cookie", "proxy-authorization"} for key in headers):
        raise ValueError("credentials are forbidden")
    req = urllib.request.Request(request["url"], headers=headers)
    try:
        response = urllib.request.build_opener(FeedRedirect()).open(req, timeout=60)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        return {"status": response.code, "reason": response.reason,
                "url": response.url, "headers": list(response.headers.items()),
                "body": base64.b64encode(response.read()).decode("ascii")}


class Cache:
    def __init__(self, directory, upstream=fetch):
        self.directory = Path(directory)
        self.upstream = upstream
        self.lock = threading.Lock()
        self.keys = {}
        self.calls = self.hits = self.errors = 0

    def lookup(self, request):
        key = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
        path = self.directory / key
        with self.lock:
            self.calls += 1
            key_lock = self.keys.setdefault(key, threading.Lock())
        # Serialize one exact request without delaying unrelated concurrent feeds.
        with key_lock:
            if path.exists():
                with self.lock:
                    self.hits += 1
                return json.loads(path.read_text(encoding="utf-8"))
            try:
                answer = self.upstream(request)
            except Exception as exc:
                reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
                category = "timeout" if isinstance(reason, TimeoutError) else "urlerror"
                answer = {"error": category}
            if "error" in answer or answer.get("status", 0) >= 400:
                with self.lock:
                    self.errors += 1
            path.write_text(json.dumps(answer), encoding="utf-8")
            return answer

    def counts(self):
        with self.lock:
            return {"requests": self.calls, "cache_hits": self.hits,
                    "upstream_requests": self.calls - self.hits,
                    "failed_upstream_requests": self.errors}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        try:
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            answer = self.server.cache.lookup(request)
            body = json.dumps(answer).encode()
            self.send_response(200)
        except Exception:
            body = b'{"error":"replay_protocol"}'
            self.send_response(500)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass


class Replay:
    def __init__(self):
        self.temp = tempfile.TemporaryDirectory(prefix="feed-replay-", dir=os.environ["RUNNER_TEMP"])
        self.cache = Cache(self.temp.name)
        class Server(ThreadingHTTPServer):
            request_queue_size = 64
        self.server = Server(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.server.cache = self.cache
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def counts(self):
        return self.cache.counts()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.temp.cleanup()


def self_test():
    from concurrent.futures import ThreadPoolExecutor
    import shutil
    import uuid
    def upstream(request):
        if request["url"] == "failure":
            raise TimeoutError()
        return {"status": 503 if request["url"] == "http-failure" else 200,
                "body": request["url"]}
    directory = Path(__file__).resolve().parent / (".replay-self-test-" + uuid.uuid4().hex)
    directory.mkdir()
    try:
        cache = Cache(directory, upstream)
        for url in ("steamer", "steamerr", "failure", "http-failure"):
            req = {"url": url, "method": "GET", "headers": [], "body": None}
            first = cache.lookup(req)
            assert cache.lookup(req) == first
        assert cache.counts() == {"requests": 8, "cache_hits": 4,
                                 "upstream_requests": 4, "failed_upstream_requests": 2}
        assert cache.lookup({"url": "steamer", "method": "GET", "headers": [], "body": None})["body"] != "steamerr"
        entered = threading.Barrier(2)
        observed = []
        def concurrent_upstream(request):
            observed.append(request["url"])
            entered.wait(timeout=5)
            if request["url"] == "concurrent-failure":
                raise TimeoutError()
            return {"status": 200}
        concurrent = Cache(directory, concurrent_upstream)
        requests = [{"url": url} for url in ("concurrent-success", "concurrent-failure")]
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(concurrent.lookup, req) for req in requests * 4]
            results = [future.result(timeout=10) for future in futures]
        assert sorted(observed) == ["concurrent-failure", "concurrent-success"]
        assert results[::2] == [{"status": 200}] * 4
        assert results[1::2] == [{"error": "timeout"}] * 4
        assert concurrent.counts() == {"requests": 8, "cache_hits": 6,
                                      "upstream_requests": 2, "failed_upstream_requests": 1}
    finally:
        shutil.rmtree(directory)
    print("replay self-test passed (offline; no sockets)")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true", required=True)
    parser.parse_args()
    self_test()
