import type { FormatOption } from "./bridge";

/** Home's search mode: Video saves the highest resolution, Music saves FLAC. */
export type SearchMode = "video" | "music";

const MODE_KEY = "qtmedia.searchMode";
type StorageLike = Pick<Storage, "getItem" | "setItem">;

function defaultStorage(): StorageLike | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

/** The format a mode downloads automatically, or null when the link has none. */
export function pickFormat(formats: FormatOption[], mode: SearchMode): string | null {
  if (mode === "music") return formats.find((format) => format.kind === "audio" && format.extension === "flac")?.key ?? null;
  const videos = formats.filter((format) => format.kind === "video");
  if (!videos.length) return null;
  return videos.reduce((best, format) => ((format.height ?? 0) > (best.height ?? 0) ? format : best)).key;
}

export function readSearchMode(storage: StorageLike | null = defaultStorage()): SearchMode {
  try {
    return storage?.getItem(MODE_KEY) === "music" ? "music" : "video";
  } catch {
    return "video";
  }
}

export function writeSearchMode(mode: SearchMode, storage: StorageLike | null = defaultStorage()) {
  try {
    storage?.setItem(MODE_KEY, mode);
  } catch {
    // A remembered mode is a convenience only.
  }
}
