# QtmediaApp Context Snapshot

**Last reviewed:** 2026-10-17

**Current phase:** Pro UI + music player build with a bundled Deno runtime is
installed from a fresh NSIS installer and verified end to end on branch
`Development`; not yet committed. Priority order agreed with the user on
2026-10-10: (1) Deno + installer ✔, (2) app-owned adapter list ✔ (+ Eporner, DoH, proxy ✔), (3) app in CI ✔ (runs locally; needs a push), (4) yt-dlp updates + FFmpeg pin ✔,
(5) clean file names + truthful progress ✔ (names clean on disk since
2026-10-17), (6) video player ✔ (2026-10-10). Next steps in this area need a
new decision from the user.

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

## 2026-10-13 Exclusive mode gives the device back on pause

User report: play music, pause, then a YouTube video in a browser has no
sound until the app is closed and the tab refreshed. Cause: in Exclusive
mode the engine kept the device for 30 s after pause; Windows silences every
other app meanwhile, and a browser that failed to open audio does not retry
until the tab reloads.
- **Engine (`src/audio/engine.rs`):** `pause()` calls `release()` at once
  when the open stream is exclusive (shared mode keeps the 30 s release; it
  never blocks other apps). `seek()` while paused and released only moves
  `released_at`, so the device is not retaken; resume reopens it at that
  position (about 0.1 s before sound).
- **Tests (`tests/audio_engine.rs`):** new
  `an_exclusive_pause_gives_the_device_back_at_once` (release on pause, seek
  stays released, resume reopens at the new position); the 30 s test now runs
  in shared mode (`a_paused_shared_engine_releases_the_device_after_30_seconds`).
- **Verified:** `cargo test --locked` all pass (engine 19), `cargo fmt
  --check` clean (clippy not installed), `git diff --check` clean. Rebuilt
  `pnpm desktop:build --bundles nsis` and installed silently. In the
  installed app over DevTools: with the output temporarily set to the Realtek
  speakers (exclusive, 24-bit 48 kHz) pause emits `deviceReleased`
  immediately, a seek while paused opens nothing, resume reopens; the user's
  audio settings were restored afterwards. On the AirBass headphones every
  track falls back to shared (`exclusive_bits_unsupported`), and a second
  Chromium audio client kept running both while playing and after pause.
- **Real second client on the speakers (follow-up, AirBass disconnected):**
  a scratch WASAPI probe opening the default device in shared mode (as a
  browser does) got `0x8889000A` (device in use) while Qtmedia played
  exclusive, **OK after pause**, and in-use again after resume.
- **Bluetooth detection fixed:** the AirBass reported `transport: "wired"`.
  Windows' own A2DP driver records `BTHENUM\{0000110B-…}` in the endpoint's
  device path (`{b3f8fa53-…},2`); only offloading drivers (Intel Smart Sound)
  fill the Bluetooth path (`…,39`) that was read. `output/mod.rs` adds
  `endpoint_transport(bluetooth_path, device_path, adapter)` (Bluetooth if
  either path or the adapter says so); `output/device.rs` reads both keys.
  Test `bluetooth_is_found_in_either_endpoint_path` in
  `tests/audio_output.rs`. Speakers still report wired. Not yet checked live
  with the AirBass connected (it was disconnected); the classifier was
  checked against its registry values (endpoint `{5aef2813-…}`).
- **Docs:** engine plan's exclusive-ownership note updated.
- **Live AirBass check (reconnected):** `audio_devices` lists
  "Headphones (AirBass Headphone)" as `bluetooth` (speakers `wired`);
  playback signal path carries `transport: "bluetooth"` (shared,
  `exclusive_format_unsupported`). Player chip: "Bluetooth · not lossless".
- **Tooltip fix:** `frontend/src/lib/signalPath.ts` `signalReason` now gives
  the Bluetooth sentence for any Bluetooth device (it only did for
  `shared_mode`, so this case said "refused exclusive mode for this
  format"); test added in `nativePlayer.test.tsx`. Vitest 141 passed, tsc
  clean. Rebuilt and reinstalled; the Now Playing tooltip reads "Bluetooth
  re-compresses audio, so it is never lossless."
- **Next:** commit/push still awaiting the user's decision.
- **Files (follow-up):** `src-tauri/src/audio/output/{mod,device}.rs`,
  `src-tauri/tests/audio_output.rs`. Rebuilt and reinstalled again; all Rust
  tests pass, fmt and `git diff --check` clean.

## 2026-10-11 Browser cookies (Firefox) for SpankBang's anti-bot check

User asked for the cookie mode proposed after the VPN `source_blocked` fix.
- **Rust:** `settings.rs` adds `CookieSource { Off, Firefox }` as
  `NetworkPreference.cookies` (`#[serde(default)]`, old files load Off);
  `engine_network_env` passes `QTMEDIA_COOKIES_BROWSER=firefox`;
  `set_network_settings` takes optional `cookies` (omitted keeps the saved
  value) and reuses the guarded engine restart. Firefox only: Chrome/Edge
  app-bound encryption on Windows stops other programs reading cookies.
- **UI:** Settings -> Network -> "Browser cookies" (Off / Firefox) beside
  Secure DNS and Proxy, applied with the same Apply button; locked during
  jobs. Home's `source_blocked` message now points to this setting; new
  `cookies_unavailable` message. Bridge/mock updated.
- **Engine:** see `Qtmedia/context.md` (`browser_cookies.py`). Cookies stay
  in memory, only SpankBang requests use them, with Firefox's exact UA and
  TLS fingerprint.
- **Verified:** live on the user's VPN with Firefox cookies, SpankBang
  inspects and downloads (240p H.264/AAC, artwork). Vitest 141 passed, tsc
  clean, Rust tests all pass, `cargo fmt --check` clean (clippy not installed
  locally), Qtmedia pytest 198 passed (1 known `.env`), sidecar 47/48 (known
  stdout-guard run with the CLI venv), `git diff --check` clean.
- **Rebuilt and installed (16:48):** PyInstaller engine (run directly;
  `build-sidecar.ps1` under Windows PowerShell 5.1 stops on PyInstaller's
  stderr logging because of `ErrorActionPreference = Stop`), then
  `pnpm desktop:build --bundles nsis` (113 MB) installed silently over
  `%LOCALAPPDATA%\Qtmedia`. Packaged engine via `scripts/probe-engine.py`
  on the VPN: SpankBang `.party` link -> `source_blocked` with cookies off,
  720p/480p/240p with `QTMEDIA_COOKIES_BROWSER=firefox`; NoodleMagazine up to
  1080p. Not driven: the Settings row in the running window (covered by
  Vitest).
- **Files:** `src-tauri/src/{settings,sidecar,commands}.rs`,
  `src-tauri/tests/{network_settings,audio_settings}.rs`,
  `frontend/src/lib/{bridge,mockBridge}.ts`, `DesktopSession.tsx`,
  `components/{SettingsPage,HomePage}.tsx` + tests,
  `sidecar/src/qtmedia_engine/engine.py`.

## 2026-10-11 NoodleMagazine added to the app's adapter list

User asked for a NoodleMagazine adapter and a test of
`noodlemagazine.com/watch/-226552677_456244963`. Added to the reviewed
desktop allowlist (`Qtmedia/src/qtmedia/desktop_service/adapters.py`,
`/watch/<owner>_<id>` pages only) and to CLI search; details in
`Qtmedia/context.md`. Works on the user's VPN with no impersonation: inspect
lists 1080p-144p MP4 + audio, title "Best pmv teen hot very hot 4k" (the site
sends it "+"-joined); a real 360p download through `download_media` saved a
valid H.264/AAC file with artwork. No frontend or sidecar changes needed.

## 2026-10-11 SpankBang on VPN: real error message, spankbang.party links

User on a VPN got "The source could not be reached right now." for
`spankbang.com/6ghm6/video/...`, and noted `spankbang.party` is the same site.
- **Cause:** SpankBang's Cloudflare answers the VPN exit IP with a managed
  challenge (`403`, `cf-mitigated: challenge`) for every curl_cffi
  fingerprint (chrome, safari, firefox, edge) on both domains; yt-dlp
  2026.08.19 is the latest release. The app mapped that 403 to
  `provider_unavailable`. `spankbang.party` was rejected as
  `unsupported_source`, and yt-dlp's SpankBang extractor only matches
  `spankbang.com` anyway.
- **Fix:** new error code `source_blocked` (HTTP 403 / Cloudflare challenge
  anywhere in the yt-dlp error chain) for inspect and download; sidecar
  passes it through; Home shows "The site blocked this connection with an
  anti-bot check. This is common on VPNs...". `spankbang.party` links are
  rewritten to `spankbang.com` by the policy before extraction.
- **Not fixed (needs a decision):** the block itself. Options: another VPN
  server / split-tunnel, or an opt-in browser-cookie mode for the app
  (`cf_clearance` is bound to the IP and user agent, so the browser must use
  the same VPN). The CLI already has the cookie mode; the app does not.
- **Verified:** live inspect of both URLs on the VPN returns
  `source_blocked`; Qtmedia pytest 183 passed (1 known `.env` failure),
  Ruff clean for `Qtmedia/`, compileall ok, HomePage Vitest 11 passed, tsc
  clean, `git diff --check` clean. Sidecar pytest 47/48: the stdout-guard
  subprocess test fails only when run with the CLI venv (`python -I`).
- **Files:** `sidecar/src/qtmedia_engine/engine.py`,
  `frontend/src/components/HomePage.tsx`, `HomePage.test.tsx`,
  `frontend/src/lib/DesktopSession.tsx`; shared code in `Qtmedia/` (see its
  context.md).

## 2026-10-11 No "Lyrics from your .lrc file" label

User asked not to show "Lyrics from your .lrc file" in the music player.
`Credit` in `components/Lyrics.tsx` now renders nothing for synced lyrics
from a local `.lrc` (plain ones still say "Not time-synced"); LRCLIB results
keep "Lyrics from LRCLIB". Since found lyrics are saved next to the song,
most songs show no label after their first lookup. Test updated
(`MediaPages.test.tsx` asserts no "Lyrics from" text); Vitest 131 passed (Lyrics.test now matches "Not time-synced" case-insensitively), tsc
clean.

## 2026-10-11 Video player flickered when reaching for the X

User reported the video overlay "acts buggy" when the mouse moves to the X.
- **Cause (app.css, from the earlier minimal-overlay change):** the title row
  hid itself whenever the Video.js controls were hidden. Pointing at the row
  counts as leaving the player, so the controls hid, the row hid and became
  click-through, the pointer then landed on the player, the controls showed,
  the row showed... a loop. Measured in headless Brave: the row's opacity
  jumped between 0 and 0.8 several times a second with the pointer at rest
  on the X.
- **Fix:** the row (and the window buttons) stay while pointed at or while
  something in them has keyboard focus (`:has(:focus-visible)`; plain focus
  is not enough because the X is focused when the player opens).
- **Verified (headless, real mouse input):** steady at full opacity for 4 s
  on the X; after moving to the middle and resting, the controls and row
  hide after about 1.5 s; one click on the X closes the player. Vitest
  131 passed; tsc clean.
- **Blockers:** none.

## 2026-10-11 Window could not be dragged: missing drag permission

User reported the app could not be moved around the screen.
- **Root cause:** the frameless window relies on `data-tauri-drag-region`,
  which calls the `start_dragging` window command. The capability granted
  only `core:default`, which does not include it, so every drag was
  silently refused. `capabilities/default.json` now also grants
  `core:window:allow-start-dragging` and
  `core:window:allow-internal-toggle-maximize` (double-click a drag area to
  maximize/restore). Test `frameless_window_can_be_dragged_by_its_drag_regions`
  in `tests/capabilities.rs` guards it.
- **More places to grab:** Tauri drags only when the pressed element itself
  has the attribute, so toolbar titles, counts and badges, the sidebar logo
  and the video title now pass presses through (`pointer-events: none`).
  The sidebar Q logo is a drag handle; Now Playing has a 56px drag strip
  along the top; Home (no toolbar) lifts the top 44px strip above the page.
- **Verification:** `cargo test --test capabilities` 4 passed (the build also
  validates permission names); Vitest 131 passed; tsc clean;
  `desktop:dev` compiled and launched. A scripted drag test was abandoned:
  the Qtmedia window was behind other windows and could not be brought
  forward, so synthetic input was unreliable. The user should confirm by
  dragging the top bar.
- **Blockers:** none.

## 2026-10-11 Sidebar polish, new nav icons, window controls on one title line

User asked to polish the sidebar, update the icons, and check the window
controls (minimise/maximise/close) against each section. Nothing committed.
- **Window controls:** they sat at y = 18px while every page title and its
  tools sit at y = 28px (56px toolbar), and Now Playing's close button sat
  at 37px. Now everything shares the 28px line: controls are 10px from the
  top/right as rounded 40x36 buttons (Close keeps the red hover); Now
  Playing's close is at top 9px; the video player's title row is 56px.
  Over Now Playing and the video they turn white (`:has()`), and over the
  video they fade with the player controls (they reappear on hover).
- **Sidebar:** subtle graphite gradient and top highlight, a hairline under
  the Q mark, 40x40 buttons with 6px spacing, a press effect, a 3px accent
  marker on the inner edge for the current page, and a small custom
  tooltip after a 450ms hover (replaces the slow native `title`; the
  accessible names are unchanged). It still never expands.
- **Icons (`components/Icon.tsx`):** new Home, Video (screen + play instead
  of a film strip), Music, Files (folder with a tab line) and Settings
  (three sliders). Shapes marked `className="duo"` fill with the accent
  when the page is selected (white outline, purple fill).
- **Tests:** `Shell.test.tsx` updated for the tooltip; Vitest 131 passed, tsc
  clean, build OK, `git diff --check` clean. Captures (title line per
  section before/after, sidebar zooms) in `artifacts/2026-10-11-sidebar/`.
- **Next:** check in the desktop app (real window dragging around the
  controls, which keep their 134px drag-free corner).
- **Blockers:** none.

## 2026-10-11 UI polish: true ink black, player bar aligned with the sidebar, glass video controls

User asked: theme is not true ink black; check the navbar position against
the video and music players; make the video overlay aesthetic, minimal, with
a slightly opaque control bar. Done in `frontend/src/app.css` (+ theme-color
in `index.html`); no component logic changed; nothing committed.
- **Ink:** tokens are neutral now (no blue cast): `--bg #050505`,
  `--bg-raised #0c0c0d`, `--bg-pop #151516`, `--field #141415`,
  `--control #222224`/`#2c2c2f`, text greys `#a1a1a6`/`#6e6e73` (same as
  the sidebar). The sidebar keeps its graphite `#232325` (earlier request).
- **Player bar vs navbar:** the bar was a flush full-height slab beside a
  floating sidebar (bottom edges 10px apart, different surface). It is now a
  floating card like the sidebar: 10px from the window's right and bottom
  edges (same bottom line as the sidebar), radius 16, same border and
  shadow, 72px tall.
- **Video overlay:** the title row floats over the picture (video uses the
  full window) and fades out with the controls; the cursor hides when idle.
  The close button is a small glass circle. The Video.js bar (which used the
  96%-opaque popover colour) is now a centred glass strip, max 880px wide,
  22px from the bottom, `rgba(18,18,20,.46)` + blur 28px, a hairline border;
  white progress and thumb; a faint bottom shade instead of the heavy
  gradient. The ±10 s buttons are smaller (58px) glass circles.
- **Verification:** Vitest 131 passed, tsc clean, build OK, `git diff
  --check` clean. Headless Brave captures (1366x800, before/after) in
  `artifacts/2026-10-11-polish/`; the glass bar was checked over a
  colourful frame (the mock serves audio-only video).
- **Next:** check the overlay with a real video in the desktop app.
- **Blockers:** none.

## 2026-10-11 Motion always on, song-to-song backdrop crossfade, Up Next drag, playlists

User asked for: (1) disable reduce motion, (2) a fluid background transition
in Now Playing when the next song starts, (3) drag-to-move in Up Next, (4)
Create Playlist with user-added songs. All four done; nothing committed.
- **Motion:** every `prefers-reduced-motion` rule removed from `app.css`
  (Now Playing tilt/drift, lyrics, video overlay, skip buttons, search
  modes, the global kill switch) and the lyrics scroll always glides. This
  machine has Windows animation effects off, which had been disabling them.
- **Backdrop crossfade (`components/Player.tsx`):** `useSettledCover` keeps
  the previous cover until the next one has loaded (no placeholder flash);
  `Backdrop` stacks the new blurred layer over the old and fades it in over
  1.4 s (`np-backdrop-in`), dropping the old layer on animationend or a timer
  fallback. `--np-tint`/`--np-accent` are registered with `@property`, so the
  tint, progress fill and accents ease to the new colours too. The cover and
  glow fade/scale in per song. Also fixed: the cover's shadow painted over
  the title (positioned `.np-hero h2, p`).
- **Up Next drag:** `player.moveInQueue(from, to)` keeps the playing song
  playing wherever it lands (unshuffled it also becomes the order).
  `lib/useDragReorder.ts`: pointer-event drag with a 5 px threshold (clicks
  still play), rows slide aside, auto-scroll near edges, Esc cancels,
  Alt+Up/Down from the keyboard with focus kept, the playing row is pinned.
  Up Next now lists the whole rest of the queue (scrolls) with a grip on hover.
- **Playlists:** `lib/playlists.ts` (useSyncExternalStore over local storage
  `qtmedia.playlists.v1`; paths only, de-duplicated, names trimmed to 80
  chars, corrupt data ignored). `components/Playlists.tsx`: a Playlists
  shelf on Music (New Playlist tile + mosaic covers), the playlist page
  (Play, Shuffle, Add Songs, Rename, Delete with a confirm sheet, remove a
  song, drag to reorder, total length), the New Playlist / Add Songs sheet
  (name + searchable song picker; songs already in the list show "Added"),
  and a per-song "Add to Playlist" menu (portalled, keyboard arrows, New
  Playlist… preselects the song) with a "Added to …" toast. Toolbar has
  New Playlist.
- **Tests:** Vitest 122 (new: moveInQueue, Up Next keyboard + pointer drag,
  backdrop crossfade layers, create/add/play/remove/delete playlist,
  add without duplicates + rename, playlist store). `test/setup.ts` now gives
  each test an in-memory localStorage (Node's file-less global shadowed
  jsdom's). tsc clean; `git diff --check` clean. No Rust changes.
- **Visual check:** headless Brave against the dev mock (1366x800): sheet,
  playlist page, dragging, row menu above the player bar, Up Next drag
  (order verified after drop), and the purple→red backdrop fade mid-way and
  settled. Saved in `artifacts/2026-10-11-playlists/`.
- **Next:** try it in the desktop app with real songs; playlists are
  per-device (local storage), not yet exported or synced.
- **Blockers:** none.

## 2026-10-11 Video "Stable volume" (YouTube parity)

User heard a big difference between YouTube and the Qtmedia download of
youtu.be/onVhbeY7nLM (Interstellar docking scene, 4K). The download's audio is
the right stream: Opus 251 at about 130 kbps stereo, non-DRC, YouTube's best.
Measured with ebur128:
- Download (original mix): -16.6 LUFS integrated, LRA 13.5 LU, quiet
  passages -40 to -28 LUFS.
- YouTube "Stable volume" track (251-drc): -14.9 LUFS, LRA 7.3 LU, quiet
  passages lifted 10–15 dB.

YouTube's -14 LUFS normalisation does not apply, because the video is
quieter than that. So the difference was YouTube's Stable volume (DRC).
- **User chose** a playback-time toggle; files keep the original mix.
  `lib/stableVolume.ts`: `useStableVolume(video)` builds a Web Audio graph
  only once switched on (MediaElementSource → 2:1 compressor (threshold
  -30, knee 10) → +2 dB make-up → limiter at -1.5 dB), then only reconnects.
  The choice is remembered (`qtmedia.video.stableVolume`, default off). The
  "Stable volume" pill is in the video overlay's top bar (`aria-pressed`).
- **Tuning:** offline renders in Chromium (its compressor adds its own
  make-up gain). Tones at -50…-6 dBFS → +10.3/+10.3/+10.1/+8.4/+5.5/+2.6/
  -0.4 dB; peaks ≤ -0.8 dBFS.
- **CORS:** Web Audio needs CORS-clean media, so `<Video crossOrigin=
  "anonymous">` is set. The `qtmedia://` handler echoes
  `Access-Control-Allow-Origin` only for the app's own origins
  (`media::allowed_origin`: tauri.localhost, tauri://localhost, dev
  localhost:1420) with `Vary: Origin`.
- **Verified in the installed app** (output routed to a silent meter):
  Interstellar 40–46 s measured -28.1 dB RMS off → -21.3 dB on (+6.8 dB),
  peaks -10.9 → -6.7 dB. The video loaded with crossOrigin and the
  AudioContext was running. The test patch was removed by a reload, and
  stable volume was reset to off.
- **Native engine for video audio:** not used. It would need A/V sync
  between the webview's video clock and the Rust output, and it decodes only
  FLAC/MP3 (video audio is Opus/AAC/Dolby). Music keeps the engine.
- **Tests:** Vitest 138 (+1 stable-volume routing/persistence); Rust media
  9 (+1 CORS origin); tsc and fmt clean.

## 2026-10-11 Dolby / 5.1 in the video player

User asked whether the player supports Dolby 5.1. On this PC, WebView2
decodes Dolby Digital (AC-3) and Dolby Digital Plus (E-AC-3) 5.1 through the
Windows Dolby decoder. This was verified with real 5.1 AC-3/E-AC-3 MP4s in
the library (audio decoded, no errors). The output device is 2 channels
(laptop speakers / AirBass), so Windows downmixes 5.1 to stereo; a 5.1
system would get all channels as multichannel PCM. Browsers cannot bitstream
Dolby to a receiver.
- **Fixes to the preparer:** `playback::Support { dolby }`. The webview
  reports it (`canPlayType` for ec-3 and ac-3) through
  `prepare_playback(relativePath, dolby)`. With Dolby, AC-3/E-AC-3 are copied
  (MP4 direct, MKV remux) instead of converted. DTS/TrueHD (no webview
  decoder) are converted to **surround Opus**: mapping family 1 at 64 kbps
  per channel, with `aformat=channel_layouts=5.1/7.1/…`, because libopus
  rejects DTS's 5.1(side). Stereo stays 192k. `RECIPE_VERSION` is 2, so the
  old stereo-only copies are not reused.
- **Verified:** DTS 5.1 and TrueHD → 6-channel Opus 5.1 that WebView2
  decodes. Installed app: a 5.1 AC-3 MKV was planned "remux", played from
  the cache at 30 fps with 0 dropped frames and decoded audio. Test files
  and cache copies removed.
- **User's clip** (Top Gun: Maverick, youtu.be/WCtJ_EZQQBM, downloaded via
  Qtmedia): YouTube offers **stereo only** for it (Opus/AAC). The "Dolby 5.1"
  title refers to the uploader's source. The best video is 8K AV1 10-bit
  HDR10. In the app it plays directly at 7680×4048 and 24 fps with 0
  dropped frames. Its first ~4 s are digital silence (-91 dB), which is why
  little audio is decoded at the start. Qtmedia chose Opus 251 and skipped
  the DRC variants this video has.
- **Tests:** Rust playback 8 (+2) and the real-FFmpeg preparer 2; Vitest 137.

## 2026-10-11 Video formats: MKV, MOV, WebM, M4V, AVI + Import

User chose the FFmpeg layer over libVLC (plan
`docs/superpowers/plans/2026-10-11-video-formats.md`). libVLC would draw in
its own native window under the web UI and add about 100 MB.
- **Library:** `paths::VIDEO_EXTENSIONS` = mp4, m4v, mov, mkv, webm, avi (also
  `AUDIO_EXTENSIONS`). The sidecar scan, `qtmedia://` content types and
  artwork sharing on delete use them.
- **`src/playback.rs` (pure):** `parse_probe` (skips cover-art streams) and
  `plan`:
  - Direct: mp4/m4v with H.264/HEVC/VP9/AV1 + AAC/Opus/MP3/FLAC, or WebM.
  - Remux: fine codecs in another container.
  - Transcode: only the stream that needs it. 10-bit H.264, MPEG-2/4,
    ProRes and VP8 in MP4 re-encode video; AC-3/E-AC-3/DTS/PCM/Vorbis in MP4
    re-encode audio.

  Also `ffmpeg_args` (h264_nvenc p4 cq19, else libx264 veryfast crf18;
  libopus 192k stereo; `-tag:v hvc1`; faststart; `-progress pipe:1`),
  `cache_name` (FNV-1a over path, size, mtime and recipe), and
  `parse_progress`.
- **`src/preparer.rs`:** `prepare_playback` returns
  direct/ready/preparing; `cancel_playback`. The job thread runs ffmpeg with
  no console, tries NVENC then x264, writes `.part` then renames, prunes to
  20 GB oldest-first, and emits `playback-prepare` progress/ready/error. Jobs
  are cancelled on window destroy. `media::serve_playback` and
  `playback_name` handle the `/playback/<16hex>.mp4` route (strict, ranges).
- **Frontend:** `VideoOverlay` `usePlayableSource` shows "Checking",
  "Preparing for playback…" (remux) or "Converting for playback…" with a
  progress bar and Cancel, then plays the copy. Closing mid-way cancels the
  job; failures offer the default player.
- **Import:** `src/import.rs` + `import_media` (native multi-file picker;
  audio→`audio/`, video→`video/`; `.part` then rename; "Name (2)"; max 500;
  unsupported or failed files skipped). Files toolbar has an "Import" button
  with a result notice and refresh.
- **Verification:** real-FFmpeg test (`tests/preparer.rs`, run with
  `--include-ignored`): MOV remux → H.264/AAC, MKV AC-3 → H.264/Opus, AVI
  MPEG-4 → H.264 (NVENC)/MP3, MP4 direct, cache hit on the second request, no
  `.part` left. Installed app: a synthetic 1080p H.264 + AC-3 MKV in the
  library was listed, converted in under 1 s and played from the cache at
  1920×1080 with 0 dropped frames. The test file was recycled and its cache
  copy removed. Tests: Rust 140 passed (+2 ignored real-tool tests), Vitest
  137, sidecar 48, desktop Python 130; fmt, tsc and Ruff clean.
- **Known gap:** deleting a video leaves its prepared copy in the cache until
  pruning (20 GB cap). Subtitles and audio-track choice are out of scope.

## 2026-10-11 Video: real full screen, better audio; player choice research

User: a downloaded 4K video "does not feel 4K". Measured in the installed app:
the file is genuine 4K (VP9 3840×2160 60 fps, about 14 Mbps, SDR). WebView2
decoded every frame (60 fps, 0 dropped, hardware). The display is the limit:
the laptop panel is 1920×1200 at 125 %, and the player only used the window
(1709×960 px). HTML full screen did not enlarge the Tauri window.
- **Full screen:** Rust `window_set_fullscreen(fullscreen)` (registered in
  `lib.rs`), bridge `setFullscreen`. After the user pointed out two buttons,
  Video.js owns full screen: its own button, its "f" hotkey and its
  double-tap gesture. `VideoOverlay` listens for `fullscreenchange`, and when
  the full-screen element is inside the overlay it makes the app window full
  screen (and restores it on exit, close or unmount). The extra top-bar
  button, F and double-click handlers, icons and CSS were removed. Verified:
  one "Enter fullscreen" button; 1709×960 → 1920×1200 → back. Vitest 132.
- **Video audio:** video-only streams now pair with the best audio track by
  `_audio_rank` (usually Opus 251) as `<video>+<audio>/<video>+bestaudio`,
  instead of forcing `bestaudio[ext=m4a]` (AAC 128). That also fixes the
  known gap where sources without M4A audio failed. WebView2 plays Opus in
  MP4 with H.264, VP9 and AV1. Verified with a real download into a scratch
  library (deleted): H.264 + Opus 48 kHz in MP4.
- **WebView2 support on this machine:** H.264, VP9 (also 10-bit HDR), AV1,
  VP8 and HEVC; MP4 and WebM ("maybe" for MKV); AAC, Opus, MP3, FLAC. 4K60
  decode is smooth and power-efficient for VP9, AV1 and H.264.
- **Tests:** Vitest 133 (+2 full screen); Python desktop 130 (+1); Rust 128;
  tsc, fmt, Ruff and the diff check clean. Installer rebuilt and installed.

## 2026-10-11 Best lossy source for music downloads

User asked for the best lossy source when downloading music. Findings: on
YouTube and YouTube Music without Premium the best stream is already Opus 251
(~130–160 kbps); Qtmedia picked it for the tracks tested, as yt-dlp's
`bestaudio` does. The 256 kbps streams (AAC 141, Opus 774) need the user's
YouTube Premium login cookies; not added (cookies stay out of the app).
- **Ranking** (`desktop_service/inspection.py` `_audio_rank`): audio-only,
  then not DRC (`-drc` ids or "DRC" notes), then original language
  (`language_preference`), then the site's quality tier, then codec-weighted
  bitrate (`CODEC_EFFICIENCY`: Opus 1.4, Vorbis 1.15, AAC-LC 1.0, HE-AAC 0.7,
  MP3 0.85, lossless always first), then sample rate. Previously it used the
  raw bitrate only (AAC 129 could beat Opus 121).
- **MP3:** LAME V0 VBR (`preferredquality: "0"`) instead of 192 kbps CBR, to
  keep the second-generation loss smallest. The label now names the source
  like FLAC: "MP3 · from Opus 139 kbps" (`bitrateKbps` null). FLAC remains
  the no-further-loss option.
- **Follow-up (user: "go with the better choice"):** music is saved as **FLAC
  only**. `_available_formats` no longer offers the MP3 option, so Home's
  Audio list shows just "FLAC · from Opus N kbps" (Music mode already
  auto-picked FLAC). The MP3/V0 download path stays in `download.py`,
  unused. Tests were updated to expect FLAC only (129 passed).
- **Verified:** a real YouTube Music lookup and an MP3 download into a scratch
  library (not the user's; deleted afterwards). V0 averaged 266 kbps, and
  tags were written (Mona Lisa / Dominic Fike / Sunburn). Tests: desktop
  Python selection 129 (new ranking test; three 192 kbps assertions
  updated), Ruff clean. Engine exe and installer rebuilt and installed.

## 2026-10-11 Native audio engine Tasks 5–7 done (resumed by the user)

The user asked to resume the engine. Answered: no DAC is needed for lossless
(the laptop's Realtek is a DAC, and exclusive on it is bit-perfect).
Bluetooth (AirBass) is never lossless; the engine gives it only small gains
(one clean resample, gapless, a hands-free-profile warning, honest labels).
Wi-Fi speakers would need a network output (not built).
- **Task 5 (host):** `src/audio/service.rs` holds the lazily started engine
  and an endpoint watcher (`DeviceEventCallbacks`, debounced; `deviceChanged`
  with `fallback` when the chosen device is gone; the default device is used
  meanwhile, and the choice returns when the device does). It also builds
  the `audio-event` payloads (library-relative paths only; `signalPath` with
  device, transport and `volumeLocked`). `src/audio_commands.rs` holds
  `audio_play`, `audio_pause`, `audio_resume`, `audio_seek`, `audio_stop`,
  `audio_release`, `audio_set_volume`, `audio_set_next`, `audio_devices`,
  `audio_get_settings` and `audio_set_settings`; paths must be `audio/` in
  the library. `settings.rs` holds `AudioPreference` (`audio` in
  preferences.json, camelCase; kept across library/network saves;
  `save_audio` never replaces an unreadable file). Engine: `EngineSender`,
  `Command::DefaultDeviceChanged`, `reopen()` (stays released while
  long-paused), and `Announce` (seeks are quiet; reopen sends only
  `SignalPath`). The window close and `Destroyed` shut the engine down.
- **Task 6 (frontend):** `lib/audioBackend.ts` (native and webview backends;
  falls back to the webview on `audio_unavailable`); `player.tsx` uses it
  (`followingIndex`; an effect keeps the engine's next track in step with
  queue, repeat and reorder; `releaseDevice` is used when a video opens).
  `lib/signalPath.ts` gives the badge and reasons. Player bar chip ("Bit-perfect",
  "Bluetooth · not lossless", …). Volume slider is locked with "Bit-perfect:
  use your amplifier or DAC volume" in strict exclusive. Now Playing shows
  the signal path. Settings → Audio: output device (Windows default +
  devices, Bluetooth/Headset labels, disconnected device), Mode
  (Shared / Exclusive · bit-perfect), rate fallback, exclusive volume
  switch, and Bluetooth/hands-free notes.
- **Verification:** Rust 127 passed, warning-free; Vitest 131 (new
  `lib/nativePlayer.test.tsx` 8 + App video release); tsc and fmt clean.
  Installed app (07:xx): device list correct, `unsafe_path` for
  `video/` and traversal, muted native playback on the AirBass with
  position, pause, seek and stop. The chip and Now Playing show "FLAC 48 kHz ·
  24-bit → Shared 48 kHz · Headphones (AirBass Headphone)". Installer 107.9
  MB (+0.5 MB).
- **Follow-up (user request):** Now Playing no longer prints the path line
  ("FLAC … → Shared/Exclusive … · device") or the reason/volume lines; only
  the quality chip remains, with those details in its hover tooltip (same as
  the player bar chip). Unused `.np-signal__path/__why` styles removed.
  Vitest 131 passed; reinstalled and verified (muted): Now Playing shows
  "Shared" only.
- **Not done / deferred:** DAC checklist and loopback capture (no DAC);
  exclusive was not re-run through the UI (it would play loudly; it was
  verified with the probe on the Realtek in Tasks 3–4); Wi-Fi speaker
  output; Import music (offered). Not committed.

## 2026-10-11 Reliable lyrics (SpotiFLAC's LRCLIB cascade), song tags, Now Playing details

User asked to use lyricstify/api; advised against it (unmaintained since
2023, broken by Spotify's token change, needs a self-hosted Node server and
the user's Spotify `sp_dc` cookie). User then pointed to SpotiFLAC
(github.com/spotbye/SpotiFLAC, MIT): it uses LRCLIB only, with a matching
cascade. **Credit SpotiFLAC in the README/About later (user request);** the
code comment in `lib/lyrics.ts` names it. Go and the Spotify Web API were
considered and not needed (no lyrics there; a client secret would ship in
the app).
- **Root causes of unreliable lyrics:** title-only `?q=` search, no artist
  (the library had no tags), and `durationSeconds` was always null, so the
  duration check never ran.
- **Engine (Python):** `desktop_service/song_tags.py`: `song_tags(info)`
  takes track/artist(s)/album from yt-dlp (also "<Artist> - Topic"
  channels); `InspectedMedia.tags`; downloads write only title, artist and
  album with mutagen into MP3/FLAC, and only when music metadata exists
  (never a guessed artist, never a link). Verified: a YouTube Music result
  gives Mona Lisa / Dominic Fike / Sunburn / 186 s, and LRCLIB `/api/get`
  matches it in one request.
- **Host (Rust, `src/lyrics.rs`):** `read_track_info` (symphonia tags and
  real duration, audio only, confined) and `save_lyrics` (writes
  `<stem>.lrc` atomically, never replaces an existing file, 512 KB cap).
  Commands are registered in `lib.rs`. Fixtures `tagged.flac`/`tagged.mp3`
  (added to `scripts/make-audio-fixtures.ps1`).
- **Webview (`lib/lyrics.ts`):** the query comes from tags, else the file
  title split as "Artist - Title". `primaryArtist` keeps the lead artist
  (commas, &, ;, /, feat/ft). Steps: `/api/get` with album, then without
  album, then `/api/search` with artist + track, then title-only, then the
  simplified title. Synced lyrics must look complete (at least 4 lines; 8
  lines or ending past half the song); otherwise plain, then partial
  synced. `pickBest` adds +3 for the same track name, -5 for non-Latin names
  on a Latin title, and -1 for a placeholder album. A found result is saved
  next to the song with `[ti:]/[ar:]/[al:]` headers, so it is looked up
  once. Cache is `qtmedia.lyrics.v4`; 5xx/429/network errors are not cached.
- **Now Playing:** shows the title, then the artist (`.np-artist`), then the
  album (`.np-album`, small, spaced capitals), from tags, else the `.lrc`
  headers. Depth effect: a blurred cover glow behind the art, layered
  shadows, and a pointer tilt (±6-7°) while the backdrop drifts the other
  way. Under reduced motion (this machine) the tilt and drift are off; the
  glow and shadows stay. `useTrackInfo` caches per path, size and mtime.
- **Live (installed app, muted playback):** all 7 library songs have
  lyrics. Sunflower → Post Malone…; A Thousand Years → John Michael Howell;
  Annihilate and Self Love → Metro Boomin with the soundtrack album. A first
  pass picked a Japanese album name, "和" and "Unnamed" entries; the scoring
  fix removed them. The four `.lrc` files this session created were
  recycled and fetched again with headers. The user's own three `.lrc`
  files were untouched.
- **Tests:** Vitest 115 (new: cascade, lead artist, headers, clean-match
  choice, Now Playing artist/album); Rust 115 (`tests/lyrics.rs` +5); Python
  desktop selection 128 (+2 song tags); Ruff clean; tsc clean. Installer
  rebuilt and installed (06:3x).

## 2026-10-11 Synced lyrics in Now Playing; video play icon centred

User asked for lyrics animation in the Now Playing overlay, in the style of
github.com/Fizzy444/Stave (unlicensed, so patterns only; no code copied). The
user chose online lookup **always on** (with a Settings toggle).
- **Source order:** a local `.lrc` next to the song (Rust `read_lyrics` plus
  `src/lyrics.rs`: audio only, confined by `resolve_library_entry`, at most
  512 KB, BOM stripped) comes first. Otherwise the webview fetches
  `https://lrclib.net/api/search?q=<cleaned title>` (credentials omitted, no
  referrer). The best result is chosen by duration (±8 s, synced preferred).
  Hits and misses are cached in localStorage (misses for 7 days; 5xx errors
  not cached). Only the title is sent, because the library has no
  artist/album.
- **CSP:** `connect-src` adds exactly `https://lrclib.net`. The capabilities
  test now asserts that it is the only `https:` source.
- **UI** (`components/Lyrics.tsx`, `lib/lyrics.ts`):
  - The active line is bold and white; other lines fade and blur by distance
    (`--d`) and are slightly scaled.
  - The view auto-centres the active line, pausing for 2.5 s after a manual
    scroll. Clicking a line seeks to it, gaps show "• • •", and a ±0.5 s
    timing nudge appears on hover beside the credit line.
  - Position is interpolated between `timeupdate` events with rAF, so line
    changes land on time.
  - Plain (unsynced) lyrics, loading, and "No lyrics found" states. Now
    Playing opens on lyrics and falls back to Up Next when there are none; a
    corner button toggles between them.
- **Settings:** a "Find lyrics online" switch (Privacy group); the copy now
  says files are never uploaded.
- **Reduced motion** (this Windows machine has animation effects off): lyrics
  keep their depth and crossfade; only the scaling and smooth scroll are
  dropped.
- **Mock bridge:** sample fictional `.lrc` for Night Drive, timed to the tone.
- **Tests:** `src/test/setup.ts` stubs `fetch` to reject, so tests never reach
  the network.
- **Video play icon:** removed an extra 2px nudge (the triangle path is already
  offset). It is now optically centred (centroid +0.25px, measured). The Music
  cover play button got the same fix.
- **Verification:** Vitest 104 passed (new `lib/lyrics.test.ts`,
  `Lyrics.test.tsx`, and a Now Playing lyrics test), `tsc -b` clean, build
  passes. Rust: all 16 suites pass, including the new `tests/lyrics.rs` and
  the stricter CSP test; `cargo fmt --check` clean. Captured in the browser
  preview with and without reduced motion. Not verified: a real LRCLIB match
  for a real downloaded song inside the desktop app.

## 2026-10-10 Ink-black theme and calmer sidebar

- **Theme:** the stage tokens in `app.css` moved from graphite to ink black:
  `--bg #0b0b0f`, raised `#131318`, popover `#18181f`, field `#1a1a21`, control
  `#272730`, player bar `#0e0e13`, separators at 7%/11% white, and slightly
  cooler text greys. `index.html` theme-color is `#0b0b0f`. At the user's
  request the sidebar is unchanged: it keeps `#232325`, and `.sidebar`
  re-declares the previous `--sep/--hover/--field/--text*` values locally.
  The accent and Now Playing are unchanged.
- **Sidebar is icon-only** (user: it popped open "whenever I got near it", then
  "no need to expand, the icons are more than enough"). The expansion was
  removed entirely: no hover or focus expansion, no labels, no wordmark. Each
  icon has a tooltip and an accessible name; the coming-soon dot is kept for
  future items.
- **Verification:** Vitest 88 passed (`Shell.test.tsx` covers the icon-only sidebar), `tsc -b` clean,
  build passes. Home, Files, Music, and Settings were captured with the mock
  bridge at 1366×768. Note: the other session's Home change now starts
  downloading straight after lookup, so the old format-list capture step no
  longer applies.

## 2026-10-10 Files multi-select and Delete (Recycle Bin)

User request: a select / select-all option and a delete option.
- **Files:** checkbox column, a header Select all (shows a partial state),
  Finder-style click / Ctrl-click / Shift-click, Ctrl+A, Esc to deselect, and
  Delete key. While items are selected, the toolbar swaps to "N selected ·
  Deselect · Delete" and the status bar shows the selected count and size.
  Actions apply only to selected items visible under the current filter or
  search. Delete opens a confirmation sheet (Cancel focused) and then moves
  files to the **Recycle Bin**; it never erases them. A failure is shown
  inline. Deleting the playing song stops the player. The list reloads.
- **Rust:** `delete_media(relative_paths)` in `commands.rs` plus
  `src/removal.rs`. It refuses during a library switch, accepts at most 2000
  paths, removes duplicates, and confirms every path with
  `resolve_library_entry` (only audio/video media in the active library;
  artwork, `temp/`, and escapes are refused and counted). It runs on a
  blocking thread. New dependency: `trash =5.2.9` (MIT, default features off
  apart from `coinit_apartmentthreaded`). Artwork shared by other entries is
  left in place.
- **Bridge:** optional `deleteMedia` (Delete is hidden when absent); the mock
  bridge implements it.
- **Verification:** Vitest 87 passed (5 new selection/delete tests), `tsc -b`
  clean, build passes. Rust: all suites pass, including 2 new
  `tests/removal.rs` tests that inject a remover so the real Recycle Bin is
  never touched; `cargo fmt --check` clean. `pnpm desktop:dev` was relaunched
  with the new command. Not verified by hand in the window: an actual
  Recycle Bin move.

## 2026-10-11 Priority step 4: yt-dlp updates + FFmpeg pin done

User chose the **update button** (not automatic, not rebuild-only) and the
yt-dlp exception to the 14-day rule (fixes are only useful while new).
- **Engine** (`sidecar/src/qtmedia_engine/ytdlp_update.py`): downloads the
  official `yt-dlp` zipimport release (bundles yt-dlp-ejs) from
  `yt-dlp/yt-dlp` (Stable) or `yt-dlp/yt-dlp-nightly-builds` (Nightly).
  `SHA2-256SUMS.sig` is verified in pure Python (OpenPGP v4, RSA, SHA-512)
  against the pinned key `AC0C BBE6 848D 6A87 3464 AF4E 57CF 6593 3B5A 7581`,
  then the file's SHA-256 against the signed sums, the archive's
  `yt_dlp/version.py` against the tag, and asset URLs must come from the
  channel's repo. Installed to `<app local data>/tools/yt-dlp/current`
  (atomic swap). At every start `activate()` re-verifies it and puts it ahead
  of the bundled copy only if newer; a broken update falls back to bundled.
  Protocol: `ytdlp_status` → `ytdlp_status {version, source, channel}`;
  `ytdlp_update {channel}` → `ytdlp_updated {status: updated|current,
  version, channel}` or `error {update_unavailable |
  update_verification_failed | update_failed}`.
- **Source changed:** `Qtmedia/.../desktop_service/ytdlp_errors.py`; an
  unexpected yt-dlp `ExtractorError` (not network, private, geo or sign-in)
  now reports `source_changed` from inspect and download; Home says "This
  site changed and yt-dlp needs an update…".
- **Host:** env `QTMEDIA_YTDLP_DIR`; commands `get_ytdlp_status`,
  `update_ytdlp(channel)` (refused while media work runs; restarts the engine
  after an update and returns what the new engine loaded).
- **UI:** Settings → "Media engine": yt-dlp version + Bundled/Updated badge,
  Stable/Nightly channel, "Check for update", outcome and error text.
- **FFmpeg:** `scripts/prepare-ffmpeg.ps1` now downloads gyan.dev 9.0.2
  essentials (released 2026-09-20) from `GyanD/codexffmpeg`, checks SHA-256
  `60f46726…a2047ba`, extracts only `ffmpeg.exe` and `ffprobe.exe` and checks
  their versions. `ffprobe` added to `externalBin` and the CI stand-ins;
  yt-dlp finds it next to ffmpeg (verified `probe_available`).
- **Verification:** real GitHub run: Stable reported current (2026.08.19);
  Nightly 2026.09.27.232945 installed in 3.8 s with the real signature; the
  rebuilt PyInstaller engine exe loads it (`source: updated`), and without
  the tools dir reports bundled; the frozen engine inspected a YouTube video
  with the update + Deno. Tests: sidecar + desktop CI selection 126 passed
  (20 new update tests incl. real-signature and tamper cases); Qtmedia 170
  passed + the known machine-dependent Firefox cookie test; Rust 107 passed,
  warning-free; Vitest Settings/Home 22 passed (5 new); Ruff (CI scope)
  clean; `git diff --check` clean.
- **Installer (2026-10-11 00:09):** after the lyrics session fixed its
  build, rebuilt the engine exe and `pnpm desktop:build --bundles nsis`
  (107 MB, 158 s); installed silently over `%LOCALAPPDATA%\Qtmedia`
  (`ffprobe.exe` 9.0.2 now beside `ffmpeg.exe`). Driven over the WebView2
  DevTools port: Settings showed 2026.08.19 · Bundled; Stable → "Already up
  to date"; Nightly → "Updated to 2026.09.27.232945. The media engine
  restarted." in 2.5 s (new engine processes), badge "Updated · Nightly";
  re-check → "Already up to date" in 0.7 s. The updated engine then
  inspected and downloaded a YouTube test video. That was a mistake: Video
  mode saves at once, and YouTube must stay out of the user's library. The
  .mp4 and its cover were moved to the Recycle Bin.
- **Fixed (user request):** Files Delete never removed the cover in
  `artwork/`. `removal.rs` now also moves `artwork/<stem>.{jpg,jpeg,png,webp}`
  to the Recycle Bin after a media file is removed, unless another
  `audio/<stem>.mp3|flac` or `video/<stem>.mp4` still exists (the same
  stem rule as the library scan). Covers resolve through
  `resolve_artwork_entry`; artwork still cannot be deleted directly; a cover
  that fails to move does not fail the media removal. Tests:
  `tests/removal.rs` 5 (3 new); Rust 110 passed; fmt and diff checks clean.
  Rebuilt and reinstalled (00:30); in the installed app a throwaway
  `audio/Qtmedia delete test.mp3` with its cover was deleted via
  `delete_media` and both went to the Recycle Bin.
- **Next action:** priority step 5 is already done; step 6 (video player)
  is done. Remaining: push so CI runs (needs the commit decision). Not
  committed.

## 2026-10-10 Native audio engine — Task 4 engine done

- New: `src-tauri/src/audio/engine.rs`, `tests/audio_engine.rs` (15 tests);
  `rtrb =0.4.0` (2026-08-17, MIT/Apache-2.0) added to `Cargo.toml`.
- **Design:** `Engine` (control state machine) + `Feeder` (decode → convert →
  `rtrb` byte ring, 2 s) + `Renderer` (ring → `Output`; no allocation after
  the first prefill). `Platform` trait opens caps (control thread) and
  outputs (render thread, since WASAPI objects are not `Send`);
  `WasapiPlatform` is the production one. `AudioEngine::spawn` runs control,
  decode and render threads; `ManualEngine` runs the same pieces on one
  thread for tests (manual clock, `FakeOutput`).
- **Behaviour:** `Command` (Play, Pause, Resume, Seek, Stop, SetVolume,
  SetNext, SetSettings, Release) → `Event` (State, Position ≤ 4 Hz,
  TrackStarted, TrackEnded, SignalPath, DeviceOpened, DeviceReleased,
  Error{code}). Gapless join when the next track negotiates the same output
  (any rates in shared mode); otherwise a new session after the end, reopening
  the device only if the format differs. The next track travels with the
  session start (a separately sent one raced the decoder on short tracks).
  Seek = new ring + output flush. Stop and end of queue release the device;
  pause releases it after 30 s (`RELEASE_AFTER`) and resume reopens at the
  paused position. Device errors → `Error{code}` + Stopped. Shared volume is
  applied at the renderer for float outputs (instant, not 2 s late);
  exclusive integer volume (opt-in) stays in the converter. Position comes
  from device-played frames, tagged with the session id so a stale position
  is never paired with a new session. The control loop ticks every 10 ms while
  a track end or join is due, else 250 ms.
- **Probe:** `examples/audio_probe.rs engine <index|default> <file>
  <shared|exclusive> [next_file]` runs the threaded engine.
- **Hardware (−30 dBFS, 0.25 s fixtures):** AirBass shared 44.1 → 96 kHz
  joined gaplessly on one device; AirBass exclusive fell back to shared with
  `exclusive_format_unsupported`; Realtek exclusive 16/44.1 → 16/44.1 joined
  gaplessly; 16/44.1 → 24/96 reopened at 96 kHz, both bit-perfect.
- **Verification:** `cargo test --locked` all suites pass (101 Rust tests),
  `cargo build --all-targets` warning-free, `cargo fmt --check` and
  `git diff --check` clean. Clippy still not installed (`rustup component
  add clippy`).
- **Paused (user decision, 2026-10-10):** the hi-fi work stops after Task 4.
  On the user's Bluetooth headphones it cannot be bit-perfect and they have no
  DAC, so Tasks 5–7 wait until they get a DAC or want gapless playback. The
  engine is self-contained and not wired into the app (no user-visible
  change). When resumed: Task 5 (Tauri commands, `audio-event`, preferences,
  library path confinement, `deviceChanged`). Work returns to priority step 4
  (yt-dlp updates + FFmpeg pin). Not committed.

## 2026-10-10 Native audio engine — Task 3 outputs done

- The user will listen on Bluetooth headphones (AirBass, A2DP "Headphones"
  endpoint), so shared mode is their music path; never bit-perfect.
- New: `src/audio/convert.rs` (`Converter`, `map_channels`),
  `src/audio/output/{mod,fake,device,shared,exclusive}.rs` (`Output` trait,
  `OutputError` + `map_hresult`, `Transport` + `classify_transport`,
  `DeviceInfo`, `PositionTracker`, `exclusive_fallback`, `open_output`,
  `FakeOutput`, `list_devices`, `WasapiCaps`, `WasapiShared`,
  `WasapiExclusive`). `format.rs` gained `Negotiated::{shared,apply_volume}`
  and `Reason::ExclusiveDenied`.
- Dependencies: `rubato =5.0.0` (5.0.1 is 9 days old); `wasapi =0.24.0` moved
  from dev-dependency to a Windows-only dependency; `windows =0.62.2` (same
  version wasapi uses) for endpoint properties; `lazy_static` pinned to 1.5.0
  (1.5.1 is 9 days old). All new crates are 14+ days old.
- Hardware finding (plan rule 5): the AirBass driver (Intel Smart Sound for
  Bluetooth) claims every exclusive format but refuses them at `Initialize`
  (`0x88890008`); `open_output` falls back to shared with
  `exclusive_format_unsupported`. Its hands-free endpoint is detected as
  `BluetoothHandsFree` from the `BTHENUM\{0000111E-…}` service UUID.
- Verification: `audio_probe play` on the AirBass (shared, 44.1 → 48 kHz,
  12,000 frames in 0.27 s; MP3 too) and the Realtek (exclusive 16/44.1,
  11,025 frames in 0.26 s), all quiet (≈ −30 dBFS). Tests
  `tests/audio_output.rs` 17 passed; Rust suite 86 passed `--locked`;
  `cargo fmt --check` and `git diff --check` clean. Clippy not installed.
- Next: Task 4 (engine: control/decoder/render threads, `rtrb`, gapless,
  seek, 30 s release, device loss).

## 2026-10-10 Native audio engine — Task 2 format negotiation done

- `src-tauri/src/audio/format.rs` (pure, no hardware): `PcmFormat`,
  `DeviceCaps` trait (`supports_exclusive`, `mix_format`, `is_bluetooth`),
  `Policy` (mode, `RateMismatch::{Strict,Resample}`, volume,
  `exclusive_volume`), `candidates`, `negotiate -> Negotiated {mode, output,
  gain, bit_perfect, reason}`, `bit_perfect_blocker`, `resample_target`,
  `pack_int` / `pack_float`.
- Rules: integer candidates never drop bits (16-bit → 16, 24, 24-in-32, 32;
  24-bit → 24, 24-in-32, 32); MP3 → f32 then the widest integer, always
  `lossy_source`; strict rate mismatch → shared with
  `exclusive_rate_unsupported`; resample → integer-ratio rate above the
  source first, labelled `resampled`; no lossless layout at a usable rate →
  shared with `exclusive_bits_unsupported`; exclusive gain fixed at 1.0
  unless `exclusive_volume`, below 1.0 → `software_volume`; Bluetooth →
  `bluetooth_output`. 24-in-32 packing keeps a zero low byte.
- Tests `tests/audio_format.rs`: 23 passed (mock device = Task 0 Realtek
  matrix). Rust suite 69 passed `--locked`; `cargo fmt --check` clean;
  `git diff --check` clean. Clippy not run: the component is not installed
  on the current stable toolchain (`rustup component add clippy`).
- The production `DeviceCaps` over `wasapi` arrives with Task 3, when
  `wasapi` moves from dev-dependency to dependency.
- Next: Task 3 (outputs: `FakeOutput`, `WasapiShared`, `WasapiExclusive`).

## 2026-10-10 Native audio engine — Task 1 decoder done

- `src-tauri/src/audio/{mod,decoder}.rs`: `Decoder::open/format/next_block/seek`
  over `symphonia =0.6.1` (features `flac`, `mp3`, `id3v2` only). FLAC →
  interleaved left-justified `i32` + `bits_per_sample` (ready for 24-in-32,
  shift for packed); MP3 → `f32` with gapless trimming; sample-accurate seek
  (accurate seek + dropping the lead-in frames), clamped at the end; errors
  `Io` / `Unsupported` / `Corrupt` (display codes `audio_io`,
  `audio_format_unsupported`, `audio_decode_failed`).
- Fixtures (synthetic, ~280 KB): `src-tauri/tests/fixtures/audio/` from
  `scripts/make-audio-fixtures.ps1` (bundled FFmpeg; FLAC and `.raw` twins
  share one WAV, LAME MP3).
- Tests `tests/audio_decoder.rs`: 8 passed (bit-exact 16/24-bit FLAC, left
  justification, gapless MP3 = 11,025 frames, exact seek to frame 4,410,
  clamp, errors) + 1 opt-in real-file test, run on a real 48/24 FLAC
  (7,585,920 frames) and a 48 kHz MP3 (8,672,932 frames): full decode matches
  each file's declared length.
- Rust suite 46 passed `--locked`; fmt and clippy clean for the module.
- Next: Task 2 (format negotiation). The DAC run of Task 0 is deferred until
  the user has a DAC.

## 2026-10-10 Native audio engine — Task 0 hardware spike done

Approved plan; Task 0 run. Probe `src-tauri/examples/audio_probe.rs` (list /
matrix / tone), `wasapi = "=0.24.0"` as a dev-dependency only (absent from
the release dependency tree). The 0.24 API matches the upstream example.
Results, now written into the plan as binding rules: aligned periods
(`calculate_aligned_period_near(1.5×min, 128)`) are required for the 44.1 kHz
family; exclusive event mode accepts only whole-buffer writes (pad with
silence); Bluetooth endpoints accept exclusive formats but are never
bit-perfect. Realtek exclusive: 44.1–192 kHz at 16/24/24-in-32 all played.
**Blocker:** the user's DAC was not visible to Windows (only Realtek and
AirBass Bluetooth were active); rerun `list`, `matrix` and `tone` on it.
Next: DAC matrix, then Task 1 (decoder). Rust 38 `--locked`, fmt clean.

## 2026-10-10 Native audio engine plan (approved)

Plan: `docs/superpowers/plans/2026-10-10-native-audio-engine.md`. Rust engine in
the Tauri host (symphonia decode → rtrb ring buffer → WASAPI shared or
exclusive render thread), library-relative paths only, signal-path/bit-perfect
reporting, gapless via `audio_set_next`, device picker and hot-plug, exclusive
released on stop/30 s pause/video/exit. Pins chosen to be ≥14 days old:
wasapi 0.24.0, symphonia 0.6.1, rtrb 0.4.0, rubato 5.0.0 (0.25.0/5.0.1 were
9 days old). Task 0 is a hardware spike on the user's DAC. Next action: user
approval, then Task 0.

## 2026-10-10 Video/Music search modes and FLAC with cover art

Research: `docs/research/2026-10-10-music-mode-and-hifi-audio.md` (Stave
analysis, FLAC honesty, WASAPI/ASIO/DSD/SACD). Spec:
`docs/superpowers/specs/2026-10-10-search-modes-flac-design.md`.
User decisions: Music saves FLAC labelled with its lossy source; Video downloads
the highest format immediately; next phase is a native Rust engine with WASAPI
Exclusive; Qtmedia will be licensed GPLv3 (licence file added when ASIO work
starts; copyright holder to confirm). DSD/DoP and SACD ISO deferred.

- **Stave (reference only, unlicensed):** webview `<audio>` → Web Audio EQ →
  shared-mode output; Spotify used for metadata only (anonymous web-player
  token or PKCE), audio from `ytsearch10:` + yt-dlp MP3 V0, tagged with lofty.
- **Engine:** inspection adds `FLAC · from <Opus|AAC> <kbps>` beside MP3 from
  the same best audio stream; FLAC downloads use `FFmpegExtractAudio`→flac,
  JPEG thumbnail conversion, `EmbedThumbnail` (front cover via mutagen
  1.48.1, now pinned in the sidecar and CI). Output extension follows the
  selection. Equal-height video ranking prefers H.264 > VP9 > AV1.
  `ThumbnailsConvertor` is a silent stage. `music.youtube.com` single tracks
  are allowed (playlists/home still rejected).
- **Library/transport:** `.flac` accepted by the sidecar scan, Rust path policy,
  and `qtmedia://` (`audio/flac`).
- **UI:** Home toggle "Video mode"/"Music mode" (remembered in localStorage,
  default Video); `inspect(url, mode)` auto-starts `pickFormat` (highest
  height / FLAC) or shows `no_video_format`/`no_music_format`. The format menu
  shows the engine's audio detail ("from Opus 142 kbps"); "Converting to
  FLAC/MP3" names the target.
- **Live:** FLAC files are 48 kHz/24-bit with an embedded front cover (type 3
  JPEG); the user's YouTube Music and youtu.be tracks saved as FLAC via the
  installed app, and the music player played the FLAC. Video mode saved the
  user's link (highest offered: 2160p) as a 431 MB file; its resolution was not
  probed before the test files were removed from the user's library.
- **Tests:** shared + engine CI selection 104, Vitest 82, Rust 38; Ruff and
  `cargo fmt` clean. CI selection now includes `test_desktop_flac.py`.
- **Note:** running all of `Qtmedia/tests` and `sidecar/tests` in one pytest
  invocation clashes on two `test_main.py` basenames; CI never combines them.

## 2026-10-10 Desktop app added to CI (plan step 3)

- `.github/workflows/ci.yml` gains job `app` on `windows-latest` (bash shell):
  Python 3.14 with `pip install -e ./Qtmedia[dev] curl-cffi==0.16.3` and
  `--no-deps -e ./QtmediaApp/sidecar`; pytest on the sidecar tests and the
  three `test_desktop_*` files; pnpm 11.20.0 + Node 24, `--frozen-lockfile`,
  Vitest, `pnpm build` (tsc + Vite, needed by the Rust build); stable Rust
  with rustfmt and `Swatinem/rust-cache`; empty `binaries/*.exe` stand-ins
  (the folder is untracked; tauri-build only checks they exist);
  `cargo fmt --check` and `cargo test --locked`. Existing lint/test jobs
  unchanged.
- Fixed `sidecar/pyproject.toml`: it depended on `Qtmedia`, but the CLI's
  distribution name is `qtmedia-cli`, so resolving it would have reached PyPI.
- Ruff (`ruff check Qtmedia`, the lint job) reported 6 errors from today's
  desktop-service work; fixed (import order, two unused `noqa`, a mutable class
  attribute in a test fake). HEAD itself was clean.
- Local run of every job command: Ruff clean, compileall ok, Qtmedia 158 (+1
  machine-dependent Firefox test that passes on runners without a profile),
  engine + desktop 93 without `PYTHONPATH` (local `.venv` now has the sidecar
  installed editable), frozen lockfile in sync, Vitest/build ok, Rust 37
  `--locked`. Not yet run on GitHub: needs a push.

## 2026-10-10 Truthful download progress (plan step 5 complete)

yt-dlp deletes `requested_formats` from each stream's hook payload, so a true
combined percentage is not knowable; progress now reports what is happening.

- **Engine (`download.py`, `models.py`):** `DownloadProgress` gains `stage`
  (`downloading|merging|converting|processing|saving`), `stream`
  (`video|audio` for merged formats), `part`, `parts`. `stream_count`
  derives parts from the selector (`137+bestaudio…` → 2); streams are numbered
  by first-seen filename and named from codecs. Percent uses exact size, else
  HLS `fragment_index/fragment_count`, else the estimate. A
  `postprocessor_hooks` entry maps `Merger`→merging, `ExtractAudio`→
  converting, others→processing (`MoveFiles` silent) and honours cancel.
  `saving` is emitted after a successful transfer. Protocol whitelist allows
  the new fields; Rust passes them through unchanged.
- **PMVHaven errors:** `requests` failures in `fetch_metadata` now raise
  `provider_unavailable` instead of falling through to `operation_failed`.
- **UI:** `lib/progress.ts` `describeProgress` gives Home and the toolbar ring
  one wording: "Downloading video (1 of 2) · 45%", "Merging video and audio",
  "Converting to MP3", "Finishing up", "Saving to your library" (no
  percentage and an indeterminate bar outside downloading), "Starting" before
  sizes are known. Event fields are optional (old engines → one stream).
- **Live:** YouTube 1080p engine stream: video 1/2 0→100, audio 2/2 0→100,
  merging, saving; MP3: downloading, converting, saving; PMVHaven HLS 360p
  0→100 with zero backward steps, then processing (HLS fixup), saving.
  Installed-app Home panel showed the same sequence. The YouTube test file was
  removed from the user's library afterwards (user asked to keep YouTube out).
- **Tests:** shared Qtmedia 158 (+1 machine-dependent Firefox test), sidecar
  26, Vitest 76, `tsc -b` clean.
- **Network note:** on the user's ISP (no VPN), PMVHaven's TLS is now
  intercepted (certificate verification fails, also in curl).

## 2026-10-10 Clean display names and ±10 s skip buttons

- **Clean names (plan step 5, first half):** files stay `Title [media-<id>].ext`
  on disk (unique; artwork pairing and actions use `relativePath`), but
  `lib/library.ts` `fileName`/`mediaTitle` strip ` [media-…]` for display, so
  Files, Video, Music, both players, the video overlay, and Home's Saved panel
  show `Title.ext` / `Title` (collision suffix ` (2)` kept). Search/sort use the
  display name. Tests: `lib/library.test.ts`.
- **Skip buttons:** two Video.js `SeekButton`s (`seconds={∓10}`) render as skin
  children, centred over the video, and fade with the skin's
  `data-controls-visible`. They match the skin's built-in ←/→ and J/L hotkeys
  (`DEFAULT_SEEK_STEP = 10`). Verified in the installed app: 121.1 → 131.1 →
  121.1 → 111.1 s; opacity 1 with controls, 0 after idle.
- Vitest 70 passed; `tsc -b` clean. Installed build updated.
- Truthful progress (step 5, second half) is still open.
- **Player theme ("match the app" + "trim the bar"):** CSS variables on
  `.video-overlay__skin` only, no skin fork: `--media-accent-color: var(--accent)`
  (replaces the earlier internal `--media-accent`), Segoe UI via
  `--media-font-family`, `--media-border-radius: 0` and transparent
  `--media-frame-border` (edge to edge), graphite `--media-popover` (the skin
  paints the control bar with it) and 24 px blur, 12 px bar / 8 px button
  radii; `.media-cast-button`/`.media-airplay-button` hidden (AirPlay never
  renders on Windows). Skip buttons enlarged on graphite. Verified computed
  styles in the installed app; visible bar: play, mute, time, slider,
  settings, PiP, fullscreen.

## 2026-10-10 Built-in video player (Video.js 10)

Spec/plan: `docs/superpowers/specs/2026-10-10-video-player-design.md` (approved
in chat: full-window overlay, resume, Video.js 10.0.1 pinned; next/prev, PiP,
custom hotkeys out of scope).

- **Dependency:** `@videojs/react` `10.0.1` (exact pin, Apache-2.0; published
  2026-10-02, 8 days before adoption). `VideoPlayer › VideoSkin › Video` with
  `@videojs/react/video/skin.css`; `Video` is a native `<video>` that forwards
  its ref and standard events, so resume uses `onLoadedMetadata`/
  `onTimeUpdate`/`onPause`/`onEnded`. Skin accent via `--media-accent`.
- **Transport:** `media.rs` now serves `video/*.mp4` (`video/mp4`) besides
  `audio/*.mp3`; every body is bounded to 2 MB (closed ranges clamped,
  large no-Range requests get a bounded 206) because files exceed 1 GB.
  New test `serve_with_limit` hook; artwork and other paths stay refused.
- **UI:** `components/VideoOverlay.tsx` (lazy chunk: 256 KB JS + 84 KB CSS;
  startup bundle unchanged at 247 KB). Opened from the Video grid, Files, and
  Home's Play after a video download via `onPlayVideo`; pauses music; Esc or
  the close button saves the position and closes; focus returns to the opener;
  "Open in default player" fallback on playback error or without `mediaUrl`.
  Overlay z-index 59 keeps the window controls (60) usable; its top bar is a
  drag region. Video's "Player coming soon" badge and sidebar "Soon" removed.
- **Resume:** `lib/resume.ts` stores `{relativePath: position}` in webview
  localStorage (`qtmedia.resume.v1`), skips <10 s and the last 15 s, clears
  on end, keeps 200 most recent, tolerates corrupt/blocked storage.
- **Installed-app verification:** all six library videos played at native
  size (1080p ×3, 720p ×2, 480p); seeking to 25:00 in the 1.1 GB Eporner file
  kept playing; reopening showed "Resumed at 25:03 · Start over" and resumed;
  Esc closed the overlay. Not verified by hand: real mouse focus return,
  fullscreen + Esc order, dragging the window by the overlay bar.
- **Tests:** Vitest 67 (resume 5, overlay 6, wiring 2 new); Rust all passing
  (media 6); `tsc -b`, `cargo fmt --check`, `git diff --check` clean.

## 2026-10-10 SpankBang title fix and VPN adapter results

- yt-dlp's SpankBang extractor returned the video ID (`3ikv8`) as the title.
  `inspection._display_title` now falls back to the URL slug when the title is
  missing or equals the extractor's `id`/`display_id` (separators → spaces,
  `.html` dropped, numeric-only slugs ignored). Live: SpankBang →
  "Bimbo fuck dolls pmv w names"; YouTube/XVideos unchanged. Tests: 3 slug
  cases + an unusable-slug case. Engine/installer not yet rebuilt with it.
- Over a VPN (Japan exit): TNAFlix 720p ✔ (180 MB), Eporner 1080p downloading.
  The user's YouJizz link returns HTTP 500 from YouJizz for every client and
  network; another YouJizz video extracts fine (up to 720p). WARP proxy mode
  worked as a route (inspection succeeded) but ran at ~5–19 KB/s here.
- One video per site was placed in the user's library
  (`Downloads\Qtmedia\library`) with matching artwork.

## 2026-10-10 DoH, proxy, app-owned adapter list, Eporner

User asked for DNS-over-HTTPS, a proxy, and Eporner (priority step 2 folded in).

- **Adapters:** `desktop_service/adapters.py` is the desktop's own reviewed
  list (XVideos, XHamster, SpankBang, TNAFlix, YouJizz, YouPorn, Eporner;
  PMVHaven/YouTube keep dedicated rules in `policy.py`). The policy no longer
  reads the CLI's `ADAPTERS`; a test proves a new CLI site is rejected.
  Impersonation (`chrome`) moved here for SpankBang and XVideos.
- **Network:** `desktop_service/network.py` reads `QTMEDIA_DOH` (RFC 8484
  endpoint) and `QTMEDIA_PROXY`. DoH patches `socket.getaddrinfo` (falls back
  to system DNS on DoH failure; IP literals/localhost untouched) and wraps
  `curl_cffi.Curl.perform` to set `DOH_URL` on every transfer (curl_cffi
  resets handles). DoH queries never use the proxy. The proxy goes to yt-dlp
  (`proxy`) and to engine sessions (PMVHaven metadata, artwork). The engine
  installs DoH at startup (`qtmedia_engine/main.py`).
- **Rust:** `settings.rs` adds `NetworkPreference { doh: Off|Cloudflare|Google|Quad9,
  proxy }` inside the existing v1 preference (`#[serde(default)]`, so old files
  load as Off); `validate_proxy` requires http/https/socks4(a)/socks5(h),
  host, and port; invalid stored proxies are dropped. Providers use IP
  endpoints (1.1.1.1, 8.8.8.8, 9.9.9.9). `get_network_settings` /
  `set_network_settings` reuse the guarded probe-then-swap engine restart;
  library switches and crash recovery keep the network choice. New stable error
  `invalid_proxy`. `url = "=2.5.8"` added (already in the lockfile).
- **UI:** Settings → Network: Secure DNS select, Proxy field, Apply (restarts
  the engine), busy lock, `invalid_proxy` message. Bridge methods are optional;
  the mock bridge implements them.
- **Engine deps:** `curl-cffi==0.16.3` installed in `.venv` and declared in
  `sidecar/pyproject.toml` (it was missing, so the packaged engine had no
  impersonation before).
- **Format fixes:** heights are read from format IDs when the extractor omits
  them (TNAFlix `…-720p_60fps`).

Live results (packaged engine, highest MP4, DoH on): SpankBang 1080p ✔,
XHamster 720p ✔, XVideos 480p ✔ (3/3), PMVHaven 1080p ✔, YouTube 1440p ✔.
TNAFlix inspects 720p–144p and Eporner 1080p–240p, but this network resets
their TLS handshakes intermittently (SNI filtering, also with curl's Chrome
fingerprint), so downloads fail mid-way; YouJizz is reset or returns an
nginx 500. These need the proxy; no proxy was available to test it live.
Installed-app pass: Settings applied Cloudflare DoH (saved with the custom
library intact), rejected `proxy.example:8080`, and Home downloaded XHamster
720p (Saved panel shows 32.6 MB, confirming the size fix).

Verification: shared Qtmedia 140 passed (+1 machine-dependent Firefox
test), sidecar 25, Rust 35, Vitest 54, `cargo fmt --check` and
`git diff --check` clean. Not verified: a live proxy; YouPorn.

## 2026-10-10 bundled Deno runtime, installer, adapter checks

- **Deno:** without a JS runtime, YouTube MP3 downloads failed 1 in 4 runs
  (unsolved player challenges). Deno 2.9.7 now ships beside the host
  (`externalBin` `binaries/deno`); `BundledTools::locate` in `sidecar.rs`
  requires `ffmpeg` and `deno` and passes `QTMEDIA_DENO`;
  `desktop_service/runtime.py` prefers it and otherwise falls back to the CLI's
  configured lookup (CLI behaviour unchanged). `scripts/prepare-deno.ps1` pins
  the version and SHA-256 (`a0c3101b…2238`); run it before any Tauri build.
  yt-dlp's verbose log confirmed `JS runtimes: deno-2.9.7` with Node absent.
- **Completed-entry fields:** `download_completed.entry` lacked size/mtime, so
  the Pro UI showed "NaN MB". `DownloadResult` now carries `size_bytes`,
  `modified_at`, and `duration_seconds` like a listing entry.
- **PMVHaven:** downloads failed ("Requested format is not available"). The
  app synthesized one codec-less format; the manifest is muxed HLS. Inspection
  now runs yt-dlp on the PMVHaven HLS master, and codec checks treat yt-dlp's
  `None` as unknown (only `"none"` means absent). Real 1080p–360p + MP3 now.
- **Installer:** `pnpm desktop:build --bundles nsis` (MSI/WiX skipped) produced
  `Qtmedia_0.1.0_x64-setup.exe`, 82.8 MB (52.5 MB before Deno), installed
  silently to `%LOCALAPPDATA%\Qtmedia`.
- **Installed-app UI pass (Node hidden from PATH)**, driven over WebView2
  DevTools: inspect, 720p download with navigation to Files (download ring
  shown), Files refresh, MP3 download, MP3 playback via `qtmedia://` (playing,
  0:03 of 3:00), 1440p cancel → "Download cancelled.", re-inspect. Closing left
  no engine processes.
- **Adapter results (highest MP4):** YouTube 1440p ✔; PMVHaven 1080p ✔
  (1920×1080 H.264/AAC). SpankBang, XHamster, TNAFlix: `provider_unavailable`
  because this network (hotspot gateway 172.20.10.1) DNS-sinkholes them to
  202.56.230.30. With real DNS, XHamster answers 200 and SpankBang reaches its
  Cloudflare check (DNS-only block); TNAFlix and Eporner get TLS resets (SNI
  block, needs VPN/proxy). Eporner is also `unsupported_source`: it is not in
  the CLI adapters the desktop policy reuses. XVideos, YouJizz, YouPorn not yet
  tested. The CLI has only an optional proxy (`PRIVATE_SEARCH_PROXY`); the app
  has none.
- **Verification:** shared Qtmedia 123 passed (+1 machine-dependent Firefox
  test); sidecar 25; Rust all passed incl. `bundled_tools_require_ffmpeg_and_the_deno_runtime`;
  Vitest 50; `cargo fmt --check` clean.
- **Changed (this pass):** `desktop_service/{runtime.py (new), download.py,
  inspection.py, models.py}`, `Qtmedia/tests/test_desktop_service.py`,
  `src-tauri/src/sidecar.rs`, `src-tauri/tauri.conf.json`,
  `src-tauri/tests/sidecar_path.rs`, `scripts/prepare-deno.ps1` (new).
- **Resolved later the same day:** DoH and proxy settings were added (see the
  section above).

## 2026-10-10 Pro UI and music player implemented

The user approved the Pro design and asked for it to be built, with a cover-adaptive Now
Playing background. Decisions: build real music playback now; video playback stays
deferred. Reference: github.com/Fizzy444/Stave (unlicensed, so patterns only;
no code copied). Plan: `docs/superpowers/plans/2026-10-10-pro-ui-music-player.md`.

What changed:
- **Rust:** new `src/media.rs` plus the `qtmedia://` scheme registered in
  `lib.rs`. It serves only `audio/*.mp3` from the active library via
  `resolve_library_entry`, supports byte ranges for seeking, accepts GET/HEAD
  only, and runs on a worker thread. `AppState::library_root()` added. CSP gains
  `media-src 'self' qtmedia: http://qtmedia.localhost`. Unlike Stave, no asset
  protocol and CSP stays on.
- **Frontend:** the UI is rewritten to the Pro design. Floating sidebar
  (hover/focus expands), unified toolbars with a download ring, Home search bar
  with a dropdown flow (lookup → format menu, where a click downloads → progress
  → done/error), Finder-style Files, Video grid (system player), Music library
  plus global player bar, Now Playing overlay, grouped Settings, and a new line
  icon set with the `QMark` logo.
- **Player:** `lib/player.tsx` has a queue, shuffle that keeps the current
  track first, repeat off/all/one, "previous" restarting after 3 s, volume and
  mute, Media Session keys, and it stops when the library location changes.
- **Now Playing:** the backdrop is the cover itself (blurred 70 px,
  saturate 1.5, scrim). `lib/coverColor.ts` samples a saturation-weighted
  colour for the tint, the no-artwork fallback, and the progress fill.
- **Session:** `startDownload(formatKey?)`. The bridge has an optional
  `mediaUrl` (via `convertFileSrc(…, "qtmedia")`). The mock bridge serves a
  generated WAV tone so playback works in a browser.
- **App icon:** the Q monogram is generated into `src-tauri/icons` with
  `tauri icon`, and `assets/icon.svg` is replaced. Bodoni font removed;
  `NavRail`, `ActivityTray`, and `ComingSoonPage` deleted.

Verification:
- Vitest 50 passed. New tests cover the player rules, Music/Now Playing, the
  fallback without `mediaUrl`, the cover colour maths, and the icons; tests
  were updated for the format-row download and "Files"/"Music"/"Open Folder"
  copy.
- `tsc -b` clean, build passes, no mock code in the bundle.
- Rust: 29 passed (4 media-protocol and 1 CSP test new), `cargo fmt --check`
  clean.
- The full UI was driven with the mock bridge in headless Brave at 1366×768 and
  960×640. A song played, the queue was switched, and the Now Playing
  background changed with the cover (violet → coral). Screenshots are in
  `artifacts/2026-10-10-pro/`.

Notes and blockers:
- The parallel Deno-runtime work lists `binaries/deno` in `tauri.conf.json`,
  but the binary is not prepared, so `cargo build` fails until
  `scripts/prepare-deno.ps1` runs. Rust tests were run with a temporary empty
  placeholder that was deleted afterwards. That work (Deno, `runtime.py`,
  sidecar/test edits) was left untouched.
- Not verified: the rebuilt Tauri app itself (real `qtmedia://` playback in
  WebView2, seeking on large MP3s, media keys). Next: prepare Deno, run
  `pnpm desktop:dev`, play a downloaded MP3, seek, switch the library during
  playback, then commit.
- Still deferred: video player, playlists, lyrics, and reading MP3 tags (an
  artist name is not shown).

## 2026-10-10 "Pro" redesign proposal (supersedes Fluid)

User feedback on Fluid:
- Home must be a single search bar; Enter drops down a panel with lookup
  progress, then the formats; clicking a format downloads it with a modern
  progress bar.
- The colours looked sloppy. Simplify everything except the sidebar, like a
  professional Mac app.
- The user also supplied two music-player references: a library with a bottom
  player bar, and a cover-tinted Now Playing view.

Mockups are in `design/2026-10-10-pro/` (11 screens plus a 960×640 render, README,
`index.html`). Neutral graphite tokens, one flat violet accent, Finder-style
Files, System Settings-style Settings. The app icon is unchanged from Fluid.
Data gaps noted in the README: MP3 artist tags, lyrics, the players
themselves, and the inspection thumbnail. **Status: awaiting approval. No app
code changed.**

## 2026-10-10 "Fluid" redesign proposal

The user was not satisfied with the implemented Ink and Violet UI and asked for
a ground-up redesign, including the app icon (modern, fluid, simplified). The
user chose: keep ink + purple, a collapsible sidebar, and a Q monogram icon.
Mockups (icon sheet, 8 screens, plus 960×640 renders) are in
`design/2026-10-10/`, with a README and an `index.html` gallery. **Status: awaiting
approval. No app code changed in this pass.** The Ink and Violet code from
2026-10-09 is still uncommitted in the working tree and will be replaced if
Fluid is approved. Next: user feedback, then an implementation plan, including
generating `src-tauri/icons` from the Q mark.

## 2026-10-09 Ink and Violet UI implemented

User approved the design and asked to build it. Plan:
`docs/superpowers/plans/2026-10-09-ink-violet-ui.md`. Open data items used the
documented fallbacks, so this is a frontend-only change (no Rust, sidecar, or
protocol changes):

- No inspection thumbnail (icon tile instead), no saved quality in Recently
  saved, no download phases, no engine status, no supported-sites list.
- Quality nicknames (4K, Full HD…) computed in UI from height.
- Video and Music are library grids (still badged "Coming soon"). Play/hover
  opens the file with the system player via the existing `openMedia` until the
  built-in players ship. Music's player bar is shown idle ("Nothing playing"),
  with controls disabled.
- Settings: Download location (unchanged behaviour), Privacy facts, About with
  version via `getVersion()` (allowed by `core:default`; new optional
  `DesktopBridge.appVersion`).

Code: new `lib/library.ts` (`useLibrary`, formatting helpers),
`components/Artwork.tsx`, `components/MediaPages.tsx` (Video/Music); rewritten
`app.css`, `HomePage`, `FilesPage`, `SettingsPage`, `NavRail` (labelled rail),
`ActivityTray`; `Icon` gained 12 Material icons; `ComingSoonPage` removed.
Fixed a layout bug where the stage grew past short windows (no scrolling to
the last Files rows); the grid row is now bounded.

Verification: Vitest 42 passed (5 new in `MediaPages.test.tsx`; 4 existing
tests updated for intentional copy/flow changes: "Files" heading, "Open
folder", Video page, Home clears the link on New link). `tsc -b` clean,
production build passed, mock code absent from bundle, `git diff --check`
clean. All states were driven through the real UI with the mock bridge in
headless Brave over CDP at 1366×768, 1024×640, and 960×640. Screenshots are in
`artifacts/2026-10-09-ink-violet/`.

Not verified: the rebuilt Tauri app itself (WebView2 rendering, `getVersion`
at runtime). Next: run `pnpm desktop:dev` or rebuild the release exe, smoke test
Home/Files/Video/Music/Settings against the real engine, then commit.

## 2026-10-09 UI refresh proposal (Ink and Violet)

User asked for a full-app UI refresh: simpler and more modern, ink black mixed
with the current purple. Mockups are in `design/2026-10-09/` (7 screens plus a
960×640 render, `index.html` gallery, `README.md` with decisions). They are
HTML/CSS sources in `src/`, rendered to PNG with headless Brave at 1366×768.
Video and Music mockups revised to full-width grids with hover play (no side text). **Status: awaiting user approval. No app code changed.** The README lists seven
elements that need data the bridge does not provide (inspection thumbnail,
saved quality, download phases, engine status, etc.). Each needs a decision
before implementation. Next: user feedback, then a written implementation plan
per the review gate.

## 2026-10-09 UI dev mock bridge

Added a browser-only UI loop so screens can be built and checked without the
Tauri host or Python engine. `frontend/src/lib/mockBridge.ts` implements
`DesktopBridge` with fictional sample data and timed events; `main.tsx` loads
it via dynamic import only when `import.meta.env.DEV && !isTauri()`, so release
builds and `desktop:dev` use the real bridge.

- Run: `pnpm --dir QtmediaApp/frontend dev`, open `http://127.0.0.1:1420`.
- Link keywords pick scenarios: any `https` link succeeds; `unsupported`,
  `offline`, `noformats` return those errors; non-http input is `invalid_url`;
  `audio` gives an MP3-only source; `unknown-size` omits totals; `fail` aborts
  the download halfway; `slow` makes everything 10x slower. Cancel is supported.
- `?library=empty|error|full` sets the Files state (default `full`, 8 entries
  with generated SVG artwork). Settings "choose" switches to a fake `D:\` path.
- Format labels mirror the engine (`1080p MP4`, `MP3 · 192 kbps`).

Verification: Vitest 37 passed (7 new mock tests), `tsc -b` clean, production
build passed, and the built bundle contains no mock code (grep for mock
strings in `dist/assets` found nothing). In the in-app browser: inspect, then
720p download, then navigating to Files mid-job; Files auto-refreshed with the
new entry and artwork; `?library=error` showed the retry state; no console
errors.

Changed files: `frontend/src/main.tsx`, `frontend/src/lib/mockBridge.ts`,
`frontend/src/lib/mockBridge.test.ts`, `setup.md`, this context. A local
`.claude/launch.json` (`qtmedia-ui`, git-ignored) starts the dev server for the
agent browser pane.

Next UI action: the responsive pass on Home (idle, formats panel, downloading),
Files, and Settings at 1366×768, 1024×640, and 960×640 using the mock bridge.

## 2026-10-09 operational pass

Root cause of the engine loss: with `quiet` alone, yt-dlp still printed
`[download] NN%` bars to stdout, gluing them onto protocol lines. The Rust host
treats any unparseable stdout line as a dead engine and killed it on the first
download. Fixes:

- `download.py`: `noprogress: True` for desktop downloads.
- `qtmedia_engine/main.py`: `protect_protocol_stdout()` keeps a private dup of
  fd 1 for protocol events and points fd 1 and `sys.stdout` at stderr, so
  library prints and FFmpeg children can never reach the pipe.
- `sidecar.rs`: whitespace-only stdout lines are ignored rather than fatal.
- Cancel reported `download_failed` and left fragment files: yt-dlp wraps the
  hook's cancellation in `DownloadError`, and fragment threads still held
  `.part` files, so cleanup raised `PermissionError` from `finally`. Cancellation
  is now recognized through the wrapper, and cleanup retries locked files for
  ~3 s and never masks the job outcome.

Verification (2026-10-09):

- Packaged engine driven over JSONL with `https://youtu.be/XbNIT-6_0bU`
  (3:01): 1440p–144p plus MP3 listed; 720p (960×720 VP9/AAC MP4), 1440p, and
  MP3 completed with artwork; zero non-JSON stdout lines (525 before the fix).
- Real release `Qtmedia.exe` driven through its WebView2 DevTools port: inspect,
  720p download with navigation to Files mid-job (tray stays visible), Files
  auto-refresh with artwork, MP3 download, 1440p cancel showing "Download
  cancelled.", re-inspect after cancel, Settings path display. Force-closing
  the host left no orphaned engine processes.
- Suites: sidecar 25 passed (needs `PYTHONPATH=QtmediaApp/sidecar/src`);
  shared Qtmedia 120 passed + 1 machine-dependent CLI failure
  (`test_ydl_options_uses_opt_in_firefox_cookies_for_spankbang` sees a real
  local Firefox profile); Rust 23 passed, `cargo fmt --check` clean; Vitest 30
  passed (no frontend change).
- Not verified: NSIS/MSI installer rebuild. Bundling timed out downloading the
  NSIS/WiX toolsets from GitHub in the agent sandbox; `target/release/Qtmedia.exe`
  with its sibling engine and FFmpeg was rebuilt and tested instead.

Known gaps carried forward:

- After a cancel, one `.part` file written late by a fragment thread can remain
  in `temp/` until the next engine start sweeps it.
- YouTube heights are delivered as VP9-in-MP4; most players handle it, but some
  default Windows players may need the VP9 extension.
- `scripts/prepare-ffmpeg.ps1` copies whatever FFmpeg is on PATH; no pinned
  version/checksum and no `ffprobe` yet.
- `tauri.conf.json` `targets: "all"` also builds MSI (WiX); use
  `pnpm desktop:build --bundles nsis` for the NSIS-only release.

Changed files: `Qtmedia/src/qtmedia/desktop_service/download.py`,
`Qtmedia/tests/test_desktop_service.py`,
`sidecar/src/qtmedia_engine/main.py`, `sidecar/tests/test_stdout_guard.py`,
`src-tauri/src/sidecar.rs`, and this context.

## Current product behavior

- Home follows the approved 2026-09-14 visual direction: compact Q navigation
  rail, centered QT MEDIA lockup, “Save media. Keep it yours.” introduction,
  and a focused direct-link field. The former “Save to your Qtmedia Library”
  storage strip is removed.
- Inspection opens an accessible top-down format panel. Exact discovered video
  heights and MP3 192 kbps are selectable; the desktop download path does not
  silently replace the chosen video format with a generic best format.
- The active download session survives navigation. A global activity tray shows
  truthful byte/percentage data when the provider supplies it, keeps
  “Cancelling…” visible while cleanup is running, and refreshes Files after a
  completed job.
- Files provides loading, load-failure/retry, empty-library, no-filter-match,
  search, filter, sort, artwork, and validated open actions.
- Settings displays the full active download location. A native folder picker
  can switch to `<selected folder>/Qtmedia/library`, or recognize a selected
  existing `Qtmedia/library`; “Use default” restores the platform app-data
  location. The versioned preference persists locally. Existing media is not
  moved, and switching is rejected while inspection/download/cancellation is
  active. The replacement sidecar is probed before the old engine is stopped.

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

## Windows release result

The refreshed PyInstaller engine and Windows x64 NSIS installer were built on
2026-09-15. The final installer is:

`src-tauri/target/release/bundle/nsis/Qtmedia_0.1.0_x64-setup.exe`

- installer: 50.06 MiB / 52.50 MB;
- Tauri host: 11.50 MiB / 12.06 MB;
- Python engine: 21.39 MiB / 22.43 MB;
- FFmpeg: 98.09 MiB / 102.86 MB;
- runtime component subtotal: 130.98 MiB / 137.34 MB.

The installer and measured runtime subtotal are below the 140 MB internal
ceiling and the 150 MB product limit. This subtotal is not a measurement of
every byte added by an installed Windows WebView runtime if the target machine
does not already provide it.

## Verification on 2026-09-15

- shared/existing Qtmedia Python suite: 119 passed;
- sidecar Python suite: 23 passed;
- React/Vitest suite: 29 passed;
- Rust suite: 23 integration tests passed;
- production Vite build and optimized Tauri/NSIS build passed;
- rebuilt packaged sidecar probe returned protocol-only `ready`;
- focused RED/GREEN coverage exists for settings persistence/path selection,
  sidecar activity and intentional shutdown, exact provider selectors,
  cancellation acknowledgement, navigation-persistent progress, Settings retry,
  Files refresh/error states, and CSP artwork transport;
- capability tests confirm no frontend shell or unrestricted opener access.

The approved Home and Settings direction was visually inspected in the local
app/browser during implementation. Native picker selection/reset and exact
960×640/1024×640 window rendering still need a final manual installed-app pass.

## 2026-09-15 media-engine recovery fix

- Reproduced the reported state at the process boundary: the installed Tauri
  host was running while no `qtmedia-engine` process remained, so Find Formats
  had only a dead manager and returned `sidecar_unavailable`.
- Verified that the installed engine binary, installed FFmpeg, custom library
  root, redirected stdin/stdout protocol, probe, and an inspection request all
  worked independently. A clean host restart also spawned and retained the
  expected PyInstaller parent/child engine processes. Stopping an old engine
  while a separately probed replacement was active did not terminate the
  replacement. The original child-termination trigger was therefore not
  reproduced.
- Fixed the persistent failure mode in Rust: `inspect` and `library_list` now
  restart, probe, atomically install, and retry against one replacement engine
  after `sidecar_unavailable` or `sidecar_exited`. Download and cancel requests
  are never replayed because their opaque in-memory job state may be lost.
- Process failure now clears stale activity state, terminates a malformed or
  failed child, and avoids emitting a premature global error while a pending
  command is eligible for recovery.
- Added RED/GREEN recovery-policy and lost-activity tests. The complete Rust
  suite passed with 23 tests, formatting passed, the production frontend built,
  and a fresh NSIS installer completed at 52,503,523 bytes (52.50 MB).
- Changed files: `src-tauri/src/commands.rs`, `src-tauri/src/sidecar.rs`,
  `src-tauri/tests/sidecar_path.rs`, `setup.md`, and this context. The remaining
  check is to install the rebuilt NSIS package, reproduce an engine loss or the
  original user flow, and confirm Find Formats transparently recovers.

## Next concrete action

Commit the operational app (user-approved scope), then rebuild the NSIS
installer outside the sandbox with `pnpm desktop:build --bundles nsis`. The
2026-10-09 automated pass covered inspection, download, cancel, navigation, and
Files; the remaining manual items from the earlier list are:

1. In Settings, select a temporary custom parent folder, confirm the derived
   Qtmedia library path, open it, then restore the default location.
2. Inspect an authorized YouTube URL, confirm the listed heights, download one
   video and one MP3, cancel one test job, and navigate during another job.
3. Confirm Files refreshes automatically and opens only the selected active
   library's local media.
4. Check Home, Files, and Settings at 1366×768, 1024×640, and 960×640.

After that validation, the next product milestone is either the Video player or
Music library/player. macOS builds, signing, and notarization remain deferred.

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

## Relevant implementation

- `frontend/src/lib/DesktopSession.tsx` and `frontend/src/components/` — shared
  workflow state, Home, Files, Settings, navigation, activity tray, and tests.
- `src-tauri/src/settings.rs`, `commands.rs`, `sidecar.rs`, `paths.rs`, and
  `protocol.rs` — preference, safe root switching, process lifecycle, and IPC.
- `sidecar/src/qtmedia_engine/` — JSONL engine and cancellation lifecycle.
- `../Qtmedia/src/qtmedia/desktop_service/` — structured inspection/download
  service used by the desktop sidecar; CLI entry points remain unchanged.
- `design/2026-09-14/` — approved mockups and design decisions.
- `../docs/superpowers/plans/2026-09-14-qtmedia-improved-workflow.md` —
  implementation plan followed for this pass.

## Files changed in this pass

- React application shell, Home, Files, Settings, shared session/activity UI,
  bridge types, CSS, and component tests under `frontend/`.
- Rust settings, commands, sidecar lifecycle, protocol, paths, capabilities,
  Tauri configuration, Cargo manifest/lockfile, and tests under `src-tauri/`.
- Python sidecar engine/tests and shared desktop inspection/tests.
- `setup.md`, approved Settings design, implementation plan, and this context.
- Rebuilt ignored release artifacts and target-suffixed sidecar binary.

Unrelated root documentation edits and the user's Telegram bot removals were
preserved and not modified as part of this app work.

## Maintenance rule

Read this file first and update it after every meaningful work session or
change affecting scope, architecture, dependencies, file layout, tests,
verification, blockers, or the next action.
