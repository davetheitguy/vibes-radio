# Vibes Radio Map

📻 An interactive map of radio stations in and around Montréal (plus some UK
stations) that you can **actually listen to** in your browser. Point, click,
vibe.

> **Heads up: this project is 100% vibe coded.** Every line of code was written
> by a local AI coding assistant working from a human's vibes,
> prompts, and taste — not hand-typed. The human part was knowing what they
> wanted to hear; the machine did the typing, the debugging, and the
> StreamTheWorld token-recovery gymnastics. No lines were harmed (or
> intentionally written).

## ⚠️ Do NOT expose this to the internet

**This app is for local, single-user use on `127.0.0.1` only. Keep it there.**

- **It has not been pen tested or security-tested in any way.** No audit, no
  hardening, no bug bounty — it's a vibe-coded toy, not a hardened web
  service: no authentication, no rate limiting, and a `GET /proxy?url=...`
  endpoint that fetches whatever it's asked to fetch. That is exactly the kind
  of thing that gets abused the moment it's reachable from the public
  internet (open proxy, SSRF, resource abuse, …).
- **The vibe coder takes no responsibility whatsoever** — human or machine —
  for anything that happens if you expose this app to the internet or to a
  network you don't fully control. If you do that, it's on you, and don't
  expect a patch from vibes.

## What it does

Open a web page and get a map with one pin per radio station.
Click any pin (or any entry in the sidebar) and that station starts streaming
straight into your browser — no apps, no plugins, no DRM.

Concretely:

- **A Leaflet map** with one pin per station; the pin shows the
  frequency.
- **Click to stream.** Selecting a station centers the map on it and plays it.
  Spacebar toggles play/pause.
- **A sidebar** with station logos (or a built-in radio icon when a logo is
  missing or fails to load), frequencies, and country.
- **Your own stations:** a floating **+** button opens a form to add a station
  (name, stream URL, frequency, logo, coordinates, HLS toggle). Hover any
  station in the sidebar for a trash icon to remove it — with a confirm prompt
  first.
- **Clustering:** stations at the same coordinates collapse into a numbered
  badge when zoomed out and fan out into separate pins when zoomed in.
- **Real streaming playback:** HLS streams play through hls.js; MP3/AAC play
  natively in the browser.

The station list is a curated set of 20 working stations — the Montréal
public/community stations plus UK ones (BBC Radio 1–4, BBC Radio Sussex,
Magic 105.4, Radio Circulation).

## Why a proxy at all?

Most radio streams refuse to play directly in a browser: they're blocked by
CORS, or the server demands a browser User-Agent and a Referer it recognizes.
So the Flask backend fetches each stream **server-side with browser-like
headers** and pipes the bytes back to your browser. HLS playlists are
rewritten so that every audio segment also routes through the proxy — and if
a StreamTheWorld session token expires mid-play, the backend re-mints a fresh
one automatically. You never notice; that's the point.

## Quick start

```
python -m pip install -r requirements.txt
python app.py
```

Then open <http://127.0.0.1:5000> and pick a station.

(Loopback only, on purpose — see the warning above. Do not port-forward,
reverse-proxy, or otherwise expose it to the internet.)

## How it works

| Route | Purpose |
| --- | --- |
| `GET /` | The map UI (`templates/index.html`) |
| `GET /api/stations` | The station list (reads `stations.json` on every request) |
| `POST /api/stations` | Add a station (JSON body: `name`, `stream`, plus optional `frequency`, `codec`, `country`, `region`, `city`, `logo`, `lat`/`lng`, `hls`). Returns `201` with the created station. |
| `DELETE /api/stations/<id>` | Remove a station by id. Returns `404` if it doesn't exist. |
| `GET /proxy?url=...` | Fetch an upstream stream (or logo image) with a browser User-Agent + Referer; HLS playlists (`#EXTM3U`) are rewritten so all segments also route through the proxy. Private/loopback hosts are refused (SSRF guard). |

`stations.json` is the single source of truth for the station list. It's read
on every request (no restart needed), and it's the only place the UI's
add/remove buttons write — new stations are appended with an auto-generated id,
removals are filtered out and saved.

## Map tiles

The map uses plain **OpenStreetMap** tiles (`tile.openstreetmap.org`) — no
account, no API key, works out of the box. The OSM tile usage policy asks for
modest local use, which this app fits comfortably.

## Project structure

| File | What it is |
| --- | --- |
| `app.py` | The entire Flask backend: routes, proxy, HLS rewriting, STW recovery |
| `templates/index.html` | The entire frontend: map, sidebar, player, clustering (one file, zero build step) |
| `stations.json` | The curated station list — edit it to change what's on the map (re-read on every request, no restart needed) |
| `requirements.txt` | Two Python packages: `flask` and `requests` |

## Notes

- Playback is routed through the proxy, so your browser never talks to the
  radio servers directly.
- The six big commercial Montréal stations (Énergie, Virgin, Classik, Café
  Musique, L'Écho, Rock Détour) could not be found with public stream URLs on
  the Radio Browser directory; the curated list contains the 20 stations that
  actually work.
- The proxy refuses private/loopback hostnames (SSRF guard), so it's safe to
  point at `stations.json`-listed public streams only.
- Run it on `127.0.0.1` (the default). It binds to loopback only — don't
  expose the proxy to the internet as-is. It has **not** been pen tested, and
  the vibe coder takes no responsibility for what happens if you do. See the
  warning at the top of this file.

---

*Built with 100% vibes, 0% manual typing. 🎧*
