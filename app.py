"""Vibes Radio Map — Flask backend.

Serves the map UI, a station list API backed by stations.json (list, add,
remove), and station-scoped stream endpoints that fetch upstream streams
with browser-like headers and rewrite HLS playlists so segments also come
through us (this sidesteps CORS and Referer/UA blocking). Segment URLs are
signed, time-limited tokens — there is no open proxy.

Run:  python app.py   ->  http://127.0.0.1:5000
"""

import hashlib
import hmac
import json
import os
import re
import threading
import time
from urllib.parse import quote, urljoin, urlparse

import requests
from flask import Flask, Response, jsonify, render_template, request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIONS_FILE = os.path.join(BASE_DIR, "stations.json")

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
app = Flask(__name__)
_sessions = threading.local()


def get_session() -> requests.Session:
    """Thread-local requests.Session.

    Flask runs with threaded=True (one worker thread per request), and
    requests.Session is not thread-safe — its connection pool and cookie
    jar assume single-thread use. Each worker thread therefore gets its
    own session, created lazily on first use.
    """
    s = getattr(_sessions, "session", None)
    if s is None:
        s = requests.Session()
        s.headers.update({"User-Agent": BROWSER_UA})
        _sessions.session = s
    return s

# Segment URLs handed to the player are short-lived signed tokens, not an
# open "fetch me anything" endpoint: anyone who learns a segment URL can
# only use it (at that exact URL) until it expires.
SEG_SECRET = os.urandom(32)
SEG_TTL = 900  # seconds; long enough for a session, short enough to matter


def referer_header(url):
    """A browser-plausible Referer derived from *url*'s own origin.

    Some stream hosts reject requests without a Referer "from their site";
    claiming the stream's own origin is the least weird thing to send.
    """
    p = urlparse(url)
    if p.scheme in ("http", "https") and p.netloc:
        return {"Referer": f"{p.scheme}://{p.netloc}/"}
    return {}

_lock = threading.Lock()


# ---------------------------------------------------------------- stations --

def load_stations():
    # utf-8-sig: tolerate a UTF-8 BOM (Windows Notepad / PowerShell write one)
    with open(STATIONS_FILE, encoding="utf-8-sig") as f:
        return json.load(f)


def save_stations(stations):
    """Atomically write the station list (temp file + rename)."""
    tmp = STATIONS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(stations, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, STATIONS_FILE)


def slugify(name):
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "station"


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/stations")
def api_list_stations():
    with _lock:
        return jsonify(load_stations())


@app.post("/api/stations")
def api_add_station():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name") or "").strip()
    stream = str(data.get("stream") or "").strip()
    if not name:
        return jsonify(error="name is required"), 400
    parsed = urlparse(stream)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return jsonify(error="stream must be a valid http(s) URL"), 400

    def text(key):
        v = str(data.get(key) or "").strip()
        return v or None

    def num(key):
        v = data.get(key)
        if v is None or v == "":
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    lat, lng = num("lat"), num("lng")
    if (lat is None) != (lng is None) or (lat is not None and not (-90 <= lat <= 90 and -180 <= lng <= 180)):
        return jsonify(error="lat and lng must both be set (or both left empty)"), 400

    st = {
        "id": None,  # filled below once a unique one is chosen
        "name": name,
        "stream": stream,
        "hls": bool(data.get("hls")) or "m3u8" in stream.lower(),
    }
    for key in ("frequency", "codec", "country", "region", "city", "logo"):
        v = text(key)
        if v:
            st[key] = v
    if lat is not None:
        st["lat"] = lat
        st["lng"] = lng

    with _lock:
        stations = load_stations()
        existing = {s.get("id") for s in stations}
        base = slugify(name)
        st["id"] = base
        i = 2
        while st["id"] in existing:
            st["id"] = f"{base}-{i}"
            i += 1
        stations.append(st)
        save_stations(stations)
    return jsonify(st), 201


@app.delete("/api/stations/<station_id>")
def api_delete_station(station_id):
    with _lock:
        stations = load_stations()
        remaining = [s for s in stations if s.get("id") != station_id]
        if len(remaining) == len(stations):
            return jsonify(error="station not found"), 404
        save_stations(remaining)
    return jsonify(ok=True)


# ------------------------------------------------------------- stream /seg --

def is_m3u8(url, content_type):
    if "mpegurl" in (content_type or "").lower():
        return True
    return urlparse(url).path.lower().endswith(".m3u8")


def _sign(url, exp):
    return hmac.new(SEG_SECRET, f"{url}|{exp}".encode("utf-8"),
                    hashlib.sha256).hexdigest()


def _verify(url, exp, sig):
    try:
        exp = int(exp)
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(_sign(url, exp), sig or "")


def seg_url(url):
    """Mint a signed, time-limited /seg token for *url*."""
    exp = int(time.time()) + SEG_TTL
    return ("/seg?u=" + quote(url, safe="") + f"&exp={exp}&sig=" + _sign(url, exp))


def _seg_target(base_url, uri):
    """Resolve *uri* against *base_url*; pass non-http(s) URIs (e.g. data:)
    through untouched, otherwise mint a signed /seg URL."""
    p = urlparse(urljoin(base_url, uri))
    if p.scheme not in ("http", "https") or not p.netloc:
        return uri
    return seg_url(urljoin(base_url, uri))


def rewrite_m3u8(text, base_url):
    """Rewrite every media URI in a playlist to a signed /seg URL."""

    def sub(uri_match):
        return _seg_target(base_url, uri_match.group(1))

    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            if "URI=\"" in stripped:
                line = re.sub(r'URI="([^"]+)"', lambda m: "URI=\"" + sub(m) + "\"",
                              line)
        elif not stripped.startswith("/seg?"):
            line = _seg_target(base_url, stripped)
        lines.append(line)
    return "\n".join(lines) + "\n"


# StreamTheWorld variant playlists look like:
#   https://<n>.live.streamtheworld.com:443/<MOUNT>/HLS/<token>/<idx>/playlist.m3u8
# The embedded token is a session token that expires after ~1 minute (upstream
# then answers 410 "Session ID not found"). A fresh master fetch always mints a
# new token, so the master (via the redirector) is the recovery anchor.
STW_VARIANT_RE = re.compile(
    r"^https://[\w.-]+\.live\.streamtheworld\.com(?::443)?"
    r"/(?P<mount>[A-Za-z0-9_]+)/HLS/[\w-]+/(?P<idx>\d+)/playlist\.m3u8$",
    re.IGNORECASE,
)


def _recover_stw_variant(url):
    """Rebuild an expired StreamTheWorld variant playlist.

    Re-fetches a fresh master through the redirector (which mints a new
    session token, possibly on a different host) and serves the variant at
    the same index, rewritten to signed /seg URLs. Returns None on any
    failure so the caller falls back to an error response.
    """
    m = STW_VARIANT_RE.match(url)
    if not m:
        return None
    redirector = (
        "https://playerservices.streamtheworld.com/api/livestream-redirect/"
        + m.group("mount")
        + ".m3u8"
    )
    try:
        master = get_session().get(redirector, headers=referer_header(redirector), timeout=(6, 30))
    except requests.RequestException:
        return None
    if master.status_code != 200 or b"#EXTM3U" not in master.content[:1024]:
        return None
    variants = [
        line.strip()
        for line in master.text.splitlines()
        if line.strip()
        and not line.strip().startswith("#")
        and line.strip().lower().endswith(".m3u8")
    ]
    try:
        idx = int(m.group("idx"))
    except ValueError:
        return None
    if not variants or idx >= len(variants):
        return None
    try:
        variant = get_session().get(variants[idx], headers=referer_header(variants[idx]), timeout=(6, 30))
    except requests.RequestException:
        return None
    if variant.status_code != 200 or b"#EXTM3U" not in variant.content[:1024]:
        return None
    text = rewrite_m3u8(variant.text, variant.url)
    resp = Response(text, status=200)
    resp.headers["Content-Type"] = "application/vnd.apple.mpegurl; charset=utf-8"
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _fetch_and_rewrite(url):
    """Fetch *url* upstream (with browser-like headers), recovering an
    expired StreamTheWorld variant when possible, and return a response.

    Playlists are read fully and rewritten to signed /seg URLs; anything
    else is streamed straight through.
    """
    try:
        upstream = get_session().get(url, headers=referer_header(url),
                                     stream=True, timeout=(6, 60))
    except requests.RequestException as exc:
        recovered = _recover_stw_variant(url)
        if recovered is not None:
            return recovered
        return jsonify(error=f"upstream request failed: {exc}"), 502
    if upstream.status_code >= 400:
        recovered = _recover_stw_variant(url)
        if recovered is not None:
            upstream.close()
            return recovered
        upstream.close()
        return jsonify(error=f"upstream returned HTTP {upstream.status_code}"), 502

    ctype = upstream.headers.get("Content-Type", "")
    base_url = upstream.url  # final URL after redirects

    if is_m3u8(url, ctype):
        # Playlists are small: read the whole thing, sniff, rewrite.
        body = b"".join(upstream.iter_content(chunk_size=64 * 1024))
        if b"#EXTM3U" not in body[:1024]:
            # Not really a playlist (redirector served audio directly).
            return _stream_response(body, ctype)
        text = rewrite_m3u8(body.decode("utf-8", "replace"), base_url)
        resp = Response(text, status=200)
        resp.headers["Content-Type"] = "application/vnd.apple.mpegurl; charset=utf-8"
        resp.headers["Cache-Control"] = "no-store"
        return resp

    return _stream_response(None, ctype, upstream)


@app.get("/station/<station_id>/stream")
def station_stream(station_id):
    """Stream a station's upstream URL. Only URLs from the station list are
    reachable — there is no free-form url= parameter."""
    with _lock:
        stations = load_stations()
    st = next((s for s in stations if s.get("id") == station_id), None)
    if st is None:
        return jsonify(error="station not found"), 404
    stream = str(st.get("stream") or "").strip()
    parsed = urlparse(stream)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return jsonify(error="station has no valid stream URL"), 400
    return _fetch_and_rewrite(stream)


@app.get("/station/<station_id>/logo")
def station_logo(station_id):
    """Proxy a station's logo (same CORS/Referer reasons as the stream)."""
    with _lock:
        stations = load_stations()
    st = next((s for s in stations if s.get("id") == station_id), None)
    if st is None:
        return jsonify(error="station not found"), 404
    logo = str(st.get("logo") or "").strip()
    if not logo:
        return "", 404
    parsed = urlparse(logo)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return "", 400
    try:
        upstream = get_session().get(logo, headers=referer_header(logo),
                                     stream=True, timeout=(6, 30))
    except requests.RequestException:
        # Frontend falls back to the default radio icon on any error.
        return "", 502
    if upstream.status_code >= 400:
        upstream.close()
        return "", 502
    ctype = upstream.headers.get("Content-Type", "")
    body = b"".join(upstream.iter_content(chunk_size=64 * 1024))
    return _stream_response(body, ctype)


@app.get("/seg")
def seg():
    """Serve one upstream segment for a signed, time-limited token.

    /seg?u=<url>&exp=<unix-ts>&sig=<hmac>  — the signature binds the exact
    URL and expiry, so a leaked token can't be re-pointed at another URL
    and stops working once it expires.
    """
    u = request.args.get("u") or ""
    exp = request.args.get("exp") or ""
    sig = request.args.get("sig") or ""
    parsed = urlparse(u)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return jsonify(error="only http(s) URLs may be fetched"), 400
    if not _verify(u, exp, sig):
        return jsonify(error="invalid segment token"), 403
    try:
        if int(exp) < int(time.time()):
            return jsonify(error="segment token expired"), 403
    except (TypeError, ValueError):
        return jsonify(error="segment token expired"), 403
    return _fetch_and_rewrite(u)


def _stream_response(body, ctype, upstream=None):
    if body is not None:
        iterator = iter([body])
    else:
        iterator = upstream.iter_content(chunk_size=64 * 1024)

    def generate():
        for chunk in iterator:
            if chunk:
                yield chunk

    resp = Response(generate(), status=200)
    if ctype:
        resp.headers["Content-Type"] = ctype
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, threaded=True)
