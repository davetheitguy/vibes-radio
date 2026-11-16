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
  service: no user accounts, no rate limiting. The streaming endpoints are
  scoped to the stations in `stations.json` (there is no free-form URL
  proxy), and the add/remove-stations API is protected by a local write
  token plus a loopback Origin/Referer check — but none of that is a
  substitute for keeping the app off the public internet, where even this
  setup gets abused (SSRF, resource abuse, …).
- **The vibe coder takes no responsibility whatsoever** — human or machine —
  for anything that happens if you expose this app to the internet or to a
  network you don't fully control. If you do that, it's on you, and don't
  expect a patch from vibes.

## What it does

Open a web page and get a 3D globe of the radio stations.
Click any entry in the sidebar and that station starts streaming
straight into your browser — no apps, no plugins, no DRM.

Concretely:

- **A 3D globe** (globe.gl, fully local) with country outlines.
- **Click to stream.** Selecting a station flies the camera to it, shows an
  animated ripple ring at its location, and plays it. Spacebar toggles
  play/pause.
- **A sidebar** with station logos (or a built-in radio icon when a logo is
  missing or fails to load), frequencies, and country.
- **Your own stations:** a floating **+** button opens a form to add a station
  (name, stream URL, frequency, logo, coordinates, HLS toggle). Hover any
  station in the sidebar for a trash icon to remove it — with a confirm prompt
  first.
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
rewritten so that every audio segment also routes through the backend via a
signed, time-limited `/seg` URL — and if a StreamTheWorld session token
expires mid-play, the backend re-mints a fresh one automatically. You never
notice; that's the point.

## Quick start

```
python -m pip install -r requirements.txt
python app.py
```

Then open <http://127.0.0.1:5000> and pick a station.

The web UI already handles add/remove. To script the write API yourself,
send the write token as the `X-Vibes-Token` header (or a `?token=` query
param); it's printed at startup and stored in `.vibes_token` next to
`app.py`:

```
curl -X POST http://127.0.0.1:5000/api/stations \
  -H "X-Vibes-Token: $(cat .vibes_token)" \
  -H "Content-Type: application/json" \
  -d '{"name": "My Station", "stream": "https://example.com/stream.mp3"}'
```

(Loopback only, on purpose — see the warning above. Do not port-forward,
reverse-proxy, or otherwise expose it to the internet.)

## How it works

| Route | Purpose |
| --- | --- |
| `GET /` | The map UI (`templates/index.html`) |
| `GET /api/stations` | The station list (reads `stations.json` on every request) |
| `POST /api/stations` | Add a station (JSON body: `name`, `stream`, plus optional `frequency`, `codec`, `country`, `region`, `city`, `logo`, `lat`/`lng`, `hls`). Requires the write token (`X-Vibes-Token` header or `?token=`); any present `Origin`/`Referer` must be `127.0.0.1`/`localhost`. Returns `201` with the created station. |
| `DELETE /api/stations/<id>` | Remove a station by id. Same token + loopback check as `POST`. Returns `404` if it doesn't exist. |
| `GET /station/<id>/stream` | Fetch the station's upstream stream with a browser User-Agent + Referer; HLS playlists (`#EXTM3U`) are rewritten so every segment routes through `/seg`. |
| `GET /station/<id>/logo` | Fetch the station's logo image (same CORS/Referer reasons as the stream). |
| `GET /seg` | Serve one upstream segment via a signed, time-limited token (`u`, `exp`, `sig` query params); the signature is verified before anything is fetched. |

`stations.json` is the single source of truth for the station list. It's read
on every request (no restart needed), and it's the only place the UI's
add/remove buttons write — new stations are appended with an auto-generated id,
removals are filtered out and saved.

## Globe

The map is a 3D globe rendered by **globe.gl** (three.js bundled inside the
UMD build): local Earth textures, country outlines from Natural Earth GeoJSON
(`static/countries-110m.geojson`), rendered entirely in the browser. Selecting
a station flies the globe to its location and shows a single animated ripple
ring — no pins. No tile server, no API key, no third-party runtime requests —
everything ships in `static/`.

## Project structure

| File | What it is |
| --- | --- |
| `app.py` | The entire Flask backend: routes, station-scoped streaming, signed segments, HLS rewriting, STW recovery |
| `templates/index.html` | The entire frontend: globe, sidebar, player (one file, zero build step) |
| `stations.json` | The curated station list — edit it to change what's on the globe (re-read on every request, no restart needed) |
| `static/globe.gl.min.js` | globe.gl v2.46.2 UMD bundle (three.js included), self-hosted — no CDN |
| `static/img/` | Local Earth textures: blue marble, topology bump map, night lights |
| `static/countries-50m.geojson` | Natural Earth country outlines (fine), bundled locally |
| `static/countries-110m.geojson` | Natural Earth country outlines (coarse fallback) |
| `requirements.txt` | Two Python packages: `flask` and `requests` |
| `.vibes_token` | The write-API token, generated on first run and git-ignored — needed only if you script the add/remove API |

## Notes

- Playback is routed through the backend, so your browser never talks to the
  radio servers directly.
- The six big commercial Montréal stations (Énergie, Virgin, Classik, Café
  Musique, L'Écho, Rock Détour) could not be found with public stream URLs on
  the Radio Browser directory; the curated list contains the 20 stations that
  actually work.
- There is no free-form URL proxy: the backend only fetches the stream and
  logo URLs of stations listed in `stations.json`, so there's no SSRF surface
  to begin with.
- The add/remove API is token-gated and CSRF-checked: a random token is
  generated on first run (printed at startup, stored in `.vibes_token`), and
  any request whose `Origin`/`Referer` isn't loopback is rejected even with a
  valid token — a malicious page in the same browser can't drive the API.
- Run it on `127.0.0.1` (the default). It binds to loopback only — don't
  expose it to the internet as-is. It has **not** been pen tested, and the
  vibe coder takes no responsibility for what happens if you do. See the
  warning at the top of this file.

---

*Built with 100% vibes, 0% manual typing. 🎧*
