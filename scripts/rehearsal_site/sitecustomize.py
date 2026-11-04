"""Rehearsal only. Sends MLB Stats API calls to the local replay server, so product code stays untouched."""
import os
import urllib.request

BASE = os.environ.get("REHEARSAL_MLB_PROXY")
if BASE:
    PREFIX = "https://statsapi.mlb.com/"
    real_urlopen = urllib.request.urlopen

    def urlopen(request, *args, **kwargs):
        url = request.full_url if isinstance(request, urllib.request.Request) else request
        if url.startswith(PREFIX):
            request = urllib.request.Request(f"{BASE}/{url[len(PREFIX):]}", headers={"User-Agent": "rehearsal"})
        return real_urlopen(request, *args, **kwargs)

    urllib.request.urlopen = urlopen
