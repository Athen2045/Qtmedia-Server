# Qtmedia "Pro" redesign

Date: 2026-10-10. Status: **approved and implemented 2026-10-10** (plan: `docs/superpowers/plans/2026-10-10-pro-ui-music-player.md`; screenshots of the built UI: `QtmediaApp/artifacts/2026-10-10-pro/`). Revises the same-day
"Fluid" direction (`../2026-10-10/`) after user feedback.

## Feedback addressed

1. **Home is a single search bar.** Paste a link and press Enter, and a panel drops
   down from the bar. It shows lookup progress, then the available formats as a
   menu. Clicking a format starts the download straight away (no second button),
   and the same panel shows a progress bar, then the finished state.
2. **Calmer colour scheme; a professional Mac-app feel.** Neutral graphite
   surfaces, hairline separators, compact native-feeling controls, and one flat
   violet accent. No aurora, glows, glass, or decorative gradients (gradients
   remain only in the app icon and media artwork). The sidebar keeps the Fluid
   structure (floating, icon-only, expands on hover) in the new neutral colours.
3. **Music follows the user's references:** a library view with a full-width
   player bar, and a full-window Now Playing view tinted by the cover.

| Screen | Image |
| --- | --- |
| Home (idle, focused) | [01-home.png](01-home.png) |
| Sidebar expanded on hover | [01b-sidebar.png](01b-sidebar.png) |
| Looking up link (indeterminate progress) | [02-searching.png](02-searching.png) |
| Formats menu (hover = selection highlight) | [03-formats.png](03-formats.png), [960×640](03-formats-960x640.png) |
| Downloading | [04-downloading.png](04-downloading.png) |
| Saved | [05-done.png](05-done.png) |
| Files (Finder-style list, toolbar download indicator) | [06-files.png](06-files.png) |
| Video | [07-video.png](07-video.png) |
| Music library + player bar | [08-music.png](08-music.png) |
| Now Playing | [09-now-playing.png](09-now-playing.png) |
| Settings (System Settings-style groups) | [10-settings.png](10-settings.png) |

The app icon is unchanged from the Fluid proposal: `../2026-10-10/00-icon.png`.
Sources are in `src/` (`pro.css` holds the tokens). All names, artists, and
artwork are fictional sample data.

## Tokens

| Role | Value |
| --- | --- |
| Window | `#1c1c1e` |
| Raised group / card | `#242426` |
| Popover / dropdown | `#2a2a2d` |
| Field | `#2c2c2f` |
| Button | `#3a3a3d` |
| Separator | 8% white |
| Text / secondary / tertiary | `#f5f5f7` / `#a1a1a6` / `#6e6e73` |
| Accent (only for focus, selection, primary action, progress) | `#7b6cf0` |
| Success | `#30d158` |

Type: Segoe UI Variable (Windows), falling back to the system font. 13 px base, 15 px toolbar
titles, 17–22 px section and hero titles. Controls are 28 px high with 7 px
radius; the Home search bar is 46 px.

## Behaviour notes

- **Privacy:** after lookup, the raw URL is cleared from the bar and replaced by
  a "YouTube link" token. Only the site name is shown.
- **One click per decision:** Enter looks up the link; clicking a format
  downloads it. Escape or × clears the panel when nothing is running.
- **Downloads elsewhere:** other pages show a small progress ring with the
  percentage in the toolbar (see Files). Clicking it could open the same panel
  as a popover.
- **Files** is a Finder-style list with sortable columns, alternating rows, a
  selection highlight, and a status bar showing the item count, total size, and
  library path.

## Needs data the app doesn't have yet

- **Artist names** in Music. Reading ID3 tags from MP3 files is not in the
  library scan today. Without them, "From your library" is shown.
- **Lyrics.** The reference shows synced lyrics; Qtmedia has no lyrics source,
  so Now Playing shows "Up next" instead.
- **Music and video playback** themselves (the player milestones). Until then,
  Play opens the file in the system player and the player bar is idle.
- **Inspection thumbnail**, which is why the formats panel uses an icon tile.
