import type { LibraryEntry } from "./bridge";
import type { RepeatMode } from "./player";

/** What survives a restart: settings, the queue, and where it was. */
export const PLAYER_KEY = "qtmedia.player.v1";
const MAX_SAVED_QUEUE = 5000;

export type SavedPlayer = {
  volume: number;
  muted: boolean;
  shuffle: boolean;
  repeat: RepeatMode;
  queue: LibraryEntry[];
  ordered: LibraryEntry[];
  index: number;
  position: number;
};

function isEntry(value: unknown): value is LibraryEntry {
  const entry = value as LibraryEntry | null;
  return Boolean(entry) && typeof entry!.relativePath === "string" && entry!.relativePath.startsWith("audio/");
}

export function readSavedPlayer(): Partial<SavedPlayer> {
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(PLAYER_KEY) ?? "{}");
    if (!raw || typeof raw !== "object") return {};
    const saved = raw as Record<string, unknown>;
    const queue = Array.isArray(saved.queue) ? saved.queue.filter(isEntry) : [];
    const ordered = Array.isArray(saved.ordered) ? saved.ordered.filter(isEntry) : [];
    const index = typeof saved.index === "number" && saved.index >= 0 && saved.index < queue.length ? saved.index : -1;
    return {
      volume: typeof saved.volume === "number" && saved.volume >= 0 && saved.volume <= 1 ? saved.volume : undefined,
      muted: typeof saved.muted === "boolean" ? saved.muted : undefined,
      shuffle: typeof saved.shuffle === "boolean" ? saved.shuffle : undefined,
      repeat: saved.repeat === "all" || saved.repeat === "one" || saved.repeat === "off" ? saved.repeat : undefined,
      queue: index >= 0 ? queue : [],
      ordered: index >= 0 ? (ordered.length ? ordered : queue) : [],
      index,
      position: typeof saved.position === "number" && Number.isFinite(saved.position) && saved.position > 0 ? saved.position : 0,
    };
  } catch {
    return {};
  }
}

export function writeSavedPlayer(state: Omit<SavedPlayer, "position">, position: number) {
  try {
    const saved: SavedPlayer = {
      volume: state.volume, muted: state.muted, shuffle: state.shuffle, repeat: state.repeat,
      queue: state.queue.slice(0, MAX_SAVED_QUEUE), ordered: state.ordered.slice(0, MAX_SAVED_QUEUE),
      index: state.index < MAX_SAVED_QUEUE ? state.index : -1, position,
    };
    localStorage.setItem(PLAYER_KEY, JSON.stringify(saved));
  } catch {
    // Remembering the player is a convenience; full or blocked storage is fine.
  }
}
