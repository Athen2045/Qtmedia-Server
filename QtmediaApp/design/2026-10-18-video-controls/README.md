# Video player controls (2026-10-18)

Approved by the user on 2026-10-18 with these choices: keep the ±10 s buttons
in the bar, drop picture-in-picture, keep Speed in the settings menu.
Implemented the same day (`frontend/src/components/VideoControls.tsx`).

- `01-window.png`: title row has only Close and the title; one bar holds
  Previous · −10 · Play · +10 · Next | volume · time · seek | CC · settings · full screen
  (the PiP button in the mockup was dropped).
- `02-settings.png`: gear menu with Stable volume and Autoplay switches,
  Subtitles and Speed pages.
- `03-subtitles.png`: Off / tracks / Add subtitle file….
- `04-fullscreen-2560.png`: the bar keeps its window size in full screen.

`mockup.html` renders each view (`#window`, `#settings`, `#subtitles`, `#fullscreen`).
