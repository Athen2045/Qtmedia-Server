# Qtmedia UI refresh: Ink and Violet

Date: 2026-10-09. Status: **approved and implemented 2026-10-09** (fallbacks used for every "needs new data" item; see `docs/superpowers/plans/2026-10-09-ink-violet-ui.md`).

Full-app visual refresh of the existing structure: Home (downloader), Files,
Settings, and the Video and Music players as designed coming-soon pages. The
mockups are real HTML/CSS at window size, rendered to PNG with headless Brave,
so every value here can be lifted straight into `frontend/src/app.css`.

| Screen | Image | Source |
| --- | --- | --- |
| Home, idle | [01-home.png](01-home.png) | [src/01-home.html](src/01-home.html) |
| Home, formats | [02-formats.png](02-formats.png), [960×640](02-formats-960x640.png) | [src/02-formats.html](src/02-formats.html) |
| Home, downloading | [03-downloading.png](03-downloading.png) | [src/03-downloading.html](src/03-downloading.html) |
| Files + activity tray | [04-files.png](04-files.png) | [src/04-files.html](src/04-files.html) |
| Video, coming soon | [05-video-soon.png](05-video-soon.png) | [src/05-video-soon.html](src/05-video-soon.html) |
| Music, coming soon | [06-music-soon.png](06-music-soon.png) | [src/06-music-soon.html](src/06-music-soon.html) |
| Settings | [07-settings.png](07-settings.png) | [src/07-settings.html](src/07-settings.html) |

To re-render, open any `src/*.html` in a Chromium browser at 1366×768.
All titles, sizes, dates, and paths are fictional sample data.

## Direction

- **Ink layers instead of flat black.** Five ink steps (`#07070a` canvas,
  `#0d0d12` rail, `#13131a` panels, `#1a1a23` raised, `#23232e` fills), and
  hairline borders at 7%/12% white instead of grey borders.
- **Violet only where it means something.** `#806eff` marks the primary
  action, the current selection, active navigation, and progress. Selected
  items use a 13% violet tint with a violet border. The blue→violet→pink
  gradient is only used on the wordmark and the rail "Q".
- **One sans family** (Segoe UI Variable/system) for every label and number;
  Bodoni stays only for the brand. Fixed type scale: 26 / 17 / 15 / 14 / 13 / 12 / 11.
- **Rail with labels.** 76 px rail, icon plus a short label, a violet
  tint for the active item and a small grey dot marking coming-soon items.
  Settings sits at the bottom of the rail.
- **Fewer boxes on Home.** Idle Home shows the wordmark, one omnibox (link
  icon, Paste, Find formats) and a "Recently saved" strip from the library. After
  inspection the brand shrinks to a small header and the choice becomes a
  tile grid (quality as the large value, a short name under it) with a fixed
  footer holding the destination and a "Download 1080p" button.
- **Players as library views** (revised 2026-10-09 at user request; no side
  copy). Video is a full-width grid of 16:9 cards: artwork, a duration badge,
  title, then format, size and date. A violet play button fades in over the thumbnail on
  hover/focus. Music is a full-width grid of square covers with a play button
  on hover, an equalizer mark on the playing track, and a full-width
  player bar (track, previous/pause/next, seek, volume). Both keep the
  "Coming soon" badge until the players ship. The cards use only fields already
  in `LibraryEntry` (artwork, duration, extension, size, modified time).

## Needs new data or behavior (decide before implementing)

These appear in the mockups but the current bridge does not provide them.
Each one either needs approved work or should be left out:

1. **Inspection thumbnail** (source card on Home). Today `inspection_ready`
   has no artwork. Fallback: neutral tile with the video icon.
2. **Saved quality in Recently saved** ("1080p"). `LibraryEntry` has no
   height. Fallback: show type and duration only.
3. **Download phases** (Checked link → Downloading → Merging → Saved). The
   engine only sends start, progress, and completion. Fallback: drop the step
   row and keep percent plus bytes.
4. **Quality nicknames** (4K, Full HD, HD…) can be computed in the UI from
   `height`, so no engine change is needed.
5. **Media engine status** in Settings. There is no status command today, so
   one would need adding through the Rust host (no new localhost server).
6. **Supported sites list** ("See list") would open a local panel and must not
   link to any website.
7. **Video/Music grids**: built from the existing library scan; playback itself is the future player milestone.

## Unchanged

Existing behavior stays as it is: format choice, cancel, the progress tray that
stays visible across pages, every Files state, Settings location rules, the
privacy limits on links and files, and the 960×640 minimum window. No new
dependencies; fonts and icons stay local.
