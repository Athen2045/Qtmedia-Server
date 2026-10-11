import { convertFileSrc, invoke } from "@tauri-apps/api/core";

import type { DownloadStage } from "./progress";
import { getVersion } from "@tauri-apps/api/app";
import { listen } from "@tauri-apps/api/event";

export type MediaKind = "audio" | "video";

export type FormatOption = {
  key: string;
  kind: MediaKind;
  label: string;
  extension: string;
  height: number | null;
  bitrateKbps: number | null;
};

export type LibraryEntry = {
  relativePath: string;
  mediaType: MediaKind;
  extension: string;
  sizeBytes: number;
  modifiedAt: number;
  durationSeconds: number | null;
  artworkPath: string | null;
};

export type LibraryLocation = {
  path: string;
  isDefault: boolean;
};

export type DohProvider = "off" | "cloudflare" | "google" | "quad9";

export type CookieSource = "off" | "firefox";

export type NetworkSettings = {
  doh: DohProvider;
  proxy: string | null;
  /** Reuse Firefox's cookies for sites behind a Cloudflare challenge. */
  cookies: CookieSource;
};

export type TrackInfo = {
  title: string | null;
  artist: string | null;
  album: string | null;
  durationSeconds: number | null;
};

export type YtdlpChannel = "stable" | "nightly";

/** The yt-dlp the media engine runs: the bundled copy or a verified update. */
export type YtdlpStatus = {
  version: string;
  source: "bundled" | "updated";
  channel: YtdlpChannel | null;
};

export type YtdlpUpdateResult = YtdlpStatus & { status: "updated" | "current" };

export type DesktopEvent =
  | { event: "inspection_started" }
  | {
      event: "inspection_ready";
      mediaId: string;
      title: string;
      site: string;
      durationSeconds: number | null;
      formats: FormatOption[];
    }
  | { event: "download_started"; jobId: string }
  | {
      event: "download_progress";
      jobId: string;
      downloadedBytes: number;
      totalBytes: number | null;
      percent: number | null;
      /** Omitted by older engines: treated as one stream downloading. */
      stage?: DownloadStage;
      stream?: "video" | "audio" | null;
      part?: number;
      parts?: number;
    }
  | { event: "download_completed"; jobId: string; entry: LibraryEntry }
  | { event: "cancellation_requested"; jobId: string }
  | { event: "download_cancelled"; jobId: string }
  | { event: "library_changed"; entries?: LibraryEntry[] }
  | { event: "error"; code: string; jobId?: string };

/** How a library video plays (see the host's playback preparer). */
export type PlaybackPlan =
  | { kind: "direct" }
  | { kind: "ready"; url: string }
  | { kind: "preparing"; id: string; mode: "remux" | "transcode" | "preparing" };

export type PlaybackEvent =
  | { type: "progress"; id: string; percent: number }
  | { type: "ready"; id: string; url: string }
  | { type: "error"; id: string; code: string };

export type AudioOutputMode = "shared" | "exclusive";
export type AudioRateMismatch = "strict" | "resample";

/** Saved native-audio choice (`deviceId: null` follows the Windows default). */
export type AudioSettings = {
  deviceId: string | null;
  mode: AudioOutputMode;
  rateMismatch: AudioRateMismatch;
  exclusiveVolume: boolean;
};

export type AudioTransport = "wired" | "bluetooth" | "bluetoothHandsFree";

export type AudioDevice = { id: string; name: string; transport: AudioTransport; isDefault: boolean };

/** What the engine is doing with the current song, from file to device. */
export type SignalPath = {
  source: { codec: "flac" | "mp3"; sampleRate: number; channels: number; bitsPerSample: number | null };
  output: { mode: AudioOutputMode; sampleRate: number; channels: number; bits: number; containerBits: number; float: boolean };
  bitPerfect: boolean;
  /** Why it is not bit-perfect or not exclusive (e.g. `shared_mode`, `bluetooth_output`). */
  reason: string | null;
  device: { name: string; transport: AudioTransport } | null;
  /** Strict exclusive mode: software volume is off (use the DAC or amplifier). */
  volumeLocked?: boolean;
};

export type AudioEvent =
  | { type: "state"; state: "idle" | "loading" | "playing" | "paused" | "stopped" }
  | { type: "position"; seconds: number }
  | { type: "trackStarted"; path: string | null; durationSeconds: number | null; source: SignalPath["source"] }
  | { type: "trackEnded"; path: string | null }
  | ({ type: "signalPath" } & SignalPath)
  | { type: "deviceOpened" }
  | { type: "deviceReleased" }
  | { type: "error"; code: string }
  | { type: "deviceChanged"; devices: AudioDevice[]; fallback: boolean };

/** The native audio engine (desktop only). Paths are library-relative. */
export type NativeAudio = {
  play(relativePath: string, startSeconds?: number): Promise<void>;
  pause(): Promise<void>;
  resume(): Promise<void>;
  seek(seconds: number): Promise<void>;
  stop(): Promise<void>;
  /** Pause and give the device back now (the video player opened). */
  release(): Promise<void>;
  setVolume(volume: number): Promise<void>;
  /** The song after the current one, for gapless playback. */
  setNext(relativePath: string | null): Promise<void>;
  devices(): Promise<AudioDevice[]>;
  getSettings(): Promise<AudioSettings>;
  setSettings(settings: AudioSettings): Promise<AudioSettings>;
  subscribe(listener: (event: AudioEvent) => void): Promise<() => void>;
};

export type DesktopBridge = {
  inspectLink(url: string): Promise<void>;
  startDownload(mediaId: string, formatKey: string): Promise<void>;
  cancelDownload(jobId: string): Promise<void>;
  listLibrary(): Promise<LibraryEntry[]>;
  openMedia(relativePath: string): Promise<void>;
  openLibrary(): Promise<void>;
  readArtwork(relativePath: string): Promise<string | null>;
  getDownloadLocation(): Promise<LibraryLocation>;
  chooseDownloadLocation(): Promise<LibraryLocation | null>;
  useDefaultDownloadLocation(): Promise<LibraryLocation>;
  /** DNS-over-HTTPS and proxy routing for the media engine. */
  getNetworkSettings?(): Promise<NetworkSettings>;
  setNetworkSettings?(doh: DohProvider, proxy: string | null, cookies: CookieSource): Promise<NetworkSettings>;
  /** yt-dlp version in use, and a signed update from GitHub (restarts the engine). */
  getYtdlpStatus?(): Promise<YtdlpStatus>;
  updateYtdlp?(channel: YtdlpChannel): Promise<YtdlpUpdateResult>;
  minimizeWindow(): Promise<void>;
  toggleMaximizeWindow(): Promise<void>;
  /** Files → Import: pick music and videos to copy into the library (null if cancelled). */
  importMedia?(): Promise<{ imported: string[]; skipped: number } | null>;
  /** MKV/MOV/AVI and other videos the webview can't play as they are get a prepared copy. */
  preparePlayback?(relativePath: string, support?: { dolby: boolean }): Promise<PlaybackPlan>;
  cancelPlayback?(id: string): Promise<void>;
  subscribePlayback?(listener: (event: PlaybackEvent) => void): Promise<() => void>;
  /** Makes the whole app window full screen (the video player uses it). */
  setFullscreen?(fullscreen: boolean): Promise<void>;
  closeWindow(): Promise<void>;
  /** Text of a `.lrc` file next to a library song, if there is one. */
  readLyrics?(relativePath: string): Promise<string | null>;
  /** Title/artist/album tags and duration of a library song, for matching lyrics. */
  readTrackInfo?(relativePath: string): Promise<TrackInfo | null>;
  /** Saves lyrics found online as the song's `.lrc` (never replaces one). */
  saveLyrics?(relativePath: string, text: string): Promise<boolean>;
  /** Moves library media to the Recycle Bin; returns what was removed. */
  deleteMedia?(relativePaths: string[]): Promise<{ removed: string[]; failed: number }>;
  /** Playable URL for a library audio file, served by the Rust `qtmedia://` scheme. */
  mediaUrl?(relativePath: string): string;
  /** Application version from the Tauri config; optional so test bridges may omit it. */
  appVersion?(): Promise<string>;
  /** Native audio engine (bit-perfect/exclusive output); absent in the browser preview. */
  audio?: NativeAudio;
  subscribe(listener: (event: DesktopEvent) => void): Promise<() => void>;
};

/** Engine replies carry `event`; an `error` event becomes a rejected `{code}`. */
function engineResult<T>(value: unknown): T {
  const reply = (value ?? {}) as { event?: string; code?: string };
  if (reply.event === "error") throw { code: reply.code ?? "operation_failed" };
  return value as T;
}

export const desktopBridge: DesktopBridge = {
  inspectLink: (url) => invoke("inspect_link", { url }),
  startDownload: (mediaId, formatKey) =>
    invoke("start_download", { mediaId, formatKey }),
  cancelDownload: (jobId) => invoke("cancel_download", { jobId }),
  listLibrary: () => invoke<LibraryEntry[]>("list_library"),
  openMedia: (relativePath) => invoke("open_media", { relativePath }),
  openLibrary: () => invoke("open_library"),
  readArtwork: (relativePath) => invoke<string>("read_artwork", { relativePath }),
  getDownloadLocation: () => invoke<LibraryLocation>("get_download_location"),
  chooseDownloadLocation: () => invoke<LibraryLocation | null>("choose_download_location"),
  useDefaultDownloadLocation: () => invoke<LibraryLocation>("use_default_download_location"),
  getNetworkSettings: () => invoke<NetworkSettings>("get_network_settings"),
  setNetworkSettings: (doh, proxy, cookies) => invoke<NetworkSettings>("set_network_settings", { doh, proxy, cookies }),
  getYtdlpStatus: async () => engineResult<YtdlpStatus>(await invoke("get_ytdlp_status")),
  updateYtdlp: async (channel) => engineResult<YtdlpUpdateResult>(await invoke("update_ytdlp", { channel })),
  minimizeWindow: () => invoke("window_minimize"),
  toggleMaximizeWindow: () => invoke("window_toggle_maximize"),
  setFullscreen: (fullscreen) => invoke("window_set_fullscreen", { fullscreen }),
  importMedia: () => invoke<{ imported: string[]; skipped: number } | null>("import_media"),
  preparePlayback: (relativePath, support) => invoke<PlaybackPlan>("prepare_playback", { relativePath, dolby: support?.dolby ?? false }),
  cancelPlayback: (id) => invoke("cancel_playback", { id }),
  subscribePlayback: async (listener) => listen<PlaybackEvent>("playback-prepare", ({ payload }) => listener(payload)),
  closeWindow: () => invoke("window_close"),
  readLyrics: (relativePath) => invoke<string | null>("read_lyrics", { relativePath }),
  readTrackInfo: (relativePath) => invoke<TrackInfo | null>("read_track_info", { relativePath }),
  saveLyrics: (relativePath, text) => invoke<boolean>("save_lyrics", { relativePath, text }),
  deleteMedia: (relativePaths) => invoke<{ removed: string[]; failed: number }>("delete_media", { relativePaths }),
  mediaUrl: (relativePath) => convertFileSrc(relativePath, "qtmedia"),
  appVersion: () => getVersion(),
  audio: {
    play: (relativePath, startSeconds) => invoke("audio_play", { relativePath, startSeconds: startSeconds ?? null }),
    pause: () => invoke("audio_pause"),
    resume: () => invoke("audio_resume"),
    seek: (seconds) => invoke("audio_seek", { seconds }),
    stop: () => invoke("audio_stop"),
    release: () => invoke("audio_release"),
    setVolume: (volume) => invoke("audio_set_volume", { volume }),
    setNext: (relativePath) => invoke("audio_set_next", { relativePath }),
    devices: () => invoke<AudioDevice[]>("audio_devices"),
    getSettings: () => invoke<AudioSettings>("audio_get_settings"),
    setSettings: (settings) => invoke<AudioSettings>("audio_set_settings", { settings }),
    subscribe: async (listener) => listen<AudioEvent>("audio-event", ({ payload }) => listener(payload)),
  },
  subscribe: async (listener) => {
    const unlisten = await listen<DesktopEvent>("desktop-event", ({ payload }) => {
      listener(payload);
    });
    return unlisten;
  },
};
