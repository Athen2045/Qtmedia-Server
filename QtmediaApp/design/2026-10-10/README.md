# Qtmedia "Fluid" redesign

Date: 2026-10-10. Status: **proposal, awaiting approval**. Replaces the
2026-10-09 Ink and Violet direction (implemented but rejected by the user).

User brief: redesign from the ground up, including the app icon: modern,
fluid, simplified. Decisions from the user: keep ink black + purple; collapsible
sidebar; app icon is a modern Q monogram.

| Screen | Image |
| --- | --- |
| App icon and wordmark | [00-icon.png](00-icon.png) |
| Home | [01-home.png](01-home.png), [960×640](01-home-960x640.png) |
| Sidebar expanded on hover | [01b-sidebar.png](01b-sidebar.png) |
| Choose quality | [02-formats.png](02-formats.png), [960×640](02-formats-960x640.png) |
| Saving | [03-downloading.png](03-downloading.png) |
| Files + download pill | [04-files.png](04-files.png) |
| Video (player coming soon) | [05-video.png](05-video.png) |
| Music (player coming soon) | [06-music.png](06-music.png) |
| Settings | [07-settings.png](07-settings.png) |

Sources are real HTML/CSS in `src/`. `fluid.css` holds the tokens and
`fluid.js` holds the Q logo, icon set, and sidebar. All titles, sizes, and
artwork are fictional sample data.

## What changed, and why it feels different

- **App icon.** A soft gradient ring (violet → pink) on an ink squircle. The ring
  opens at the bottom right, and a separate rounded play triangle forms the Q's
  tail. Checked from 300 px down to 16 px and on light and dark taskbars. The
  Bodoni "QT MEDIA" wordmark is retired in favour of a lowercase `qtmedia` set in
  the UI font.
- **Floating, collapsible sidebar.** A glass panel inset 12 px from the window
  edges. It shows icons only (68 px); on hover it expands to 224 px over the
  content, with labels and "Soon" tags, and never shifts the page. Coming-soon
  items show a small dot when collapsed.
- **New icon set.** Rounded 1.75 px line icons drawn for Qtmedia, replacing
  the filled Material Symbols. Video is a film strip, so it doesn't look like a
  third-party logo.
- **Fluid surfaces.** No table lines or hard dividers. Rounded glass cards
  (18–30 px), pill controls, and a faint violet/pink aurora on the ink canvas.
  The violet-to-pink gradient is used only for focus and progress: the link
  capsule rim, the selected quality, and progress rings.
- **Home talks to you.** "What should we save?" above one large capsule input,
  with "Jump back in" cards for the most recent saves.
- **Choosing is one decision.** A Video / Audio-only switch, then a single row
  of quality pills (4K, 1440p, 1080p…), then one button that says exactly what
  will happen ("Save 1080p video").
- **Saving is glanceable.** A large gradient progress ring with the percentage
  in the middle. On other pages, a floating pill shows a mini ring, title,
  percent, and a cancel button.
- **Files groups by time** (Today / This week / Earlier). Rows are borderless,
  and Open and Play appear on hover.
- **Settings looks like a modern OS settings page:** grouped rounded lists with
  small coloured badges.

## Typography

The UI uses Segoe UI Variable (Display for headings, Text for UI), which ships
with Windows 11. It falls back to Segoe UI on Windows 10 and to the system font
on macOS. No font downloads, and no bundled display font any more.

## Feasibility with today's engine

Everything except the music player itself uses data the app already has: site,
title, duration, available heights, bytes and percent, and library entries with
artwork, duration, size, and modified time. The formats card shows an icon tile
because inspection does not return a thumbnail. Until the players ship, Play
opens the file in the system player, and the music player bar shows an idle
state. The mockup shows the bar as it will look when playing.

## Implementation notes (after approval)

- Generate `src-tauri/icons/*` (ico, png sizes, icns) from the Q mark SVG.
- Replace `app.css` and the component structure for the new shell. Keep the
  existing bridge, session state, tests' accessibility contract, and privacy
  rules.
- Sidebar expansion: on hover and on keyboard focus within the sidebar, as an
  overlay (no layout shift), with a 180 ms ease. Respect reduced motion.
