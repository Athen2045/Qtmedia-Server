import { invoke } from "@tauri-apps/api/core";
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
    }
  | { event: "download_completed"; jobId: string; entry: LibraryEntry }
  | { event: "cancellation_requested"; jobId: string }
  | { event: "download_cancelled"; jobId: string }
  | { event: "library_changed"; entries?: LibraryEntry[] }
  | { event: "error"; code: string; jobId?: string };

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
  minimizeWindow(): Promise<void>;
  toggleMaximizeWindow(): Promise<void>;
  closeWindow(): Promise<void>;
  subscribe(listener: (event: DesktopEvent) => void): Promise<() => void>;
};

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
  minimizeWindow: () => invoke("window_minimize"),
  toggleMaximizeWindow: () => invoke("window_toggle_maximize"),
  closeWindow: () => invoke("window_close"),
  subscribe: async (listener) => {
    const unlisten = await listen<DesktopEvent>("desktop-event", ({ payload }) => {
      listener(payload);
    });
    return unlisten;
  },
};
