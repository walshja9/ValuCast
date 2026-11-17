"""Rehearsal-only HTTP interception, derived from injury-final 460f388e."""
import os

BASE = os.environ.get("REHEARSAL_PROXY")
if BASE:
    import base64
    import email.message
    import io
    import json
    import socket
    import urllib.error
    import urllib.request
    import urllib.response
    from urllib.parse import urlsplit

    endpoint = urlsplit(BASE)
    if endpoint.scheme != "http" or endpoint.hostname != "127.0.0.1" or not endpoint.port:
        os._exit(78)
    real_open = urllib.request.OpenerDirector.open
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def guard(address):
        if not isinstance(address, tuple) or address[:2] != ("127.0.0.1", endpoint.port):
            raise OSError("uncaptured network is blocked by rehearsal")

    def connect(sock, address):
        guard(address)
        return real_connect(sock, address)

    def connect_ex(sock, address):
        guard(address)
        return real_connect_ex(sock, address)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex

    def getaddrinfo(host, port, *args, **kwargs):
        guard((host, int(port)))
        return real_getaddrinfo(host, port, *args, **kwargs)

    def blocked(*args, **kwargs):
        raise OSError("uncaptured network is blocked by rehearsal")

    socket.getaddrinfo = getaddrinfo
    socket.gethostbyname = blocked
    socket.gethostbyname_ex = blocked
    socket.socket.sendto = blocked
    if hasattr(socket.socket, "sendmsg"):
        socket.socket.sendmsg = blocked

    def exchange(method, url, headers, body):
        payload = json.dumps({"method": method, "url": url,
                              "headers": sorted((k.lower(), v) for k, v in headers),
                              "body": base64.b64encode(body).decode() if body else None}).encode()
        req = urllib.request.Request(BASE, data=payload, headers={"Content-Type": "application/json"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with real_open(opener, req, timeout=180) as response:
            result = json.loads(response.read())
        if "error" in result:
            if result["error"] == "timeout":
                raise TimeoutError("cached upstream timeout")
            raise urllib.error.URLError("cached upstream failure")
        return result

    def replay_open(self, fullurl, data=None, timeout=socket._GLOBAL_DEFAULT_TIMEOUT):
        req = fullurl if isinstance(fullurl, urllib.request.Request) else urllib.request.Request(fullurl)
        if data is not None:
            req.data = data
        result = exchange(req.get_method(), req.full_url, req.header_items(), req.data)
        headers = email.message.Message()
        for key, value in result["headers"]:
            headers[key] = value
        body = io.BytesIO(base64.b64decode(result["body"]))
        if result["status"] >= 400:
            raise urllib.error.HTTPError(result["url"], result["status"], result["reason"], headers, body)
        response = urllib.response.addinfourl(body, headers, result["url"], result["status"])
        response.reason = result["reason"]
        return response

    urllib.request.OpenerDirector.open = replay_open

    try:
        import requests

        def send(self, request, **kwargs):
            try:
                result = exchange(request.method, request.url, request.headers.items(), request.body)
            except TimeoutError as exc:
                raise requests.exceptions.Timeout("cached upstream timeout", request=request) from exc
            except urllib.error.URLError as exc:
                raise requests.exceptions.ConnectionError("cached upstream failure", request=request) from exc
            response = requests.Response()
            response.status_code = result["status"]
            response.reason = result["reason"]
            response.url = result["url"]
            response.headers = requests.structures.CaseInsensitiveDict(result["headers"])
            response.raw = requests.packages.urllib3.response.HTTPResponse(
                body=io.BytesIO(base64.b64decode(result["body"])),
                headers=response.headers, preload_content=False)
            response._content = response.raw.read(decode_content=True)
            response._content_consumed = True
            response.encoding = requests.utils.get_encoding_from_headers(response.headers)
            response.request = request
            return response

        requests.sessions.Session.send = send
    except ImportError:
        pass
