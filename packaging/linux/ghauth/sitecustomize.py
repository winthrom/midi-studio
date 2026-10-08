"""Loaded automatically by Python (via PYTHONPATH) during the AppImage build.
python-appimage asks api.github.com which base image to use, anonymously, and GitHub
throttles anonymous callers that share an address (HTTP 403 rate limit).  Send the build's
GITHUB_TOKEN with that request, and retry politely if GitHub still says no."""
import os
import time
import urllib.error
import urllib.request

_real_urlopen = urllib.request.urlopen


def _urlopen(url, *args, **kwargs):
    target = url if isinstance(url, str) else getattr(url, "full_url", "")
    if "://api.github.com/" in target:
        token = os.environ.get("GITHUB_TOKEN", "")
        if token:
            req = url if not isinstance(url, str) else urllib.request.Request(url)
            req.add_header("Authorization", "Bearer " + token)
            req.add_header("Accept", "application/vnd.github+json")
            url = req
        for attempt in range(5):
            try:
                return _real_urlopen(url, *args, **kwargs)
            except urllib.error.HTTPError as exc:
                if exc.code not in (403, 429, 500, 502, 503) or attempt == 4:
                    raise
                time.sleep(20 * (attempt + 1))
    return _real_urlopen(url, *args, **kwargs)


urllib.request.urlopen = _urlopen
