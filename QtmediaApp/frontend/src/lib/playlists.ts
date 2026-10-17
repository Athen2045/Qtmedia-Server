import { useMemo, useSyncExternalStore } from "react";

/**
 * User playlists. They hold library-relative paths only (never file contents)
 * and live in this app's local storage, so they stay on this device. Songs that
 * are later deleted or moved simply drop out of the playlist when shown.
 */
export type Playlist = { id: string; name: string; paths: string[]; createdAt: number; updatedAt: number };

const STORAGE_KEY = "qtmedia.playlists.v1";
export const MAX_PLAYLIST_NAME = 80;

const listeners = new Set<() => void>();
let snapshot: Playlist[] | null = null;

function isPlaylist(value: unknown): value is Playlist {
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  return typeof item.id === "string" && typeof item.name === "string" && Array.isArray(item.paths)
    && item.paths.every((path) => typeof path === "string") && typeof item.createdAt === "number" && typeof item.updatedAt === "number";
}

function read(): Playlist[] {
  if (snapshot) return snapshot;
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "[]");
    snapshot = Array.isArray(parsed) ? parsed.filter(isPlaylist) : [];
  } catch {
    snapshot = [];
  }
  return snapshot;
}

function write(next: Playlist[]) {
  snapshot = next;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // Storage full or unavailable: keep the in-memory copy for this session.
  }
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  const onStorage = (event: StorageEvent) => {
    if (event.key !== STORAGE_KEY) return;
    snapshot = null;
    listener();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

function newId() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

export function cleanName(name: string) {
  return name.trim().replace(/\s+/g, " ").slice(0, MAX_PLAYLIST_NAME) || "Untitled Playlist";
}

function change(id: string, edit: (playlist: Playlist) => Playlist) {
  write(read().map((playlist) => (playlist.id === id ? { ...edit(playlist), updatedAt: Date.now() } : playlist)));
}

export const playlistStore = {
  create(name: string, paths: string[] = []): Playlist {
    const now = Date.now();
    const playlist: Playlist = { id: newId(), name: cleanName(name), paths: [...new Set(paths)], createdAt: now, updatedAt: now };
    write([...read(), playlist]);
    return playlist;
  },
  rename(id: string, name: string) {
    change(id, (playlist) => ({ ...playlist, name: cleanName(name) }));
  },
  remove(id: string) {
    write(read().filter((playlist) => playlist.id !== id));
  },
  /** Adds songs that are not already in the playlist; returns how many were added. */
  addSongs(id: string, paths: string[]) {
    const playlist = read().find((item) => item.id === id);
    if (!playlist) return 0;
    const fresh = [...new Set(paths)].filter((path) => !playlist.paths.includes(path));
    if (fresh.length) change(id, (item) => ({ ...item, paths: [...item.paths, ...fresh] }));
    return fresh.length;
  },
  removeSong(id: string, path: string) {
    change(id, (playlist) => ({ ...playlist, paths: playlist.paths.filter((item) => item !== path) }));
  },
  moveSong(id: string, from: number, to: number) {
    change(id, (playlist) => {
      const paths = [...playlist.paths];
      if (from < 0 || to < 0 || from >= paths.length || to >= paths.length) return playlist;
      const [moved] = paths.splice(from, 1);
      paths.splice(to, 0, moved);
      return { ...playlist, paths };
    });
  },
  /** Points saved songs at their new paths after files are renamed (no timestamp change). */
  remap(rename: (path: string) => string) {
    const current = read();
    let changed = false;
    const next = current.map((playlist) => {
      const paths = [...new Set(playlist.paths.map(rename))];
      if (paths.length === playlist.paths.length && paths.every((path, index) => path === playlist.paths[index])) return playlist;
      changed = true;
      return { ...playlist, paths };
    });
    if (changed) write(next);
  },
  /** Tests only. */
  reset() {
    snapshot = null;
  },
};

export function usePlaylists() {
  return useSyncExternalStore(subscribe, read, read);
}

/** Resolves a playlist's paths against the library, skipping songs that are gone. */
export function usePlaylistSongs<T extends { relativePath: string }>(playlist: Playlist | undefined, songs: T[]) {
  return useMemo(() => {
    if (!playlist) return [];
    const byPath = new Map(songs.map((song) => [song.relativePath, song]));
    return playlist.paths.flatMap((path) => byPath.get(path) ?? []);
  }, [playlist, songs]);
}
