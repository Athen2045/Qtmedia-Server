# Qtmedia CLI Context Snapshot

**Verified:** 2026-10-18
**Current phase:** Standalone CLI maintenance and desktop sidecar integration.

## Completed

- The CLI is isolated under `Qtmedia/` with its own package, tests,
  benchmarks, documentation, and runtime data.
- The CLI package owns terminal search, source adapters, direct downloads,
  cancellation, and the local search cache.
- The desktop-facing service boundary is being developed under
  `src/qtmedia/desktop_service/` with focused tests.
- Retired messaging-bot code and deployment references were removed from the
  workspace; the CLI does not depend on them.
- Rechecked the SpankBang downloader path against the current yt-dlp package.
  The venv has yt-dlp 2026.08.19, yt-dlp-ejs 0.8.0, and curl-cffi 0.15.0;
  the SpankBang options resolve to the upstream-recommended `chrome`
  impersonation target.
- Added local `.env` loading to the launcher and configured Firefox
  profile cookies with the installed Firefox 156.0.1 user-agent for SpankBang
  challenge requests. The profile is configured by its actual directory path
  because yt-dlp could not resolve Firefox's friendly profile name. The `.env`
  file is ignored and contains no copied cookies.
- 2026-10-09: Added `[tool.ruff] src = ["src"]` to `pyproject.toml` so Ruff
  treats `qtmedia` as first-party. This clears the five I001 import-order
  errors that had failed CI lint since 2026-08-23. Verified: `ruff check
  Qtmedia` passes; pytest 120/121 locally, the one failure
  (`test_ydl_options_uses_opt_in_firefox_cookies_for_spankbang`) is caused by
  the local `.env` cookie-profile setting and does not occur in CI.

- 2026-10-11: SpankBang mirror and block handling (shared with the app).
  `sources/spankbang.py` gains `SPANKBANG_MIRROR_HOSTS` (`spankbang.party`)
  and `canonical_spankbang_url`; the desktop policy and CLI `download_video`
  rewrite mirror links to `spankbang.com` so yt-dlp's SpankBang extractor
  handles them. `desktop_service/ytdlp_errors.py` adds `is_source_blocked`
  (HTTP 403 or Cloudflare challenge in the error chain) and the
  `source_blocked` code, used by inspection and `download_media`. Diagnosis:
  on the user's VPN, Cloudflare serves a managed challenge to every
  fingerprint, so the block itself still needs another exit IP or the
  opt-in cookie mode. Verified: pytest 183 passed (1 known `.env` failure),
  Ruff and compileall clean; live inspect returns `source_blocked`.
  Files: `sources/spankbang.py`, `download/engine.py`,
  `desktop_service/{policy,inspection,download,ytdlp_errors}.py`,
  `tests/test_desktop_service.py`, `tests/test_downloader.py`.

- 2026-10-11: NoodleMagazine adapter (CLI search + desktop allowlist).
  Desktop `DesktopAdapter("NoodleMagazine", "noodlemagazine.com",
  ^/watch/-?\d+_\d+$)`; CLI `SiteAdapter` searching
  `noodlemagazine.com/video/{query}`, scoped to `#list_videos` (the page also
  lists other users' recently watched videos). New optional
  `SiteAdapter.title_selector` reads the card's `[data-video-title-text]`
  instead of the link text, which starts with "HD 1.21M 54:53". Desktop
  `_display_title` turns form-encoded titles ("Best+pmv+teen") into spaces
  when there are two or more joins. yt-dlp's own NoodleMagazine extractor
  does the extraction; no impersonation needed. Verified live on the user's
  VPN: search returns 20 clean titles; `/watch/-226552677_456244963`
  inspects 144p-1080p MP4 + audio, and a 360p desktop download saved
  H.264/AAC, 17:13, 112 MB with artwork in 21 s (test file deleted).
  pytest 189 passed (1 known `.env` failure), Ruff, compileall,
  `git diff --check` clean. Files: `desktop_service/adapters.py`,
  `desktop_service/inspection.py`, `search/engine.py`,
  `tests/test_desktop_service.py`, `tests/test_search.py`,
  `tests/test_downloader.py`.

- 2026-10-11: Desktop Firefox cookie mode (`desktop_service/browser_cookies.py`).
  With `QTMEDIA_COOKIES_BROWSER=firefox` (set by the app's Settings ->
  Network -> Browser cookies), adapters marked `browser_cookies=True`
  (SpankBang only) get yt-dlp `cookiesfrombrowser` for the most recently used
  Firefox profile (newest `cookies.sqlite`), that profile's exact user agent
  (major version from `compatibility.ini`; Cloudflare binds `cf_clearance` to
  IP + UA), a `firefox` impersonation target, and `cachedir: False`. No
  readable profile -> stable `cookies_unavailable`. `site_ydl_options(url)`
  now builds impersonation for both inspection and download. Other sites
  never receive the cookies. The CLI's own `.env` cookie mode is unchanged
  (its UA there is stale: Firefox is now 157). Verified live on the user's
  VPN: SpankBang (and the `.party` link) inspect 720p/480p/240p and a 240p
  download saved H.264/AAC 4:24 with artwork (test file deleted). pytest 198
  passed (1 known `.env` failure), Ruff, compileall clean. Files:
  `desktop_service/{browser_cookies,adapters,inspection,download}.py`,
  `tests/test_browser_cookies.py`.

- 2026-10-18: Adapter batch from yt-dlp's supported list.
  Desktop allowlist (`desktop_service/adapters.py`): XNXX, RedTube, RedGifs,
  EMPFlix, MovieFap, ThisVid, and the Txxx network (HClips, HDZog, HotMovs,
  InPorn, PrivateHomeClips, TubePornClassic, Txxx, Upornia, VJAV, VXXX,
  VoyeurHit; `.tube` mirrors via the new `DesktopAdapter.aliases`). CLI
  search (`search/engine.py`): XNXX, RedTube, EMPFlix, MovieFap, ThisVid
  (each returned 20 clean results live); RedGifs and Txxx sites render with
  JavaScript, so they are direct-link only. Inspection now treats a format
  with no codec, height or audio details but a video extension as a muxed
  video (Txxx's only format, `hq.mp4`), offered as "Video MP4" only when no
  labelled height exists (hides XNXX's duplicate low/high files).
  Not added, broken in yt-dlp 2026.08.19 and nightly 2026.10.10: Beeg (API
  no longer returns streams; site IDs also carry a "-0" prefix the API
  rejects), Rule34Video (download-link markup changed; links need the page
  session), 4tube/PornTube/PornerBros/Fux (site moved to a JS app; Cloudflare
  challenges Chrome fingerprints but not Firefox).
  Live on the user's VPN: all 23 domains inspect; downloads verified for
  RedGifs, XNXX, EMPFlix, MovieFap, ThisVid, HClips (H.264/AAC, full
  durations, files deleted). RedTube (and existing YouPorn) media URLs answer
  410 Gone on this VPN (Aylo CDN rejects the signed links; time window is
  valid), and yt-dlp then skips every HLS fragment for minutes before
  "downloaded file is empty". pytest 233 passed (1 known `.env`), Ruff,
  compileall clean. Files: `desktop_service/{adapters,inspection}.py`,
  `search/engine.py`, `tests/test_{desktop_service,downloader,search}.py`.

## Next concrete action

Continue the QtmediaApp sidecar work. If SpankBang still returns 403 outside
the app's current network path, configure same-browser cookies and a matching
user agent; the upstream site issue remains open.

## Open decisions or blockers

- Keep CLI commands and terminal behavior backward compatible.
- The complete packaged desktop sidecar build remains to be verified.

## Relevant files

- `Qtmedia/src/qtmedia/`
- `Qtmedia/tests/`
- `Qtmedia/benchmarks/`
- `Qtmedia/src/qtmedia/desktop_service/`
- `Qtmedia/tests/test_desktop_service.py`
- `QtmediaApp/`

## Verification

The SpankBang verification pass is complete. `pytest -q tests/test_search.py
tests/test_downloader.py` passed (45 tests), Ruff passed, compileall passed,
and `git diff --check` reported no whitespace errors. No package update was
available from the configured package index.
