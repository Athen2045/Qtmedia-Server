import type { ReactNode, SVGProps } from "react";

// Qtmedia's own rounded line icons (24px grid, 1.75 stroke). Filled shapes are
// marked with `fill="currentColor" stroke="none"`. Shapes with class "duo" get
// a soft tint fill when the icon is selected (see .duo in app.css).
const paths = {
  home: <><path className="duo" d="M4.5 10.3 12 4.4l7.5 5.9v8.2A1.5 1.5 0 0 1 18 20h-3.5v-4.6a1.2 1.2 0 0 0-1.2-1.2h-2.6a1.2 1.2 0 0 0-1.2 1.2V20H6a1.5 1.5 0 0 1-1.5-1.5z" /></>,
  video: <><rect className="duo" x="3" y="5" width="18" height="14" rx="4" /><path d="M10.3 9.6v4.8a.6.6 0 0 0 .9.52l4-2.4a.6.6 0 0 0 0-1.04l-4-2.4a.6.6 0 0 0-.9.52z" fill="currentColor" strokeWidth="1" /></>,
  music: <><path d="M9 17.5V7.2a1 1 0 0 1 .8-.98l8.5-1.7a1 1 0 0 1 1.2.98V15.5M9 10.4l10.5-2.1" /><circle className="duo" cx="6.5" cy="17.5" r="2.5" /><circle className="duo" cx="17" cy="15.5" r="2.5" /></>,
  files: <><path className="duo" d="M3.5 7.5a2 2 0 0 1 2-2h3.6a2 2 0 0 1 1.4.58l1.1 1.1a2 2 0 0 0 1.4.58h5.5a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z" /><path d="M3.5 10.5h17" /></>,
  settings: <><path d="M4 7h9M17 7h3M4 12h3M11 12h9M4 17h11M19 17h1" /><circle className="duo" cx="15" cy="7" r="2" /><circle className="duo" cx="9" cy="12" r="2" /><circle className="duo" cx="17" cy="17" r="2" /></>,
  search: <><circle cx="11" cy="11" r="6.5" /><path d="m20 20-4.3-4.3" /></>,
  link: <><path d="M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 0 0-5.66-5.66l-1 1" /><path d="M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 0 0 5.66 5.66l1-1" /></>,
  clipboard: <><rect x="8" y="3.5" width="8" height="4" rx="1.5" /><path d="M8 5.5H7a2.5 2.5 0 0 0-2.5 2.5v10A2.5 2.5 0 0 0 7 20.5h10a2.5 2.5 0 0 0 2.5-2.5V8A2.5 2.5 0 0 0 17 5.5h-1" /></>,
  download: <path d="M12 4.5v10.5m0 0-4.2-4.2M12 15l4.2-4.2M5.5 19.5h13" />,
  trash: <path d="M4.5 7h15M9.5 7V5.5A1.5 1.5 0 0 1 11 4h2a1.5 1.5 0 0 1 1.5 1.5V7m-8 0 .8 11.1A2 2 0 0 0 8.3 20h7.4a2 2 0 0 0 2-1.9L18.5 7M10.5 11v5M13.5 11v5" />,
  lyrics: <><path d="M5 18V12.5C5 9 6.8 6.8 10 6M13 18v-5.5C13 9 14.8 6.8 18 6" /><rect x="4.5" y="12.5" width="5" height="5.5" rx="1.2" /><rect x="12.5" y="12.5" width="5" height="5.5" rx="1.2" /></>,
  check: <path d="m5 12.5 4.5 4.5L19 7.5" />,
  plus: <path d="M12 5v14M5 12h14" />,
  back: <path d="m14.5 6-6 6 6 6" />,
  pencil: <path d="M14.5 5.5l4 4M4.5 19.5l1-4.5L15.8 4.7a1.8 1.8 0 0 1 2.5 0l1 1a1.8 1.8 0 0 1 0 2.5L9 18.5z" />,
  grip: <g fill="currentColor" stroke="none"><circle cx="9" cy="7" r="1.3" /><circle cx="15" cy="7" r="1.3" /><circle cx="9" cy="12" r="1.3" /><circle cx="15" cy="12" r="1.3" /><circle cx="9" cy="17" r="1.3" /><circle cx="15" cy="17" r="1.3" /></g>,
  playlist: <><path d="M4 6.5h11M4 11.5h11M4 16.5h6" /><path d="M18 18.5V9.5l3-1" /><circle cx="16" cy="18.5" r="2" /></>,
  addToPlaylist: <><path d="M4 6.5h11M4 11.5h11M4 16.5h7" /><path d="M18 13.5v7M14.5 17h7" /></>,
  close: <path d="M7 7l10 10M17 7 7 17" />,
  chevron: <path d="m7 10 5 5 5-5" />,
  arrow: <path d="M5 12h14m-5-5 5 5-5 5" />,
  open: <path d="M13.5 4.5h6v6M19.5 4.5l-8 8M18 14v3.5a2.5 2.5 0 0 1-2.5 2.5h-9A2.5 2.5 0 0 1 4 17.5v-9A2.5 2.5 0 0 1 6.5 6H10" />,
  folder: <path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H9l2 2.4h7.5A2.5 2.5 0 0 1 21 9.9v6.6a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 16.5z" />,
  volume: <><path d="M4.5 9.5v5H8l4.5 4V5.5L8 9.5z" /><path d="M16 9.2a4 4 0 0 1 0 5.6M18.6 6.6a7.6 7.6 0 0 1 0 10.8" /></>,
  mute: <><path d="M4.5 9.5v5H8l4.5 4V5.5L8 9.5z" /><path d="m16 9.5 5 5m0-5-5 5" /></>,
  lock: <><rect x="5" y="10.5" width="14" height="9.5" rx="3" /><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5" /></>,
  info: <><circle cx="12" cy="12" r="8.5" /><path d="M12 11v5M12 8h.01" /></>,
  queue: <><path d="M4 7h12M4 12h12M4 17h7" /><path d="M17 14v6l4-3z" fill="currentColor" /></>,
  shuffle: <path d="M4 7h3.5c2 0 3 1 4.2 3l1.6 3c1.2 2 2.2 3 4.2 3H20M4 17h3.5c1.3 0 2.2-.4 3-1.2M14.5 8.2c.8-.8 1.7-1.2 3-1.2H20M17.5 4.5 20 7l-2.5 2.5M17.5 14.5 20 17l-2.5 2.5" />,
  repeat: <path d="M5 11V9.5A2.5 2.5 0 0 1 7.5 7H19m-2.5-2.5L19 7l-2.5 2.5M19 13v1.5a2.5 2.5 0 0 1-2.5 2.5H5m2.5 2.5L5 17l2.5-2.5" />,
  repeatOne: <><path d="M5 11V9.5A2.5 2.5 0 0 1 7.5 7H19m-2.5-2.5L19 7l-2.5 2.5M19 13v1.5a2.5 2.5 0 0 1-2.5 2.5H5m2.5 2.5L5 17l2.5-2.5" /><path d="M11.5 10.5 12.6 10v4.2" /></>,
  play: <path d="M8.5 6.2v11.6a1 1 0 0 0 1.5.86l9.4-5.8a1 1 0 0 0 0-1.72L10 5.34a1 1 0 0 0-1.5.86z" fill="currentColor" stroke="none" />,
  pause: <><rect x="7" y="5.5" width="3.5" height="13" rx="1.2" fill="currentColor" stroke="none" /><rect x="13.5" y="5.5" width="3.5" height="13" rx="1.2" fill="currentColor" stroke="none" /></>,
  next: <><path d="M6 6.8v10.4a.8.8 0 0 0 1.25.66l7.4-5.2a.8.8 0 0 0 0-1.32l-7.4-5.2A.8.8 0 0 0 6 6.8z" fill="currentColor" stroke="none" /><path d="M18 6v12" /></>,
  prev: <><path d="M18 6.8v10.4a.8.8 0 0 1-1.25.66l-7.4-5.2a.8.8 0 0 1 0-1.32l7.4-5.2A.8.8 0 0 1 18 6.8z" fill="currentColor" stroke="none" /><path d="M6 6v12" /></>,
  minimize: <path d="M5 12h14" />,
  maximize: <rect x="5.5" y="5.5" width="13" height="13" rx="2" />,
} satisfies Record<string, ReactNode>;

export type IconName = keyof typeof paths;

export function Icon({ name, ...props }: { name: IconName } & SVGProps<SVGSVGElement>) {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" {...props}>
      {paths[name]}
    </svg>
  );
}
