/** Per-video playback positions, kept only in this webview's local storage.
 *
 * Keys are library-relative paths (never URLs or absolute paths). Positions
 * near the start or the end are not worth resuming and are dropped. */

export const RESUME_KEY = "qtmedia.resume.v1";
/** Fired on `window` after this app changes saved positions. */
export const RESUME_EVENT = "qtmedia-resume";
const DEFAULT_LIMIT = 200;
const MIN_POSITION_SECONDS = 10;
const END_MARGIN_SECONDS = 15;

type StorageLike = Pick<Storage, "getItem" | "setItem" | "removeItem">;
type Entry = { t: number; at: number };

export type SavedPosition = { relativePath: string; position: number; savedAt: number };

export type ResumeStore = {
  get(relativePath: string): number | null;
  /** Every saved position, most recently watched first. */
  list(): SavedPosition[];
  save(relativePath: string, position: number, duration: number): void;
  clear(relativePath: string): void;
};

function defaultStorage(): StorageLike | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export function createResumeStore(
  storage: StorageLike | null = defaultStorage(),
  { now = Date.now, limit = DEFAULT_LIMIT }: { now?: () => number; limit?: number } = {},
): ResumeStore {
  const read = (): Record<string, Entry> => {
    try {
      const parsed: unknown = JSON.parse(storage?.getItem(RESUME_KEY) ?? "{}");
      return parsed && typeof parsed === "object" ? (parsed as Record<string, Entry>) : {};
    } catch {
      return {};
    }
  };
  const write = (entries: Record<string, Entry>) => {
    try {
      storage?.setItem(RESUME_KEY, JSON.stringify(entries));
    } catch {
      // Resume is a convenience; a full or blocked store must not break playback.
    }
    try {
      window.dispatchEvent(new Event(RESUME_EVENT));
    } catch {
      // No window (tests with a bare store).
    }
  };

  const clear = (relativePath: string) => {
    const entries = read();
    if (relativePath in entries) {
      delete entries[relativePath];
      write(entries);
    }
  };

  return {
    get(relativePath) {
      const entry = read()[relativePath];
      return entry && Number.isFinite(entry.t) ? entry.t : null;
    },
    list() {
      return Object.entries(read())
        .filter(([, entry]) => entry && Number.isFinite(entry.t))
        .map(([relativePath, entry]) => ({ relativePath, position: entry.t, savedAt: Number.isFinite(entry.at) ? entry.at : 0 }))
        .sort((left, right) => right.savedAt - left.savedAt);
    },
    save(relativePath, position, duration) {
      const nearEnd = Number.isFinite(duration) && duration > 0 && position > duration - END_MARGIN_SECONDS;
      if (!Number.isFinite(position) || position < MIN_POSITION_SECONDS || nearEnd) {
        clear(relativePath);
        return;
      }
      const entries = read();
      entries[relativePath] = { t: Math.round(position * 10) / 10, at: now() };
      const kept = Object.entries(entries).sort(([, a], [, b]) => b.at - a.at).slice(0, limit);
      write(Object.fromEntries(kept));
    },
    clear,
  };
}

/** Moves saved positions to new paths after files are renamed; the newer one wins a clash. */
export function remapResumePositions(rename: (path: string) => string, storage: StorageLike | null = defaultStorage()) {
  try {
    const parsed: unknown = JSON.parse(storage?.getItem(RESUME_KEY) ?? "{}");
    if (!parsed || typeof parsed !== "object") return;
    const entries = parsed as Record<string, Entry>;
    const next: Record<string, Entry> = {};
    let changed = false;
    for (const [path, entry] of Object.entries(entries)) {
      const target = rename(path);
      if (target !== path) changed = true;
      const existing = next[target];
      if (!existing || (entry?.at ?? 0) > (existing.at ?? 0)) next[target] = entry;
    }
    if (changed) storage?.setItem(RESUME_KEY, JSON.stringify(next));
  } catch {
    // Resume is a convenience; a corrupt or blocked store is left alone.
  }
}
