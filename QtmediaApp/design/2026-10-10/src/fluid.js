// Mockup-only helpers: Q logo, rounded line icon set, and the floating sidebar.
let uid = 0;

// The Q monogram (100x100 grid). Ring centre (47,47) r=21, open from 20deg to
// 70deg; a detached rounded play triangle sits in the gap as the Q's tail,
// pointing down-right. The group is shifted (-3,-3) to centre the silhouette.
function qMark(size, { tile = true } = {}) {
  const id = `q${++uid}`;
  const ring = "M54.18 66.73 A21 21 0 1 1 66.73 54.18";
  const tri = "M63.26 74.58 L74.58 63.26 L78.75 78.75 Z";
  return `<svg width="${size}" height="${size}" viewBox="0 0 100 100" aria-hidden="true">
    <defs>
      <linearGradient id="${id}g" x1="18" y1="20" x2="80" y2="82" gradientUnits="userSpaceOnUse">
        <stop offset="0" stop-color="#6f7bff"/><stop offset=".5" stop-color="#9b6cff"/><stop offset="1" stop-color="#e65bd2"/>
      </linearGradient>
      <linearGradient id="${id}b" x1="0" y1="0" x2="0" y2="100" gradientUnits="userSpaceOnUse">
        <stop offset="0" stop-color="#1b1926"/><stop offset="1" stop-color="#0a0a10"/>
      </linearGradient>
      <radialGradient id="${id}r" cx="50" cy="38" r="60" gradientUnits="userSpaceOnUse">
        <stop offset="0" stop-color="#7a5cff" stop-opacity=".28"/><stop offset="1" stop-color="#7a5cff" stop-opacity="0"/>
      </radialGradient>
    </defs>
    ${tile ? `<rect x="4" y="4" width="92" height="92" rx="27" fill="url(#${id}b)"/>
    <rect x="4" y="4" width="92" height="92" rx="27" fill="url(#${id}r)"/>
    <rect x="4.5" y="4.5" width="91" height="91" rx="26.5" fill="none" stroke="rgba(255,255,255,.09)"/>` : ""}
    <g transform="translate(-3 -3)">
      <path d="${ring}" fill="none" stroke="url(#${id}g)" stroke-width="10.5" stroke-linecap="round"/>
      <path d="${tri}" fill="url(#${id}g)" stroke="url(#${id}g)" stroke-width="7" stroke-linejoin="round"/>
    </g>
  </svg>`;
}

const I = {
  home: '<path d="M4 10.4 12 4l8 6.4V18a2 2 0 0 1-2 2h-3.5v-5.5h-5V20H6a2 2 0 0 1-2-2z"/>',
  video: '<rect x="3.5" y="4" width="17" height="16" rx="3.5"/><path d="M8 4v16M16 4v16M3.5 9H8M3.5 15H8M16 9h4.5M16 15h4.5"/>',
  music: '<path d="M9 17.5V6.5l10-2v11"/><circle cx="6.5" cy="17.5" r="2.5"/><circle cx="16.5" cy="15.5" r="2.5"/>',
  files: '<path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H9l2 2.4h7.5A2.5 2.5 0 0 1 21 9.9v6.6a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 16.5z"/>',
  settings: '<path d="M4 7.5h9M17 7.5h3M4 16.5h3M11 16.5h9"/><circle cx="15" cy="7.5" r="2"/><circle cx="9" cy="16.5" r="2"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.3-4.3"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 0 0-5.66-5.66l-1 1"/><path d="M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 0 0 5.66 5.66l1-1"/>',
  paste: '<rect x="8" y="3.5" width="8" height="4" rx="1.5"/><path d="M8 5.5H7a2.5 2.5 0 0 0-2.5 2.5v10A2.5 2.5 0 0 0 7 20.5h10a2.5 2.5 0 0 0 2.5-2.5V8A2.5 2.5 0 0 0 17 5.5h-1"/>',
  download: '<path d="M12 4.5v10.5m0 0-4.2-4.2M12 15l4.2-4.2M5.5 19.5h13"/>',
  play: '<path d="M8.5 6.2v11.6a1 1 0 0 0 1.5.86l9.4-5.8a1 1 0 0 0 0-1.72L10 5.34a1 1 0 0 0-1.5.86z" fill="currentColor" stroke="none"/>',
  pause: '<rect x="7" y="5.5" width="3.5" height="13" rx="1.2" fill="currentColor" stroke="none"/><rect x="13.5" y="5.5" width="3.5" height="13" rx="1.2" fill="currentColor" stroke="none"/>',
  next: '<path d="M6 6.8v10.4a.8.8 0 0 0 1.25.66l7.4-5.2a.8.8 0 0 0 0-1.32l-7.4-5.2A.8.8 0 0 0 6 6.8z" fill="currentColor" stroke="none"/><path d="M18 6v12"/>',
  prev: '<path d="M18 6.8v10.4a.8.8 0 0 1-1.25.66l-7.4-5.2a.8.8 0 0 1 0-1.32l7.4-5.2A.8.8 0 0 1 18 6.8z" fill="currentColor" stroke="none"/><path d="M6 6v12"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  x: '<path d="M7 7l10 10M17 7 7 17"/>',
  chevron: '<path d="m7 10 5 5 5-5"/>',
  arrow: '<path d="M5 12h14m-5-5 5 5-5 5"/>',
  open: '<path d="M13.5 4.5h6v6M19.5 4.5l-8 8M18 14v3.5a2.5 2.5 0 0 1-2.5 2.5h-9A2.5 2.5 0 0 1 4 17.5v-9A2.5 2.5 0 0 1 6.5 6H10"/>',
  volume: '<path d="M4.5 9.5v5H8l4.5 4V5.5L8 9.5z"/><path d="M16 9.2a4 4 0 0 1 0 5.6M18.6 6.6a7.6 7.6 0 0 1 0 10.8"/>',
  lock: '<rect x="5" y="10.5" width="14" height="9.5" rx="3"/><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5"/>',
  info: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5M12 8h.01"/>',
  grid: '<rect x="4" y="4" width="7" height="7" rx="2"/><rect x="13" y="4" width="7" height="7" rx="2"/><rect x="4" y="13" width="7" height="7" rx="2"/><rect x="13" y="13" width="7" height="7" rx="2"/>',
  list: '<path d="M9 7h11M9 12h11M9 17h11"/><circle cx="5" cy="7" r=".6"/><circle cx="5" cy="12" r=".6"/><circle cx="5" cy="17" r=".6"/>',
  sparkle: '<path d="M12 4.5c.6 3.6 2 5 5.5 5.5-3.5.6-4.9 2-5.5 5.5-.6-3.5-2-4.9-5.5-5.5 3.5-.5 4.9-1.9 5.5-5.5z"/>',
  more: '<circle cx="6" cy="12" r="1.2" fill="currentColor"/><circle cx="12" cy="12" r="1.2" fill="currentColor"/><circle cx="18" cy="12" r="1.2" fill="currentColor"/>',
};

function icon(name, cls = "") {
  return `<svg class="ic ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${I[name]}</svg>`;
}

document.querySelectorAll("[data-logo]").forEach((el) => { el.outerHTML = qMark(+el.dataset.logo); });
document.querySelectorAll("[data-glyph]").forEach((el) => { el.outerHTML = qMark(+el.dataset.glyph, { tile: false }); });
document.querySelectorAll("[data-i]").forEach((el) => { el.outerHTML = icon(el.dataset.i, el.className); });

// App shell: floating sidebar (collapsed unless body[data-expanded]) + window controls.
const route = document.body.dataset.route;
if (route) {
  const expanded = document.body.hasAttribute("data-expanded");
  const item = (id, label, soon) => `<a class="nav${route === id ? " is-active" : ""}">${icon(id)}<span class="nav-label">${label}</span>${soon ? '<span class="nav-soon">Soon</span>' : ""}</a>`;
  const shell = document.createElement("div");
  shell.className = `shell${expanded ? " is-expanded" : ""}`;
  shell.innerHTML = `
    <aside class="sidebar">
      <div class="side-brand">${qMark(36)}<span class="wordmark wordmark--sm">qtmedia</span></div>
      <nav class="side-nav">${item("home", "Home")}${item("video", "Video", true)}${item("music", "Music", true)}${item("files", "Files")}</nav>
      <nav class="side-nav side-nav--end">${item("settings", "Settings")}</nav>
    </aside>
    <div class="winctl" aria-hidden="true">
      <span><svg viewBox="0 0 16 16"><path d="M3.5 8h9"/></svg></span>
      <span><svg viewBox="0 0 16 16"><rect x="3.5" y="3.5" width="9" height="9" rx="2"/></svg></span>
      <span><svg viewBox="0 0 16 16"><path d="m4.5 4.5 7 7m0-7-7 7"/></svg></span>
    </div>`;
  document.body.prepend(shell);
}
