# QtmediaApp Context Snapshot

**Last reviewed:** 2026-10-18

**Current phase:** Cleanup and optimisation pass on branch `Development`
(baseline committed as `62a26b6`). Pro UI + music player build with a bundled
Deno runtime is installed from a fresh NSIS installer and verified end to
end. Priority order agreed with the user on
2026-10-10: (1) Deno + installer ✔, (2) app-owned adapter list ✔ (+ Eporner, DoH, proxy ✔), (3) app in CI ✔ (runs locally; needs a push), (4) yt-dlp updates + FFmpeg pin ✔,
(5) clean file names + truthful progress ✔ (names clean on disk since
2026-10-17), (6) video player ✔ (2026-10-10). Next steps in this area need a
new decision from the user.

Older entries (2026-09-15 to 2026-10-13) and the superseded 2026-09 release
notes are in `context-archive.md`; read them only when the history matters.

## 2026-10-18 Build cache cleanup

- `src-tauri/target/debug` had grown to ~26 GB (deps 14 GB, incremental
  9 GB); removed with `cargo clean --profile dev` (30.5 GiB, 23,514 files).
  `target/release` (installers in `bundle/`) and `binaries/` were kept.
- `Cargo.toml`: `[profile.dev.package."*"] debug = false`, so dependencies
  build without debug info in dev; the app crate keeps full debug info.
  Manifest verified with `cargo metadata --locked`; the next `cargo test` or
  `desktop:dev` recompiles from scratch once.

## 2026-10-18 Minimal scrollbars and matching drop-downs

User asked for minimal, matching scrollbars and drop-downs in every section.
- **Drop-downs:** all native `<select>`s (Video sort; Settings: Secure DNS,
  Browser cookies, yt-dlp channel, audio device/mode/rate) use
  `appearance: base-select` (WebView2 here is 155; needs Chromium 135+,
  older engines fall back to the native list). Closed: field-coloured
  button with a small chevron that flips when open (sort menus keep their
  quiet text style and own chevron). Open list: `--bg-pop` panel, 10px radius,
  hairline border, shadow, fade-in; rows 30px with an accent hover and a
  check on the chosen option. No markup or test changes; keyboard and
  accessibility stay native. Removed the old `appearance: none` and option
  colours on `.sort-menu`.
- **Scrollbars:** one `::-webkit-scrollbar` style for the whole app: 10px
  gutter, 4px rounded thumb at 14% white (28%/36% on hover/drag), no track
  or arrows. Lyrics and Up Next stay hidden.
- **Verified:** headless Brave (155) with scrollbars shown: Settings list open
  with hover, Sort list, thin thumb on a scrolled page. Vitest 190 passed;
  tsc clean. Captures in `artifacts/2026-10-18-dropdowns/`. Installer
  rebuilt with everything above (the release CSS minifier rejected
  `::picker(select):popover-open` inside `@starting-style`; it is now
  `::picker(select)`). Nothing committed.

## 2026-10-18 Up Next: move songs above the playing one; smoother resizing

From the user's test of the installed build: control bar, window moving and
everything else fine; resizing "not butter smooth"; Up Next could not place a
song above the playing one.
- **Up Next (`components/Player.tsx`):** lists the whole queue; played songs
  are dimmed ("Played") above the playing one, which is scrolled near the top
  when Up Next opens or the song changes. Every row drags anywhere (and
  Alt+Up/Down); the playing song keeps playing (moveInQueue). A song dropped
  above the playing one counts as played; it won't play next.
- **Resizing:** measured in headless Brave while resizing step by step:
  style+layout under 1ms per frame and paint/raster under 3ms on every page,
  with or without the blur effects, so the page is not the bottleneck; the
  remaining stutter is WebView2 catching up with a frameless window. Done:
  window `backgroundColor` #050505 in `tauri.conf.json` (no white flash at
  the moving edge) and `lib/resizeHint.ts` (html.is-resizing for 180ms after
  the last resize event; CSS drops all transitions meanwhile, so nothing
  trails the edge). Nothing on the Rust side runs per resize.
- **Verified:** Vitest 190 passed (Up Next test now drags above the playing
  song; new resizeHint test), tsc clean, capabilities tests pass. Headless
  check: dragging the last song above the playing one keeps Glasshouse
  playing. Installer rebuilt (02:10). Nothing committed.

## 2026-10-18 Test build

Engine rebuilt with PyInstaller (its sources had changed since the last
binary; `build-sidecar.ps1` stops early under Windows PowerShell 5.1 because
PyInstaller logs to stderr, so PyInstaller was run directly) and copied to
`src-tauri/binaries`. `pnpm desktop:build --bundles nsis` succeeded:
`src-tauri/target/release/bundle/nsis/Qtmedia_0.1.0_x64-setup.exe`. Not
installed; the user is testing it. Nothing committed.

## 2026-10-18 Cleanup pass 2: library scan, shared loads, file splits, archive

Continues pass 1 (both uncommitted).
- **Library scan (`sidecar/.../library.py`):** `scan_library` lists each
  folder once with `os.scandir` (Windows listings carry size/mtime),
  resolves the root and media folder once, and reads `artwork/` into a set
  instead of up to four `is_file` calls per file. Symlinks, or a media
  folder that resolves elsewhere, still go through `confined_path`.
  3,000 synthetic files: 1,151 ms → 40 ms per scan. It runs on every
  Video/Music/Files visit and artwork reload. +2 tests.
- **Shared loads (`lib/library.ts`):** `loadLibrary` (renames, then list)
  and `currentLibrary`, which joins a load already running; the player's
  queue restore uses it, so startup scans once instead of twice.
  `useLibrary` starts from the last list for the same `refreshToken`, so a
  page opened again shows its items at once while refreshing (a library
  change moves the token, so it never shows another library's list). +2 tests.
- **Splits (public paths unchanged):** `audio/engine.rs` (1,689 → 1,019
  lines, control state machine) + `audio/engine/pipeline.rs` (Feeder,
  Renderer, gain helpers) + `audio/engine/threads.rs` (threaded driver,
  MMCSS boost); `VideoOverlay.tsx` 553 → 412 with `lib/videoPrefs.ts`,
  `lib/playableSource.ts` and `useSubtitles` in `lib/subtitles.ts`;
  `lib/player.tsx` 576 → 527 with `lib/savedPlayer.ts`.
- **This file:** 1,893 → 428 lines; history before 2026-10-17 and the
  2026-09 release notes moved unchanged to `context-archive.md`.
- **Sidecar ruff config:** `[tool.ruff] src = ["src"]` in
  `sidecar/pyproject.toml`; without it import sorting depended on the
  folder ruff ran from (root vs sidecar disagreed).
- **Dead code:** survey in `docs/cleanup/2026-10-18-dead-code.md` (dead:
  `newestFirst`, `main_window`, empty root `src/` and `tests/`; test-only
  and unused CLI search helpers; over-exported frontend symbols). The dead
  items are removed (`newestFirst` in `lib/library.ts`, `main_window` in
  `commands.rs`, root `src/`, `tests/`, `__pycache__/`); the rest is still
  to decide. After removal: clippy and fmt clean, `cargo test` passed,
  Vitest 189, tsc clean.
- **Verification:** Vitest 189 passed; `tsc -b` clean (also with
  `--noUnusedLocals --noUnusedParameters`); `vite build` OK; clippy and
  fmt clean; `cargo test` all passed; ruff clean on Qtmedia and sidecar
  from root, `QtmediaApp/` and `sidecar/`; sidecar + desktop-service
  pytest 149 passed, 1 failed (`test_stdout_guard`, needs `qtmedia`
  installed in the venv, as in pass 1); `git diff --check` clean.
  Not tried in the desktop app.
- **Next:** try the app (`desktop:dev`): page switches, startup queue
  restore, synced lyrics, music playback after the engine split; then
  decide on the test-only and unused CLI items in the dead-code list.
- **Blockers:** none.

## 2026-10-18 Cleanup pass 1: lyrics re-render, clippy, sidecar ruff

User asked for code cleanup and optimisation. `cargo clippy` is now
installed; `ruff` runs from any shell through wrappers in `~/bin`
(`ruff`, `ruff.cmd`) that call `Qtmedia/.venv/Scripts/ruff.exe`.
Nothing committed.
- **Lyrics (`components/Lyrics.tsx`):** the synced view kept the smoothed
  position in state and set it on every animation frame, so the whole
  line list re-rendered ~60 times a second while playing. `useActiveLine`
  now works out the line inside the frame loop and keeps only its index
  in state, so the list renders when the line changes. Position/nudge
  updates use a layout effect so the old line never paints first.
  New test: the line advances between position updates while playing.
- **Clippy (`audio/engine.rs`):** `map_err(decode_code)`; `FeedCommand`
  boxes `Start(Feeder)` and `SetNext(NextTrack)` (the enum was ≥1416 bytes
  per message). Clippy `--all-targets` clean.
- **Sidecar ruff:** imports sorted (entrypoint, three tests); the two
  deliberate `except Exception` blocks in `qtmedia_engine/engine.py` get
  `noqa: BLE001` with reasons. CI runs ruff only on `Qtmedia/`.
- **Verification:** Vitest 187 passed; `tsc -b` clean; `cargo test` all
  passed; clippy and `cargo fmt --check` clean; ruff clean (Qtmedia and
  sidecar); sidecar + desktop-service pytest 147 passed, 1 failed:
  `test_stdout_guard` runs `python -I`, which needs `qtmedia` installed in
  the venv (it is not; run with `PYTHONPATH`); `git diff --check` clean.
  Not tried in the desktop app.
- **Next:** measure how often `list_library` runs (engine scan, durations,
  covers, loudness each call) and cache it if needed; consider splitting
  `audio/engine.rs`, `VideoOverlay.tsx` and `lib/player.tsx`; move older
  entries in this file to an archive.
- **Blockers:** none.

## 2026-10-18 Video settings icon redrawn as a cog

The bar's Settings icon (a circle with eight short strokes) read as a
sun/brightness control. `gear` in `components/Icon.tsx` is now an 8-tooth
cog outline with a centre hole, checked at 20, 34 and 96px. Vitest and tsc
passed. Nothing committed.

## 2026-10-18 Simpler video controls: one bar, one settings menu, same size in full screen

User asked to declutter the video player (stable volume, subtitles,
autoplay and start over had piled up as chips) and to stop the controls
growing in full screen. Mockups in `design/2026-10-18-video-controls/`
were approved with: keep ±10 s in the bar, drop picture-in-picture, keep
Speed in the settings menu. Nothing committed.
- **Cause of the big full-screen controls:** Video.js's packaged skin raises
  its scale unit up to 1.75x in full screen on displays 1920px and wider
  (documented behaviour). The packaged skin also can't take extra items.
- **Now:** `VideoOverlay` uses `VideoPlayer` + `Container` with our own
  `components/VideoControls.tsx` built from Video.js parts (PlayButton,
  SeekButton, MuteButton + VolumeSlider, Time, TimeSlider with preview,
  FullscreenButton, Controls, plus the skin's Hotkey and Gesture set: Space/K,
  M, F, C, arrows, J/L, 0-9, < >, click to play, double-click sides to skip
  and centre for full screen). `skin.css` is no longer imported. All sizes
  are fixed px in `app.css` ("Video player controls" section): bar 880x52,
  20px icons, 12px text in a window and in full screen (measured both).
- **Bar:** Previous · −10 · Play · +10 · Next (navigation only when there
  is a list) | volume (slider slides out on hover) · time · seek | CC (only
  when the video has subtitles; underline when on) · Settings · Full screen.
- **Settings menu:** Stable volume and Autoplay next switches
  (menuitemcheckbox), Subtitles page (Off, tracks, "Add subtitle file…",
  the picture-subtitles note), Speed page (0.5 to 2x). Esc steps back or
  closes the menu without closing the player; the controls stay visible
  while it is open.
- **Title row:** Close and title only. "Resumed at … · Start over" and
  "Subtitles added." are a small note above the bar that fades with the
  controls; the resume note also goes after 6 s.
- **Tests:** `VideoOverlay.test.tsx` stands in for the Video.js parts and
  opens the menu for Stable volume/Autoplay/subtitles; new tests for CC and
  the Subtitles page, Speed and Esc, and the resume note fading. Vitest 186
  passed; tsc clean. Headless Brave check of the real Video.js parts: bar
  880x52 in both modes, menu pages, Esc behaviour, no page errors.
  Captures in `artifacts/2026-10-18-video-controls/`.
- **Next:** try it with real videos with subtitles in the desktop app.
- **Blockers:** none.

## 2026-10-17 Responsive scaling across window sizes and snap layouts

User asked to improve scaling when the window is resized or snapped.
Checked every section (Home, Video, Music, Files, Settings, Music playing,
Now Playing, video player) at 680x460, 720x520, 960x540, 1920x1080 and
2560x1440 in headless Brave. Nothing committed.
- **Before:** the minimum window (960x640) blocked Windows quarter snaps;
  at narrow widths the Files toolbar ran under the window buttons; Music
  covers grew huge in small windows; at large sizes covers, Now Playing art
  and lyrics stayed small.
- **Changes:** `tauri.conf.json` minimum is now 680x460. `app.css` gets a
  "Fluid scaling" section at the end: toolbars are size containers, so the
  song/video count hides first, then "New Playlist" and "Open Folder" turn
  icon-only (labels are `.btn-label` spans; buttons keep aria-label and a
  tooltip) and segmented filters tighten; search fields shrink to 112px.
  Grids scale (`cover-grid` tiles clamp(120px, 11vw, 220px), 112px in short
  windows; `video-grid` clamp(200px, 17vw, 360px)). Home search widens to
  820px. Now Playing scales cover (150 to 520px from viewport height and
  width), title, artist, lyrics (19 to 42px), progress width and spacing.
- **Not done:** no global zoom; at 2560x1440 with 100% Windows scaling the
  chrome stays at its normal pixel size (Windows display scaling covers
  that). CSS `zoom` was avoided because it can skew pointer maths (drag to
  reorder, Video.js).
- **Verification:** Vitest 183 passed; tsc clean; build OK;
  `cargo test --test capabilities` passed; no element overflowed sideways
  at any size. Contact sheets in `artifacts/2026-10-17-responsive/`.
- **Next:** try Windows snap layouts (halves and quarters) in the desktop
  app; the new minimum applies after restarting `desktop:dev`.
- **Blockers:** none.

## 2026-10-19 Bug review: Private folder fixes

User asked for a check for bugs. Five confirmed and fixed:
1. **Vault index lost updates (data loss):** `Vault::add` loaded the index
   before minutes of encryption and saved its stale copy; parallel moves or
   a delete/restore during one dropped items (encrypted file kept, original
   deleted, item gone). `vault.rs` now has a process-wide `INDEX_LOCK`;
   add encrypts first, then reloads + saves under the lock; restore (whole)
   and delete run under it (`remove_item`). Test: 8 parallel moves + a
   delete keep exactly the right items.
2. **Missed move events:** `VaultView` re-subscribed on every library
   reload (new `retry`/`titles` each time; async listen gap), so the next
   video's `added` could be lost (row stuck on Encrypting). One listener
   per vault now, latest values via refs. Test: rerenders keep one
   subscription and still handle events.
3. **Originals in use silently kept:** deletion errors were ignored; on
   Windows an open file (cover grab, conversion, other player) stays.
   `remove_with_retry` (~2 s) and `vault-added.originalKept` → notice to
   delete it from Files. Windows test holds a file without delete sharing.
4. **Cover race:** the cover job saved `artwork/<title>.jpg` even if the
   video was moved/deleted while ffmpeg ran; it now re-checks the video.
5. **Private video fallback:** the player offered "Open in default
   player" for encrypted files; hidden for `vault/` paths.
- Minor, left as is: no cancel for a running move; a move fails if the
  same video's preparation is cancelled by closing the player on it; the
  subtitle cache is never pruned and holds subtitle text of moved videos;
  a saved device that is a Hands-Free endpoint shows as "Disconnected"
  (playback still redirects); `durations` holds its cache lock while
  measuring.
- **Verified:** Rust all passing (vault 9), Vitest 197, fmt, `tsc -b`,
  `git diff --check`; installer rebuilt and installed, app starts.

## 2026-10-19 Private folder (encrypted video vault)

User asked for a password-protected folder in the Video player; chose an
encrypted vault that locks on close or after 10 minutes idle. Spec:
`docs/superpowers/specs/2026-10-19-private-video-vault-design.md`.
- **Dependencies (new, exact pins):** `aes-gcm =0.10.3`, `argon2 =0.5.3`,
  `zeroize =1.8.1` (RustCrypto; lockfile updated).
- **`src-tauri/src/vault.rs` (new):** `<library>/vault/` — `vault.json`
  (Argon2id 64 MiB/3/1 + salt, data key wrapped with AES-256-GCM),
  `index.qv` (encrypted item list), `<32 hex>.qv` videos and `.cover`s in
  64 KiB AES-256-GCM chunks (nonce = prefix ‖ index, header as AAD:
  reorder/truncate/tamper fail). `VaultReader::read_range` decrypts only
  the chunks a range needs. create/unlock/change_password (re-wrap only),
  add/restore (free name, cover back to artwork)/delete. Timestamps whole
  seconds (serde_json float round trip is not exact; a test was flaky).
- **`src-tauri/src/vault_commands.rs` (new):** `VaultSession` (key in
  memory, per library; `lock_if_idle`), auto-lock thread (20 s checks, 10
  min idle → `vault-locked`), lock on library switch (`commands.rs`).
  Commands `vault_status/create/unlock/lock/change_password/items/cover/
  restore/delete/add`. `vault_add` job: make playable via the preparer
  (direct, prepared copy, or wait for conversion; `Preparer::is_running`
  added), encrypt video + cover, then delete the original, cover,
  subtitle files and prepared copy permanently (not Recycle Bin); events
  `vault-progress/added/failed/done`.
- **Streaming:** `media.rs` `serve_bytes` (shared range logic; `serve_path`
  now uses it), `vault_request` (strict `vault/<32 hex>.mp4|m4v|webm`),
  `serve_vault`; `lib.rs` route serves only while unlocked (403 locked).
- **UI:** Video page "Private" tile → `components/VaultView.tsx` (create
  with confirm + no-recovery warning, unlock, grid with decrypted covers,
  Add videos sheet with "removed for good" note, live progress, move back
  to library, delete-for-good confirm, change password, Lock; returns to
  the unlock form on `vault-locked`). Vault items play in the normal
  player as `vault/<id>.<ext>` (`LibraryEntry.title`, `mediaTitle` uses
  it; `playableSource` streams vault paths directly). `App.tsx` closes a
  playing vault video on lock. CSS "Private folder" section in `app.css`.
- **Live (installed build, generated 12 s test clip, removed after):**
  create → move in 0.5 s (title, duration, cover kept; original and cover
  gone; vault files have no title or `ftyp` text) → plays from the vault
  with seeking → Lock → list refused (`vault_locked`), `<video>` load
  fails → wrong password message → unlock → restore (H.264/AAC 12 s
  intact, cover back). Test vault, clip and resume key deleted; the
  user's library has no vault until they create one. Not exercised live:
  the 10-minute idle lock (unit-tested) and a large file / conversion
  path.
- **Tests:** Rust vault 7 (passwords, nothing readable on disk, ranges,
  tamper/truncate/swap/wrong key, restore/delete, session idle lock,
  streaming + strict names), media 9 still pass, full suite passing;
  Vitest 195 (VaultView 5); fmt, `tsc -b`, `git diff --check` clean.
- **Limits (stated in spec):** no subtitles inside the vault; deleted
  plaintext may physically remain on SSDs; forgotten password = loss.

## 2026-10-17 Surround downmix, lossy-source label, loudness levelling

- **Downmix (`convert.rs`):** `stereo_downmix` for 3–8 channels in FLAC/WAVE
  order: centre and surrounds at −3 dB, LFE dropped (ITU-R BS.775 / Dolby
  Lo/Ro), each side normalised so full-scale input never passes full
  scale. `map_channels` uses it for surround → stereo (it used to keep
  only FL/FR, dropping vocals). No surround file in the library; unit
  tested.
- **Lossy source:** engine (`Qtmedia/.../download.py`, `song_tags.py`)
  records the fetched stream's `acodec`/`abr` from the progress hook and
  writes `SOURCE_CODEC`/`SOURCE_BITRATE` into FLACs made from lossy
  codecs (opus, aac, vorbis, mp3, ac3, eac3). `lyrics.rs` `TrackInfo`
  gains `lossy_source`: "Opus 160 kbps" from those tags, or "unknown"
  for FFmpeg-written (`ENCODER=Lavf…`) 24-bit 44.1/48 kHz FLACs (every
  older download; 16-bit and ≥88.2 kHz FLACs are taken as lossless).
  `LossySourceChip` ("Lossy source", tooltip explains) in the player bar
  and Now Playing. Live: Skyfall shows it. Engine rebuilt (PyInstaller).
- **Levelling:** `src-tauri/src/loudness.rs` (new): ffmpeg `ebur128`
  integrated loudness + true peak, cached per file
  (`<app local data>/loudness.json`), measured one at a time in the
  background from `list_library`; `level_gain` targets −14 LUFS (YouTube/
  Spotify) and caps boosts at −1 dBTP; ≤ −70 LUFS (silence/too short) →
  unchanged. Engine: `Leveler` (path → gain) passed to `AudioEngine::spawn`
  / `ManualEngine::with_leveler`; each `Track` keeps its level, applied in
  its own `Converter` (`set_level`) so gapless joins switch exactly;
  never in strict exclusive (no software volume) or with `levelling`
  off; levelled exclusive output reports `volume_levelling`. Bit-copy
  path now requires gain and level exactly 1.0 (a boost was ignored
  before). `AudioPreference.levelling` (default on, older files on);
  Settings → Audio "Volume levelling" switch. Live: all 21 songs measured
  in ~30 s; they are −11.4 to −5.5 LUFS with true peaks above 0 dBTP, so
  levelling turns them down 2.6–8.5 dB. (−16 LUFS was tried first: 4.6–
  10.5 dB quieter, too quiet.)
- **Tests:** Rust audio_output +1 (downmix), lyrics +1 (lossy source,
  real ffmpeg), loudness 4, audio_engine +2 (levelled scale, strict/off
  stay bit-perfect), all passing; Qtmedia pytest 204 (+ known Firefox
  test), ruff clean; Vitest 183; fmt, `tsc -b`, `git diff --check` clean.
  `examples/audio_probe.rs` updated for the new `spawn` argument.

## 2026-10-17 Bluetooth audio: HFP lockout, headroom/limiter, MMCSS, lyrics delay

User asked for five Bluetooth items. Findings and changes:
1. **WASAPI resampling:** already bypassed — shared mode opens in the
   device mix format with `autoconvert: false` and Qtmedia resamples
   (rubato FFT). The Bluetooth link rate is set by the headset/codec; no
   app can change it. Live on the AirBass: FLAC 48 kHz/24 → Shared 48 kHz
   (no resampling at all).
2. **Hands-Free lockout (new):** `output/mod.rs` `Endpoint` +
   `avoid_hands_free`; `device.rs` reads `PKEY_Device_ContainerId`,
   `find_device` swaps a Hands-Free endpoint (explicit or Windows default)
   for the same headset's A2DP endpoint, else `OutputError::HandsFreeOnly`
   (`audio_hands_free_only`, not `audio_unavailable`, so no webview
   fallback). `list_devices` hides Hands-Free endpoints. Live: setting
   the device to `Headset (AirBass…)` ({4583f3a5…}) played on "Headphones
   (AirBass Headphone)"; setting restored.
3. **Latency:** video A/V sync is Chromium's (it paces frames on the
   device clock Windows reports); the music engine has no picture. Lyrics
   could run ahead by the headset's own delay, which no API reports: new
   `lib/bluetoothDelay.ts` (`qtmedia.audio.bluetoothDelayMs`, 0–500, default
   0) and Settings → Audio "Lyrics delay on Bluetooth" (Bluetooth outputs
   only); `PositionedLyrics` subtracts it on Bluetooth.
4. **Headroom (new):** `convert.rs` `soft_limit` (transparent ≤ −1 dBFS,
   tanh knee to full scale, never above ±1.0) on every float path;
   `Converter::set_bluetooth` adds 1 dB headroom (`BLUETOOTH_HEADROOM`) for
   Bluetooth. The bit-perfect integer copy never passes through it (test).
5. **Threads:** decode/render/control threads + lock-free ring existed; new
   `boost_render_thread` registers the render thread with MMCSS "Pro
   Audio" (`windows` feature `Win32_System_Threading`, same version). Live:
   render thread at priority 24 (TimeCritical) while playing.
- **Tests:** Rust audio_output +4 (limiter, overs/headroom, bit-perfect
  untouched, HFP redirect); Vitest 181 (+2 delay). All Rust tests pass;
  fmt, `tsc -b`, `git diff --check` clean. Installer rebuilt and
  installed; volume/player state restored after the live checks.

## 2026-10-17 Subtitles, generated video covers, Continue watching removed

- **Continue watching row removed (user: "videos got duplicated"):** no
  files were duplicated on disk; the row repeated started videos above the
  grid. Each video now shows once; started ones keep the progress bar.
- **Subtitles** (spec `docs/superpowers/specs/2026-10-17-video-subtitles-design.md`,
  git-ignored): `src-tauri/src/subtitles.rs` (new) finds `video/<stem>.srt|vtt`
  and `<stem>.<label>.srt|vtt` (2–3 letter label = language), and text
  streams inside the video via ffprobe (subrip/ass/ssa/mov_text/webvtt);
  picture streams (PGS/DVD) are counted as `unsupported`. Titles that are
  web addresses or shared by every stream (release-site ads) are dropped.
  Everything becomes WebVTT (SRT `,`→`.`, `<font>` removed, UTF-16/BOM
  handled, 4 MB cap) in `<app local data>/subtitle-cache/<16 hex>.vtt`;
  embedded streams are extracted in one ffmpeg pass. Served as
  `qtmedia://localhost/subtitles/<16 hex>.vtt` (`media.rs`
  `subtitle_name`/`serve_subtitle`, strict names; CSP unchanged).
  Commands `read_subtitles`, `add_subtitles` (file picker, copies as
  `<stem>.<picked name>.<ext>`). Deleting a video also trashes its
  subtitle files unless another video shares the stem (`removal.rs`).
  `Preparer::ffmpeg()` added.
- **Player:** `<track kind="subtitles">` per track inside Video.js
  `<Video>`; Video.js's CC button (appears only with tracks), settings →
  captions submenu and `C` key do on/off and choice. `lib/subtitles.ts`:
  language names (ISO 639-2 → BCP 47 + `Intl.DisplayNames`), numbered
  repeats ("English (2)"), `pickTrack`, choice in `qtmedia.video.subtitles`
  (same language, else label, else first). The overlay applies the choice
  per video, records picks on `textTracks` `change`, and turns off a second
  track the webview enabled by itself. Header: "Add subtitles"/"Subtitles"
  button and a note when only picture subtitles exist; `::cue` styled.
- **Generated covers:** `src-tauri/src/covers.rs` (new). `list_library`
  starts a background job for videos without a cover: ffmpeg at a
  pseudo-random but fixed point (15–60 % by path hash; start if that fails),
  `thumbnail=48` picks a representative frame, HDR (PQ/HLG via ffprobe) is
  tone-mapped (zscale + hable), saved as `artwork/<stem>.jpg` (never
  replacing one). `CoverJobs` stops duplicate/failed retries per session;
  `library-artwork` event → `bridge.subscribeArtwork` → `useLibrary`
  reloads.
- **Live with the user's `Lanterns…HEVC-PSA.mkv` (4K HDR10+/DV, 53 min):**
  cover generated and tone-mapped (snowy street at night); 36 embedded
  SubRip tracks extracted in 1.05 s (34 ms cached), ad titles dropped,
  labels English, English (2), Bulgarian…; remembered English applied;
  807 cues, "No witnesses." shown at 10:58; CC off/on saved; remux to MP4
  for playback. Not exercised live: the Add subtitles file picker (native
  dialog), Video.js captions submenu selection (feeds from the same list).
- **Tests:** Vitest 179; Rust subtitles 10, covers 5 (real ffmpeg for
  embedded extraction and frame grab), all passing; fmt, `tsc -b`,
  `git diff --check` clean. Subtitle choice left as English on.

## 2026-10-17 Player quality pass (durations, renders, memory, volume, seek) + features

User asked for items 1–5 of the quality review, then the missing features.
- **1 Durations (`src-tauri/src/durations.rs`, new):** `list_library` fills
  `durationSeconds` (the engine scan never did): symphonia for songs, the
  bundled ffprobe for videos and header-less MP3s, 4 workers, cached
  (including "unknown") by `root|path|size|mtime` in `<app local
  data>/durations.json`, pruned per root. `Preparer::ffprobe()` added.
  Live: 32/32 measured, first listing 718 ms, then 20 ms.
- **2 Renders (`lib/player.tsx`):** position left `PlayerState`; a
  per-provider store + `usePlayerPosition()` (useSyncExternalStore). Only
  `SeekBar` and `PositionedLyrics` (in `Player.tsx`) re-render on ticks.
- **3 Memory:** `qtmedia.player.v1` keeps volume, mute, shuffle, repeat,
  queue/ordered (≤5000), index and position (every 5 s, on state change,
  on `pagehide`). Restores paused and cued (`loadedPathRef`); Play loads at
  the saved position; seek while cued only moves the start. On mount the
  restored queue is checked against the library (following the rename log)
  and gone songs dropped. Live: Skyfall restored at 0:30 / 4:46, resumed
  there.
- **4 Volume:** `volumeGain(v) = v³` for both backends (50 % ≈ −18 dB).
- **5 Seek:** `Slider live={false}` holds the drag locally and seeks once
  on pointer up; keys seek at once.
- **Video:** `resume.ts` gains `list()` and a `qtmedia-resume` window event;
  Video page shows "Continue watching" (≤12, newest first; plays within
  that row) and a progress bar on every card. Overlay: Autoplay toggle
  (`qtmedia.video.autoplay`, on by default; only with neighbours), "Up
  next in 5" card with Play now/Cancel (Esc cancels before closing);
  video volume/mute remembered (`qtmedia.video.volume`). Live: row and
  bars correct, card counted down and advanced, Cancel worked.
- **Music:** `playNext` / `addToQueue` (move duplicates, keep the current
  song; start playing when idle); the song row button is now "More
  options for …" (⋯ icon) with Play Next / Add to Queue above the playlist
  items. `usePlayerShortcuts`: Space, Ctrl+←/→, Ctrl+↑/↓ app-wide, off
  while typing or with a video open; Now Playing's own Space handler
  removed.
- **Tests:** Vitest 171 (persistence, render isolation, seek on release,
  cubic gain, queue insertion, shortcuts, continue watching, autoplay,
  video volume, song menu); Rust durations 3 new, all passing; fmt,
  `tsc -b` clean.
- **Note:** saved positions for videos not opened by the agent changed
  between runs (someone was using the app); explains the earlier "page
  reset" and missing key. Test state removed; the app was force-closed
  several times and reopened at the end.
- **Still open (bigger, need design):** subtitles, audio-track choice,
  music loudness normalisation, streaming preparation of MKV/AVI.

## 2026-10-17 Video next/previous; media keys follow the open video

User asked for next/previous in the video player and the music player, and
whether a doubly linked list is used. Music already had Previous/Next (player
bar and Now Playing; `lib/player.tsx` queue = array + index, prev restarts
past 3 s) — unchanged. Neither player uses a linked list (answered in chat:
array + index fits shuffle, drag reorder and immutable React state).
- **Video (`components/VideoOverlay.tsx`):** optional `navigation`
  (`previous`, `next`, `onPrevious`, `onNext`). Prev/Next buttons flank the
  ±10 s buttons (`.video-skip__side`, `.video-skip__nav` in `app.css`),
  titled "Previous: <title> (Shift+P)", disabled at the ends, hidden for one
  video. Shift+N / Shift+P. Saves the position before moving. The overlay
  is no longer keyed by path: per-video state resets on path change, the old
  video is paused and unloaded (`removeAttribute("src")` + `load()`), and
  `switchingRef` ignores its late pause/ended until the next metadata loads.
  The player stays mounted while the next source is checked, so full screen
  is kept; `usePlayableSource` resets to `checking` per path.
- **App/pages:** `onPlayVideo(entry, list?)`; Video grid passes its items,
  Files its visible videos, Home just the entry. `App` holds
  `{list, index}` and builds `navigation`.
- **Media keys:** `PlayerValue.setVideoActive`; while a video is open the
  music player stops registering media-session handlers and the overlay
  registers play/pause/next/previous (title as metadata); on close it
  clears them and music registers again. Before this, ⏭ during a video
  started the next song.
- **Tests:** Vitest 154 (overlay 5 new, App list stepping, Video page list
  order, media-key handover); `tsc -b` clean.
- **Installed-app check:** Video page → Previous/Next titles and disabled
  ends correct; Next and Shift+P switch videos and save the position
  (Kianna 40 s saved, resumed at 40); a video with no saved position starts
  at 0 after a far-along one; full screen kept across Next and Previous;
  media-session title follows the video and clears on close; Files opens
  with Files' order (Milf wars: prev "I love big tits pmv", next "Bridgette
  b pmv"). Positions created by testing were removed; Nonstop and Best pmv
  moved ~2 s forward from test playback.
- **Open observation:** once during testing the page reset to Home mid
  script and the renamed Interstellar resume key was missing afterwards.
  Neither reproduced (full-screen, Next chain through Interstellar all kept
  it; key restored at 88→90.8 s). The one plausible code path (old video's
  late `ended` clearing the new path) is now guarded and tested.
- **Files:** `frontend/src/{App.tsx,App.test.tsx,app.css}`,
  `components/{VideoOverlay,VideoOverlay.test,MediaPages,MediaPages.test,FilesPage}.tsx`,
  `lib/player.tsx`; spec `docs/superpowers/specs/2026-10-10-video-player-design.md`
  (note: `docs/` is git-ignored, so specs stay local).

## 2026-10-17 Clean file names on disk

User asked for saved names without the ` [media-<id>]` tag, keeping covers,
resume and playlists working. Spec:
`docs/superpowers/specs/2026-10-17-clean-file-names-design.md`.
- **Engine (`Qtmedia/.../desktop_service/download.py`):** `clean_stem(title)`
  (sanitized, 120 chars, Windows device names get `_`). Temp files keep
  `safe_stem` = `Title [media-id]` (job isolation and cleanup); the final
  move takes `_free_stem`: free across `audio/`, `video/`, `artwork/` (any
  extension, case-insensitive), else ` (2)`… under a process lock. The cover
  follows the media stem.
- **Rust (`src-tauri/src/names.rs`, new):** `tidy_library` renames every
  tagged group (media + `.lrc` + cover) that contains real audio/video to the
  untagged stem (numbered on clash; orphan lyrics/covers left alone), rolls a
  group back if any part fails, never overwrites, carries the prepared
  playback copy to its new `cache_name`. Renames are logged per library root
  in `<app data>/Qtmedia/renames.json` after each group. Runs in `setup`
  before the engine starts and in `switch_library`. New command
  `library_renames` (`commands.rs`, registered in `lib.rs`).
- **UI:** `lib/renames.ts` (`renamer` follows chains, `applyRenames`);
  `playlistStore.remap` (dedupes, keeps `updatedAt`) and
  `remapResumePositions` (newer wins). Applied by `AppShell` on mount and on
  `libraryRevision`, and by `useLibrary` before listing. Display stripping
  of the tag in `lib/library.ts` stays for files added other ways.
- **Live (installed build, user's library):** first launch renamed 83 files
  (11 videos, 21 songs with lyrics and covers, 30 covers); no tagged media
  left; 30/32 entries have covers (the 2 without never had one); 5 orphan
  `.lrc` files untouched. Resume keys remapped while on Home (7 of 7 for
  existing videos; 7 others belong to deleted videos). Interstellar opened
  "Resumed at 1:26" from `video/Interstellar … (HDR - 4K - 5.1).mp4`;
  Skyfall's lyrics and cover resolve. The user had no playlists, so playlist
  remap is verified by tests only. A new download was not run live (would add
  a file to the user's library); covered by engine tests. Native audio
  playback of a renamed song not exercised (same path resolution as lyrics).
- **Verified:** Vitest 147 passed, `tsc -b` clean; Rust all passed (names 7
  new), `cargo fmt --check` clean, build warning-free; Qtmedia pytest 200
  passed + the known machine-dependent Firefox cookie test; sidecar 47/48
  (known stdout-guard with the CLI venv; needs `PYTHONPATH=src;../../Qtmedia/src`);
  ruff clean; `git diff --check` clean. Pytest needs
  `-p no:cacheprovider --basetemp <scratch>` in the sandbox. Engine rebuilt
  with PyInstaller directly; `pnpm desktop:build --bundles nsis` (108 MB)
  installed silently.
- **Files:** `Qtmedia/src/qtmedia/desktop_service/download.py`,
  `Qtmedia/tests/test_desktop_{service,flac}.py`, `src-tauri/src/{names,commands,lib}.rs`,
  `src-tauri/tests/names.rs`, `frontend/src/App.tsx`, `App.test.tsx`,
  `lib/{renames,renames.test,playlists,resume,bridge,library,library.test}.ts`,
  `components/MediaPages.test.tsx`, `setup.md`, the spec.
- **Next:** commit/push still awaiting the user's decision (this and the
  2026-10-13 audio work are both uncommitted).

## Architecture and privacy boundaries

Tauri 2.11.5 owns the window, application-data root, settings preference,
sidecar lifecycle, request correlation, path validation, confined artwork
reads, and OS open operations. React 19.2.8/Vite renders the interface. One
long-lived PyInstaller `qtmedia-engine` process communicates through JSON Lines
on stdin/stdout; no Python localhost server is used.

The desktop service remains separate from the CLI-facing download function.
The current explicit desktop policy covers the seven original providers plus
YouTube. Inspection sessions and provider selectors are opaque and in memory.
Raw URLs are accepted only by `inspect` and are not returned or persisted.
Rust capabilities expose neither arbitrary shell access nor unrestricted
frontend opener permissions. Artwork uses a bounded Rust data-URL transport
allowed by the narrow CSP.

Library layout:

```text
<active root>/
├── audio/
├── video/
├── artwork/
└── temp/
```

## Known blockers and decisions

- Earlier agent-run YouTube extraction on this Windows host reached policy but
  failed before extraction with WinError 10013. Restricted agent networking
  means this does not prove an installed-app firewall problem; reproduce in the
  new build before prescribing endpoint-security changes.
- New CLI adapters are not automatically trusted by the desktop app. Add each
  one explicitly to the desktop policy after reviewing its URL/path rules.
- Switching download locations does not migrate old media in this version.
- Apple signing/notarization and Windows code signing require external
  credentials.

## Maintenance rule

Read this file first and update it after every meaningful work session or
change affecting scope, architecture, dependencies, file layout, tests,
verification, blockers, or the next action.
