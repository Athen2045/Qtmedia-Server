import { useEffect, useState } from "react";

import type { DesktopBridge, LibraryEntry } from "./bridge";
import { applyRenames } from "./renames";

/** Older engines named files `Title [media-<id>].ext`; the app now renames them
 * at startup, but a tagged file added some other way is still shown clean. */
const MEDIA_ID_SUFFIX = / \[media-[A-Za-z0-9_-]+\]/;

/** Display name with extension; the on-disk ID is hidden. Use `relativePath` for actions. */
export function fileName(entry: LibraryEntry) {
  const name = entry.relativePath.split("/").at(-1) ?? entry.relativePath;
  return name.replace(MEDIA_ID_SUFFIX, "");
}

/** File name without its extension, for media titles in Video and Music. */
export function mediaTitle(entry: LibraryEntry) {
  const name = fileName(entry);
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(0, dot) : name;
}

export function formatBytes(bytes: number) {
  if (bytes === 0) return "0 KB";
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  if (bytes >= 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDuration(seconds: number) {
  const whole = Math.floor(seconds);
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const rest = String(whole % 60).padStart(2, "0");
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${rest}` : `${minutes}:${rest}`;
}

export function formatAdded(epochSeconds: number, now = Date.now()) {
  const date = new Date(epochSeconds * 1000);
  const today = new Date(now);
  if (date.toDateString() === today.toDateString()) return "Today";
  const sameYear = date.getFullYear() === today.getFullYear();
  return new Intl.DateTimeFormat(undefined, sameYear ? { month: "short", day: "numeric" } : { dateStyle: "medium" }).format(date);
}

export type LibraryState = {
  entries: LibraryEntry[];
  loading: boolean;
  failed: boolean;
  retry(): void;
};

/** Loads the active library and reloads when `refreshToken` changes. */
export function useLibrary(bridge: DesktopBridge, refreshToken = 0): LibraryState {
  const [entries, setEntries] = useState<LibraryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [retryToken, setRetryToken] = useState(0);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    setFailed(false);
    // Playlists and resume positions follow files renamed to clean names first.
    const renamed = bridge.libraryRenames?.().then(applyRenames, () => undefined) ?? Promise.resolve();
    void renamed.then(() => bridge.listLibrary()).then((items) => {
      if (!mounted) return;
      setEntries(items);
      setLoading(false);
    }).catch(() => {
      if (!mounted) return;
      setFailed(true);
      setLoading(false);
    });
    return () => { mounted = false; };
  }, [bridge, refreshToken, retryToken]);

  // New covers for videos that had none arrive later: reload quietly.
  useEffect(() => {
    let unlisten: (() => void) | null = null;
    let active = true;
    void bridge.subscribeArtwork?.(() => setRetryToken((value) => value + 1)).then((stop) => {
      if (active) unlisten = stop;
      else stop();
    }).catch(() => undefined);
    return () => {
      active = false;
      unlisten?.();
    };
  }, [bridge]);

  return { entries, loading, failed, retry: () => setRetryToken((value) => value + 1) };
}

export function newestFirst(entries: LibraryEntry[]) {
  return [...entries].sort((left, right) => right.modifiedAt - left.modifiedAt);
}
