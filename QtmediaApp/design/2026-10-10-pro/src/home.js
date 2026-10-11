// Builds the Home mockup for body[data-state]: idle | searching | formats | downloading | done.
const state = document.body.dataset.state || "idle";
const title = "Harbour Lights - Live Session";

const field = {
  idle: `<span data-i="link" class="ic"></span><span class="caret"></span><span class="ph">Paste a video or music link</span><span class="field-actions"><span class="btn btn-plain"><span data-i="paste" class="ic-sm"></span>Paste</span><kbd class="kbd">↵</kbd></span>`,
  searching: `<span data-i="link" class="ic"></span><span class="val">https://www.youtube.com/watch?v=sample</span><span class="field-actions"><span class="spin"></span></span>`,
  token: `<span data-i="link" class="ic"></span><span class="token"><span data-i="check" class="ic-sm"></span>YouTube link</span><span class="grow"></span><span class="field-actions"><span class="btn btn-icon btn-plain"><span data-i="x" class="ic-sm"></span></span></span>`,
}[state === "idle" ? "idle" : state === "searching" ? "searching" : "token"];

const head = `<div class="p-head"><div class="art a0 p-thumb"><span data-i="video" class="ic-lg"></span></div><div class="p-title"><strong>${title}</strong><span>YouTube · 22:05</span></div></div>`;

const row = (q, d, hover) => `<div class="p-row${hover ? " is-hover" : ""}"><b>${q}</b><span>${d}</span><span class="p-dl"><span data-i="download" class="ic-sm"></span>${hover ? "Download" : ""}</span></div>`;

const panels = {
  idle: "",
  searching: `<div class="panel">
      <div class="p-search"><div class="p-search-line"><strong>Looking up link…</strong><span class="t3">youtube.com</span></div><div class="bar bar--indeterminate"><i></i></div><span class="t3 p-note">Checking which video and audio formats are available.</span></div>
    </div>`,
  formats: `<div class="panel">${head}
      <div class="p-list">
        <div class="p-label">Video · MP4</div>
        ${row("4K", "2160p")}${row("1440p", "QHD")}${row("1080p", "Full HD", true)}${row("720p", "HD")}${row("480p", "SD")}
        <div class="p-label">Audio</div>
        ${row("MP3", "192 kbps")}
      </div>
      <div class="p-foot"><span class="t3">Click a format to download it to your Library.</span></div>
    </div>`,
  downloading: `<div class="panel">${head}
      <div class="p-progress">
        <div class="p-progress-line"><strong>Downloading 1080p</strong><span class="pct">42%</span></div>
        <div class="bar bar--lg"><i style="width:42%"></i></div>
        <div class="p-progress-line t3"><span>26.3 MB of 62.5 MB · MP4</span><span class="btn btn-default">Cancel</span></div>
      </div>
    </div>`,
  done: `<div class="panel">${head}
      <div class="p-done">
        <span class="ok"><span data-i="check" class="ic"></span></span>
        <div><strong>Saved to your Library</strong><span class="t3">Harbour Lights - Live Session.mp4 · 62.5 MB</span></div>
        <span class="grow"></span>
        <span class="btn btn-default">Show in Files</span><span class="btn btn-accent"><span data-i="play" class="ic-sm"></span>Play</span>
      </div>
    </div>`,
};

document.querySelector("main").innerHTML = `
  <div class="home${state === "idle" ? "" : " is-active"}">
    <div class="intro"><span data-logo="56"></span><h2>Qtmedia</h2><p>Save videos and music from a link. Everything stays on this device.</p></div>
    <div class="search${state === "idle" ? " is-focused" : ""}">${field}</div>
    ${panels[state]}
  </div>`;
