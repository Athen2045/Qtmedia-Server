// Development-only stand-in for the Tauri bridge so the UI can run in a plain
// browser (`pnpm dev`). It is loaded only from `main.tsx` when Vite is in dev
// mode and the page is not inside Tauri, so it never ships in a release build.
// All titles, paths, and sizes are fictional sample data.
//
// Scenarios are chosen by keywords in the pasted link:
//   (any https link)  inspection succeeds, download progresses and completes
//   "unsupported"     unsupported_source        "noformats"  no_formats
//   "offline"         provider_unavailable      "audio"      MP3-only source
//   "unknown-size"    progress without totals   "fail"       download_failed midway
//   "slow"            10x slower timings
// and by page query parameters:
//   ?library=empty|error|full (default full)
import type { DesktopBridge, DesktopEvent, FormatOption, LibraryEntry, LibraryLocation, NetworkSettings } from "./bridge";

type Listener = (event: DesktopEvent) => void;

export type MockBridgeOptions = {
  library?: "empty" | "error" | "full";
  /** Multiplies every simulated delay; tests use 0. */
  timeScale?: number;
};

const DEFAULT_ROOT = "C:\\Users\\you\\AppData\\Roaming\\Qtmedia\\library";
const CUSTOM_ROOT = "D:\\Media\\Qtmedia\\library";
const DAY = 86_400;

const artworkPalette: Record<string, [string, string]> = {
  "artwork/night-drive.jpg": ["#5b5bf0", "#c35bd8"],
  "artwork/harbour-lights.jpg": ["#1f8a8a", "#3b5bdb"],
  "artwork/morning-loop.jpg": ["#d8a25b", "#d85b8a"],
  "artwork/field-notes.jpg": ["#3a7d44", "#a3c45b"],
  "artwork/glasshouse.jpg": ["#7a4fd8", "#4fb3d8"],
};

function sampleLibrary(now: number): LibraryEntry[] {
  const entry = (
    relativePath: string,
    sizeMb: number,
    daysAgo: number,
    durationSeconds: number | null,
    artworkPath: string | null,
  ): LibraryEntry => ({
    relativePath,
    mediaType: relativePath.startsWith("audio/") ? "audio" : "video",
    extension: relativePath.split(".").at(-1) ?? "",
    sizeBytes: Math.round(sizeMb * 1024 * 1024),
    modifiedAt: now - Math.round(daysAgo * DAY),
    durationSeconds,
    artworkPath,
  });
  return [
    entry("video/Night Drive (Official Video).mp4", 84.2, 0.2, 241, "artwork/night-drive.jpg"),
    entry("audio/Night Drive.mp3", 5.6, 0.2, 241, "artwork/night-drive.jpg"),
    entry("video/Harbour Lights - Live Session.mp4", 312.9, 2, 1325, "artwork/harbour-lights.jpg"),
    entry("audio/Morning Loop.mp3", 3.9, 5, 168, "artwork/morning-loop.jpg"),
    entry("video/Field Notes, Episode 4.mp4", 148.4, 9, 734, "artwork/field-notes.jpg"),
    entry("audio/Glasshouse.mp3", 7.1, 14, 302, "artwork/glasshouse.jpg"),
    entry("video/Untitled clip.mp4", 0.8, 31, null, null),
    entry("audio/A very long track title that keeps going to test truncation in narrow windows.mp3", 9.4, 60, 401, null),
  ];
}

/** A short generated WAV tone so the music player can be exercised in a browser. */
let toneUrl: string | null = null;
function mockToneUrl() {
  if (toneUrl) return toneUrl;
  const rate = 8000;
  const seconds = 20;
  const samples = rate * seconds;
  const buffer = new ArrayBuffer(44 + samples);
  const view = new DataView(buffer);
  const text = (offset: number, value: string) => [...value].forEach((char, index) => view.setUint8(offset + index, char.charCodeAt(0)));
  text(0, "RIFF"); view.setUint32(4, 36 + samples, true); text(8, "WAVE");
  text(12, "fmt "); view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, rate, true); view.setUint32(28, rate, true); view.setUint16(32, 1, true); view.setUint16(34, 8, true);
  text(36, "data"); view.setUint32(40, samples, true);
  for (let index = 0; index < samples; index += 1) {
    const t = index / rate;
    const envelope = 0.25 * (0.6 + 0.4 * Math.sin(2 * Math.PI * 0.5 * t));
    view.setUint8(44 + index, 128 + Math.round(127 * envelope * Math.sin(2 * Math.PI * 330 * t)));
  }
  toneUrl = URL.createObjectURL(new Blob([buffer], { type: "audio/wav" }));
  return toneUrl;
}

function artworkDataUrl(relativePath: string) {
  const [from, to] = artworkPalette[relativePath] ?? ["#444", "#888"];
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${from}"/><stop offset="1" stop-color="${to}"/></linearGradient></defs><rect width="96" height="96" fill="url(#g)"/><circle cx="66" cy="34" r="14" fill="rgba(255,255,255,.35)"/></svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

const videoFormats: FormatOption[] = [
  { key: "mock-2160", kind: "video", label: "2160p MP4", extension: "mp4", height: 2160, bitrateKbps: null },
  { key: "mock-1080", kind: "video", label: "1080p MP4", extension: "mp4", height: 1080, bitrateKbps: null },
  { key: "mock-720", kind: "video", label: "720p MP4", extension: "mp4", height: 720, bitrateKbps: null },
  { key: "mock-480", kind: "video", label: "480p MP4", extension: "mp4", height: 480, bitrateKbps: null },
  { key: "mock-360", kind: "video", label: "360p MP4", extension: "mp4", height: 360, bitrateKbps: null },
  { key: "mock-144", kind: "video", label: "144p MP4", extension: "mp4", height: 144, bitrateKbps: null },
];
const audioFormat: FormatOption = { key: "mock-mp3", kind: "audio", label: "MP3 · 192 kbps", extension: "mp3", height: null, bitrateKbps: 192 };

type Media = { mediaId: string; title: string; flags: Set<string>; formats: FormatOption[]; durationSeconds: number };
type Job = { jobId: string; timers: ReturnType<typeof setTimeout>[]; cancelled: boolean };

export function createMockBridge(options: MockBridgeOptions = {}): DesktopBridge {
  const scale = options.timeScale ?? 1;
  const libraryMode = options.library ?? "full";
  const listeners = new Set<Listener>();
  const media = new Map<string, Media>();
  const jobs = new Map<string, Job>();
  let library = libraryMode === "full" ? sampleLibrary(Math.floor(Date.now() / 1000)) : [];
  let location: LibraryLocation = { path: DEFAULT_ROOT, isDefault: true };
  let network: NetworkSettings = { doh: "off", proxy: null, cookies: "off" };
  let sequence = 0;

  const emit = (event: DesktopEvent) => listeners.forEach((listener) => listener(event));
  const later = (ms: number, run: () => void) => setTimeout(run, ms * scale);
  const nextId = (prefix: string) => `${prefix}-${++sequence}`;

  function runDownload(job: Job, item: Media, format: FormatOption) {
    const slow = item.flags.has("slow") ? 10 : 1;
    const totalBytes = Math.round((format.kind === "audio" ? 5.4 : format.height! / 12) * 1024 * 1024);
    const knownSize = !item.flags.has("unknown-size");
    const steps = 24;
    job.timers.push(later(300 * slow, () => emit({ event: "download_started", jobId: job.jobId })));
    for (let step = 1; step <= steps; step += 1) {
      job.timers.push(later((300 + step * 250) * slow, () => {
        if (item.flags.has("fail") && step === Math.floor(steps / 2)) {
          job.timers.forEach(clearTimeout);
          jobs.delete(job.jobId);
          emit({ event: "error", code: "download_failed", jobId: job.jobId });
          return;
        }
        const downloadedBytes = Math.round((totalBytes * step) / steps);
        emit({
          event: "download_progress",
          jobId: job.jobId,
          downloadedBytes,
          totalBytes: knownSize ? totalBytes : null,
          percent: knownSize ? (step / steps) * 100 : null,
        });
      }));
    }
    job.timers.push(later((300 + (steps + 1) * 250) * slow, () => {
      jobs.delete(job.jobId);
      const folder = format.kind === "audio" ? "audio" : "video";
      const entry: LibraryEntry = {
        relativePath: `${folder}/${item.title}${format.kind === "video" ? ` (${format.height}p)` : ""}.${format.extension}`,
        mediaType: format.kind,
        extension: format.extension,
        sizeBytes: totalBytes,
        modifiedAt: Math.floor(Date.now() / 1000),
        durationSeconds: item.durationSeconds,
        artworkPath: "artwork/glasshouse.jpg",
      };
      library = [entry, ...library.filter((existing) => existing.relativePath !== entry.relativePath)];
      emit({ event: "download_completed", jobId: job.jobId, entry });
    }));
  }

  const bridge: DesktopBridge = {
    async inspectLink(url) {
      const text = url.toLowerCase();
      const flags = new Set(["unsupported", "noformats", "offline", "audio", "unknown-size", "fail", "slow"].filter((flag) => text.includes(flag)));
      const slow = flags.has("slow") ? 10 : 1;
      emit({ event: "inspection_started" });
      later(900 * slow, () => {
        if (!/^https?:\/\/[^\s/]+/i.test(url.trim())) return emit({ event: "error", code: "invalid_url" });
        if (flags.has("unsupported")) return emit({ event: "error", code: "unsupported_source" });
        if (flags.has("offline")) return emit({ event: "error", code: "provider_unavailable" });
        if (flags.has("noformats")) return emit({ event: "error", code: "no_formats" });
        const item: Media = {
          mediaId: nextId("media"),
          title: flags.has("audio") ? "Glasshouse" : "Harbour Lights - Live Session",
          flags,
          formats: flags.has("audio") ? [audioFormat] : [...videoFormats, audioFormat],
          durationSeconds: flags.has("audio") ? 302 : 1325,
        };
        media.set(item.mediaId, item);
        emit({ event: "inspection_ready", mediaId: item.mediaId, title: item.title, site: flags.has("audio") ? "SoundCloud" : "YouTube", durationSeconds: item.durationSeconds, formats: item.formats });
      });
    },
    async startDownload(mediaId, formatKey) {
      const item = media.get(mediaId);
      const format = item?.formats.find((candidate) => candidate.key === formatKey);
      if (!item || !format) throw { code: "format_unavailable" };
      const job: Job = { jobId: nextId("job"), timers: [], cancelled: false };
      jobs.set(job.jobId, job);
      runDownload(job, item, format);
    },
    async cancelDownload(jobId) {
      const job = jobs.get(jobId);
      if (!job || job.cancelled) return;
      job.cancelled = true;
      job.timers.forEach(clearTimeout);
      emit({ event: "cancellation_requested", jobId });
      later(700, () => {
        jobs.delete(jobId);
        emit({ event: "download_cancelled", jobId });
      });
    },
    async listLibrary() {
      await new Promise((resolve) => later(250, () => resolve(undefined)));
      if (libraryMode === "error") throw { code: "storage_unavailable" };
      return library;
    },
    async openMedia(relativePath) {
      console.info("[mock bridge] open media", relativePath);
    },
    async openLibrary() {
      console.info("[mock bridge] open library folder", location.path);
    },
    async readArtwork(relativePath) {
      return artworkDataUrl(relativePath);
    },
    async getDownloadLocation() {
      return location;
    },
    async chooseDownloadLocation() {
      if (jobs.size > 0) throw { code: "storage_busy" };
      location = { path: CUSTOM_ROOT, isDefault: false };
      return location;
    },
    async useDefaultDownloadLocation() {
      if (jobs.size > 0) throw { code: "storage_busy" };
      location = { path: DEFAULT_ROOT, isDefault: true };
      return location;
    },
    async getNetworkSettings() {
      return network;
    },
    async setNetworkSettings(doh, proxy, cookies) {
      if (jobs.size > 0) throw { code: "storage_busy" };
      if (proxy && !/^(https?|socks4a?|socks5h?):\/\/[^\s/:]+:\d+$/.test(proxy.replace(/\/\/[^@]*@/, "//"))) throw "invalid_proxy";
      network = { doh, proxy: proxy || null, cookies };
      return network;
    },
    async minimizeWindow() {
      console.info("[mock bridge] minimize window");
    },
    async toggleMaximizeWindow() {
      console.info("[mock bridge] toggle maximize window");
    },
    async closeWindow() {
      console.info("[mock bridge] close window");
    },
    async readLyrics(relativePath) {
      // Sample synced lyrics (fictional) timed to the 20 s mock tone.
      if (!relativePath.endsWith("Night Drive.mp3")) return null;
      return ["[00:00.50] Headlights on the empty road", "[00:03.20] Radio low, the city glows", "[00:06.00] Every sign a little brighter",
        "[00:08.80] Hold the wheel and hold on tighter", "[00:11.60] Night drive, take the long way home", "[00:14.40] Night drive, we were never alone",
        "[00:17.20] ", "[00:18.40] Fade out slow"].join(String.fromCharCode(10));
    },
    async deleteMedia(relativePaths) {
      await new Promise((resolve) => later(300, () => resolve(undefined)));
      const removed = relativePaths.filter((path) => library.some((entry) => entry.relativePath === path));
      library = library.filter((entry) => !removed.includes(entry.relativePath));
      return { removed, failed: relativePaths.length - removed.length };
    },
    mediaUrl() {
      return mockToneUrl();
    },
    async appVersion() {
      return "0.1.0-dev";
    },
    async subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
  return bridge;
}

export function mockOptionsFromLocation(search: string): MockBridgeOptions {
  const library = new URLSearchParams(search).get("library");
  return { library: library === "empty" || library === "error" ? library : "full" };
}
