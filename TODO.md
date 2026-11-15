# Vibes Radio — improvement backlog

Everything below is a *plan*, not done work. Grouped the way a human brain
actually thinks about it: **make it nicer**, **make it not fall over**,
**make it not be a front door for sketchy people**. Line numbers refer to
the code as of this writing; they'll drift.

---

## 🎛️ Usability

- [ ] **Buffering indicator.** The UI only knows two states: playing or
      error. There's no listener for `waiting`/`playing`/`stalled` on the
      audio element (index.html:539ff). Add a "buffering…" status (and maybe
      dim the EQ bars) so a slow station doesn't feel broken.
- [ ] **Smarter error messages + a Retry button.** Today every failure is
      the same generic toast ("Stream failed — the URL may be down, or the
      server blocked it.", index.html:542). The proxy *does* know the real
      reason — it catches the upstream exception (app.py:261). Return a
      sanitized reason + upstream status (see Security below) and surface it,
      plus a one-click **Retry** in the status bar instead of re-clicking the
      pin.
- [ ] **Surprise me 🎲.** One button, pick a random station that passes the
      current filters, play it. This whole app is a vibe machine; give it a
      dice roller.
- [ ] **Click-the-map to place a pin.** The add-station form demands hand-
      typed lat/lng with a "Provide both, or neither" validation
      (index.html:600). In add-mode, clicking the map should drop a draggable
      marker and fill the fields in. (Reverse geocoding would be a stretch
      goal, not required.)
- [ ] **Remember me (localStorage).** Nothing persists today (verified:
      zero `localStorage` matches in the template). Save + restore: volume,
      search query, active region filter, and last-played station. Cheap
      win, big "it's mine now" feeling.
- [ ] **Favorites.** A heart on each station/list row, persisted locally
      (localStorage or a local JSON file), with a "My favorites" filter.
      Pairs with the persistence item above.
- [ ] **More keyboard shortcuts.** Space already toggles play (index.html:570);
      add a few: `/` or `F` to focus search, `Esc` to close the add form /
      clear search, `R` for the surprise-me button. Show the shortcuts
      somewhere unobtrusive.
- [ ] **Station detail popup.** Clicking a pin today mostly just plays it.
      A popup showing name, frequency, genre, and the station's own website
      link would make the map feel like a real thing.
- [ ] **Filter reset.** When search + region filters are active, show a
      "clear filters" chip so the map doesn't silently look empty.
- [ ] **Empty states.** Zero results right now is a quiet empty map + empty
      list. Say something human: "no stations match that vibe — try
      clearing a filter."
- [ ] *(already done, do NOT re-add)* Volume slider exists (index.html:195)
      and Space-to-play exists. These are fine as-is.

## 🚦 Rate limiting & resilience

There is currently *no* throttling anywhere, and the dev server runs
`threaded=True` (app.py:308) which means one misbehaving client can spawn
unbounded threads. For a local single-user toy that's acceptable-but-
silly; here's the ladder, cheapest first:

- [ ] **Per-IP token bucket on the hot endpoints** — `GET /proxy`
      (app.py:244) and the write API (`POST`/`DELETE` /api/stations,
      app.py:85/141). A tiny in-memory bucket keyed on
      `request.remote_addr`, guarded by a lock (the server is threaded).
      No new dependencies needed; ~30 lines.
- [ ] **Upstream concurrency semaphore.** Wrap the proxy's upstream fetch
      (app.py:256) in a `threading.BoundedSemaphore` so a burst of clicks
      can't fan out into hundreds of in-flight upstream requests.
- [ ] **Cap the m3u8 body before parsing.** `rewrite_m3u8` works on the full
      `resp.content` with no size limit (app.py:275). A hostile or broken
      playlist can be arbitrarily large. Reject/trim anything above a
      sane cap (e.g. 1 MB) before it gets into memory.
- [ ] **Stream byte/duration cap on `/proxy`.** The upstream read timeout
      already exists (6s connect / 60s read, app.py:256) — good. Add an
      optional max-bytes per streamed response so a stuck "infinite" stream
      can't hold a connection and a thread forever.
- [ ] **Bound the thread fan-out.** `threaded=True` is unbounded; pair with
      the semaphore above or drop to a modest thread pool, so the process
      stays boring under load.
- [ ] *(already done, do NOT re-add)* Timeouts on all three upstream
      requests (app.py:212/231/256). Fine as-is.

## 🔒 Security

The README already says it: loopback-only, not pen tested, and
`/proxy?url=` is an open proxy by construction. These items turn that
"trust me, it's localhost" into "localhost AND I'd have to work a bit."

- [x] **Kill the open proxy (top priority).** `/proxy?url=` accepts any
      http(s) URL and the guard is a regex on the *hostname string*
      (app.py:45–48). Bypasses a string check doesn't catch:
      - names that *resolve* to private IPs (DNS rebinding,
        `nslu2local`-style names, public CNAMEs to 127.0.0.1),
      - **redirect hops**: `requests` follows redirects and the final URL
        is never re-checked — `http://ok.example/302 → http://169.254.169.254/`
        sails through (app.py:256, 271),
      - alternate IP encodings and non-standard ports.
      Two ways out, in order of preference:
      1. **Allowlist: only proxy URLs that exist in stations.json.**
         Change the API to `GET /proxy/station/<id>` and drop the free-form
         `url=` param entirely. Smallest surface, zero cleverness.
      2. If free-form must stay: resolve via `socket.getaddrinfo`, reject
         every resolved IP in private/link-local/CGNAT ranges
         (incl. 169.254/16, 100.64/10), and **re-validate on every redirect
         hop** via a redirect hook.
- [x] **Thread-local `requests.Session`.** The global session
      (app.py:28) is shared across all worker threads. Per-thread sessions
      (or one per request) remove the shared-mutable-state class of bug
      entirely.
- [x] **Auth on the write API.** `POST`/`DELETE /api/stations`
      (app.py:85/141) mutate `stations.json` with zero auth — any tab or
      script on the machine (or anything that can reach the port) can
      rewrite or nuke the list. Add a local secret token (header or query
      param, generated on first run and shown once) **plus** an
      Origin/Referer check against `127.0.0.1` so cross-origin pages can't
      post to it (CSRF).
- [x] **Stop leaking internals in errors.** app.py:261 returns the raw
      exception text to the client — hostnames, internal paths, whatever
      `requests` grumbled about. Log the detail server-side; return a
      generic message + upstream status code. (This is the backend half of
      the "smarter error messages" usability item.)
- [x] **CDN supply chain.** The page loads leaflet 1.9.4 +
      leaflet.markercluster 1.5.3 from unpkg and hls.js 1.5.13 from
      jsdelivr with no `integrity` (index.html:8–9, 242–244). For a
      local-only app the clean fix is to **vendor the files into
      `/static`** and load them locally. Fallback: add SRI hashes.
- [x] **Basic security headers.** Nothing is set today. Add
      `X-Content-Type-Options: nosniff`, a `Referrer-Policy`, and a CSP.
      CSP note: the map tiles and (until vendored) CDN scripts are remote,
      and there's inline JS — a first pass will need `unsafe-inline` or a
      refactor to external scripts. Worth it for nosniff at minimum.
- [x] **`data:` URIs in playlists.** `rewrite_m3u8` happily rewrites
      `data:` segment URLs (app.py:164). Harmless today, but skip or reject
      non-http(s) segment schemes when rewriting.
- [ ] *(already done, do NOT change)* Loopback-only bind, atomic
      `stations.json` writes via tmp+rename (app.py:59), BOM-tolerant JSON
      load, per-URL Referer derivation (app.py:32). These are the good
      parts; leave them alone.

---

### Suggested order if you actually do any of this

1. Security #1 (allowlist the proxy) — it subsumes most of the risk.
2. Security #4 (error leak) — five lines, removes the gross part.
3. Rate limiting #1 + #2 — small, and the app gets boring under load.
4. Usability, in whatever order brings vibes.
