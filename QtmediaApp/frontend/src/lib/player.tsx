import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";

import { createHtmlBackend, createNativeBackend, type AudioBackend, type BackendListener } from "./audioBackend";
import type { DesktopBridge, LibraryEntry, SignalPath } from "./bridge";
import { mediaTitle } from "./library";
import { renamer } from "./renames";

export type RepeatMode = "off" | "all" | "one";

type PlayerState = {
  queue: LibraryEntry[];
  /** Original order, restored when shuffle is turned off. */
  ordered: LibraryEntry[];
  index: number;
  playing: boolean;
  duration: number;
  volume: number;
  muted: boolean;
  shuffle: boolean;
  repeat: RepeatMode;
  failed: boolean;
  /** Stable code of the last playback error (e.g. `audio_device_lost`). */
  error: string | null;
  /** The native engine's path from file to device; null for webview playback. */
  signal: SignalPath | null;
  nowPlayingOpen: boolean;
};

export type PlayerValue = PlayerState & {
  available: boolean;
  /** "native" once the desktop engine plays; "html" in the browser or as a fallback. */
  backend: "native" | "html" | null;
  current: LibraryEntry | null;
  playQueue(entries: LibraryEntry[], startIndex: number): void;
  playAt(index: number): void;
  /** Puts songs right after the current one (moving them if already queued). */
  playNext(entries: LibraryEntry[]): void;
  /** Puts songs at the end of the queue (moving them if already queued). */
  addToQueue(entries: LibraryEntry[]): void;
  /** Moves a queue item; the playing song keeps playing wherever it lands. */
  moveInQueue(from: number, to: number): void;
  toggle(): void;
  next(): void;
  prev(): void;
  seek(seconds: number): void;
  setVolume(volume: number): void;
  toggleMute(): void;
  toggleShuffle(): void;
  cycleRepeat(): void;
  stop(): void;
  /** Pause and free the audio device (the video player opened). */
  releaseDevice(): void;
  /** While a video is open it owns the media keys; music takes them back after. */
  setVideoActive(active: boolean): void;
  openNowPlaying(): void;
  closeNowPlaying(): void;
};

const initial: PlayerState = {
  queue: [], ordered: [], index: -1, playing: false, duration: 0,
  volume: 0.8, muted: false, shuffle: false, repeat: "off", failed: false, error: null, signal: null, nowPlayingOpen: false,
};

const PlayerContext = createContext<PlayerValue | null>(null);

/**
 * The playback position changes four times a second. It lives in its own
 * store so only the components that show it re-render, not every player
 * consumer (the song list, Up Next, the whole bar).
 */
type PositionStore = { get(): number; set(seconds: number): void; subscribe(listener: () => void): () => void };

function createPositionStore(initialSeconds = 0): PositionStore {
  let seconds = initialSeconds;
  const listeners = new Set<() => void>();
  return {
    get: () => seconds,
    set(next) {
      if (next === seconds) return;
      seconds = next;
      for (const listener of listeners) listener();
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

const PositionContext = createContext<PositionStore | null>(null);
const noPosition = () => 0;
const noSubscribe = () => () => undefined;

/** The current playback position in seconds; re-renders only its caller. */
export function usePlayerPosition() {
  const store = useContext(PositionContext);
  return useSyncExternalStore(store?.subscribe ?? noSubscribe, store?.get ?? noPosition, store?.get ?? noPosition);
}

/** Slider position → output gain. Loudness is heard on a log scale; a cubic
 * curve (as PulseAudio uses) makes each part of the slider sound even. */
export function volumeGain(volume: number) {
  const clamped = Math.max(0, Math.min(1, volume));
  return clamped ** 3;
}

/** What survives a restart: settings, the queue, and where it was. */
export const PLAYER_KEY = "qtmedia.player.v1";
const MAX_SAVED_QUEUE = 5000;
const SAVE_POSITION_MS = 5000;

type SavedPlayer = {
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

function readSavedPlayer(): Partial<SavedPlayer> {
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

function writeSavedPlayer(state: PlayerState, position: number) {
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

/** Restart the current track instead of going back when past this point. */
const RESTART_THRESHOLD = 3;

function shuffled<T>(items: T[]) {
  const copy = [...items];
  for (let index = copy.length - 1; index > 0; index -= 1) {
    const swap = Math.floor(Math.random() * (index + 1));
    [copy[index], copy[swap]] = [copy[swap], copy[index]];
  }
  return copy;
}

/** The song that plays after `index`, given the repeat mode. */
export function followingIndex(length: number, index: number, repeat: RepeatMode) {
  if (index < 0 || index >= length) return -1;
  if (repeat === "one") return index;
  if (index + 1 < length) return index + 1;
  return repeat === "all" ? 0 : -1;
}

export function PlayerProvider({ bridge, children }: { bridge: DesktopBridge; children: React.ReactNode }) {
  // The last session comes back paused, at the song and position it left off.
  const [saved] = useState(readSavedPlayer);
  const [state, setState] = useState<PlayerState>(() => {
    const { position: _position, ...rest } = saved;
    return { ...initial, ...Object.fromEntries(Object.entries(rest).filter(([, value]) => value !== undefined)) } as PlayerState;
  });
  const [positionStore] = useState(() => createPositionStore(saved.index !== undefined && saved.index >= 0 ? saved.position ?? 0 : 0));
  const [backendKind, setBackendKind] = useState<"native" | "html" | null>(null);
  const stateRef = useRef(state);
  stateRef.current = state;
  // The song the backend holds; a restored song is only cued until Play.
  const loadedPathRef = useRef<string | null>(null);
  const backendRef = useRef<AudioBackend | null>(null);
  // Set when the native engine reports it cannot run; the webview takes over.
  const nativeFailedRef = useRef(false);
  const events = useRef<BackendListener | null>(null);
  const available = Boolean(bridge.audio) || typeof bridge.mediaUrl === "function";

  const update = useCallback((patch: Partial<PlayerState>) => {
    stateRef.current = { ...stateRef.current, ...patch };
    setState(stateRef.current);
  }, []);

  // A stable listener that forwards to the latest handlers below.
  const listener = useMemo<BackendListener>(() => ({
    time: (seconds) => events.current?.time(seconds),
    duration: (seconds) => events.current?.duration(seconds),
    playing: (playing) => events.current?.playing(playing),
    ended: () => events.current?.ended(),
    trackStarted: (path, duration) => events.current?.trackStarted(path, duration),
    idle: () => events.current?.idle(),
    signal: (signal) => events.current?.signal(signal),
    error: (code) => events.current?.error(code),
  }), []);

  const backend = useCallback((): AudioBackend | null => {
    if (!backendRef.current) {
      backendRef.current = bridge.audio && !nativeFailedRef.current
        ? createNativeBackend(bridge.audio, listener)
        : createHtmlBackend(bridge, listener);
      const { volume, muted } = stateRef.current;
      backendRef.current?.setVolume(muted ? 0 : volumeGain(volume));
      setBackendKind(backendRef.current?.kind ?? null);
    }
    return backendRef.current;
  }, [bridge, listener]);

  const load = useCallback((queue: LibraryEntry[], index: number, extra: Partial<PlayerState> = {}, startSeconds = 0) => {
    const entry = queue[index];
    const player = backend();
    if (!entry || !player) return;
    positionStore.set(startSeconds);
    loadedPathRef.current = entry.relativePath;
    update({ ...extra, queue, index, duration: entry.durationSeconds ?? 0, failed: false, error: null, playing: true });
    void player.load(entry, startSeconds);
  }, [backend, positionStore, update]);

  const playQueue = useCallback((entries: LibraryEntry[], startIndex: number) => {
    if (!entries[startIndex]) return;
    const { shuffle } = stateRef.current;
    if (shuffle) {
      const first = entries[startIndex];
      const rest = shuffled(entries.filter((_, index) => index !== startIndex));
      load([first, ...rest], 0, { ordered: entries });
    } else {
      load(entries, startIndex, { ordered: entries });
    }
  }, [load]);

  const playAt = useCallback((index: number) => load(stateRef.current.queue, index), [load]);

  const insert = useCallback((entries: LibraryEntry[], where: "next" | "end") => {
    const { queue, ordered, index, shuffle } = stateRef.current;
    const current = queue[index];
    if (!current) {
      // Nothing playing: the songs become the queue.
      playQueue(entries, 0);
      return;
    }
    const seen = new Set<string>([current.relativePath]);
    const added = entries.filter((entry) => !seen.has(entry.relativePath) && seen.add(entry.relativePath));
    if (!added.length) return;
    const moving = new Set(added.map((entry) => entry.relativePath));
    const rest = queue.filter((entry) => !moving.has(entry.relativePath));
    const at = where === "next" ? rest.indexOf(current) + 1 : rest.length;
    const nextQueue = [...rest.slice(0, at), ...added, ...rest.slice(at)];
    const nextOrdered = shuffle ? [...ordered.filter((entry) => !moving.has(entry.relativePath)), ...added] : nextQueue;
    update({ queue: nextQueue, ordered: nextOrdered, index: nextQueue.indexOf(current) });
  }, [playQueue, update]);
  const playNext = useCallback((entries: LibraryEntry[]) => insert(entries, "next"), [insert]);
  const addToQueue = useCallback((entries: LibraryEntry[]) => insert(entries, "end"), [insert]);

  const moveInQueue = useCallback((from: number, to: number) => {
    const { queue, index, shuffle } = stateRef.current;
    if (from === to || from < 0 || to < 0 || from >= queue.length || to >= queue.length) return;
    const reordered = [...queue];
    const [moved] = reordered.splice(from, 1);
    reordered.splice(to, 0, moved);
    let playing = index;
    if (from === index) playing = to;
    else if (from < index && to >= index) playing -= 1;
    else if (from > index && to <= index) playing += 1;
    // Unshuffled, the new order is the order; shuffled, turning shuffle off restores the original.
    update({ queue: reordered, index: playing, ...(shuffle ? {} : { ordered: reordered }) });
  }, [update]);

  const next = useCallback(() => {
    const { queue, index, repeat } = stateRef.current;
    if (!queue.length) return;
    if (index + 1 < queue.length) load(queue, index + 1);
    else if (repeat === "all") load(queue, 0);
    else {
      backend()?.pause();
      update({ playing: false });
    }
  }, [backend, load, update]);

  const prev = useCallback(() => {
    const { queue, index } = stateRef.current;
    const player = backend();
    if (!queue.length || !player) return;
    const cued = loadedPathRef.current !== queue[index]?.relativePath;
    const at = cued ? positionStore.get() : player.currentTime();
    if (at > RESTART_THRESHOLD || index === 0) {
      if (!cued) player.seek(0);
      positionStore.set(0);
      return;
    }
    load(queue, index - 1);
  }, [backend, load, update]);

  const toggle = useCallback(() => {
    const { queue, index, playing } = stateRef.current;
    const player = backend();
    if (index < 0 || !player) return;
    if (!playing && loadedPathRef.current !== queue[index]?.relativePath) {
      // A restored song: start it where the last session left off.
      load(queue, index, {}, positionStore.get());
      return;
    }
    if (playing) {
      player.pause();
      update({ playing: false });
    } else {
      update({ playing: true, failed: false, error: null });
      void player.play();
    }
  }, [backend, load, positionStore, update]);

  const seek = useCallback((seconds: number) => {
    const { queue, index, duration } = stateRef.current;
    const clamped = Math.max(0, Math.min(seconds, duration || seconds));
    // A cued song only remembers where to start.
    if (loadedPathRef.current === queue[index]?.relativePath) backend()?.seek(clamped);
    positionStore.set(clamped);
  }, [backend, positionStore]);

  const setVolume = useCallback((volume: number) => {
    const clamped = Math.max(0, Math.min(1, volume));
    backendRef.current?.setVolume(volumeGain(clamped));
    update({ volume: clamped, muted: false });
  }, [update]);

  const toggleMute = useCallback(() => {
    const muted = !stateRef.current.muted;
    backendRef.current?.setVolume(muted ? 0 : volumeGain(stateRef.current.volume));
    update({ muted });
  }, [update]);

  const toggleShuffle = useCallback(() => {
    const { shuffle, queue, ordered, index } = stateRef.current;
    const current = queue[index];
    if (!current) {
      update({ shuffle: !shuffle });
      return;
    }
    if (shuffle) {
      update({ shuffle: false, queue: ordered, index: Math.max(0, ordered.indexOf(current)) });
    } else {
      const rest = shuffled(queue.filter((_, position) => position !== index));
      update({ shuffle: true, queue: [current, ...rest], index: 0 });
    }
  }, [update]);

  const cycleRepeat = useCallback(() => {
    const order: RepeatMode[] = ["off", "all", "one"];
    update({ repeat: order[(order.indexOf(stateRef.current.repeat) + 1) % order.length] });
  }, [update]);

  const stop = useCallback(() => {
    backendRef.current?.stop();
    loadedPathRef.current = null;
    positionStore.set(0);
    const { volume, muted, shuffle, repeat } = stateRef.current;
    update({ ...initial, volume, muted, shuffle, repeat });
  }, [positionStore, update]);

  const releaseDevice = useCallback(() => {
    if (stateRef.current.index < 0) return;
    backendRef.current?.release();
    update({ playing: false });
  }, [update]);

  const openNowPlaying = useCallback(() => {
    if (stateRef.current.index >= 0) update({ nowPlayingOpen: true });
  }, [update]);
  const closeNowPlaying = useCallback(() => update({ nowPlayingOpen: false }), [update]);

  // Backend reports. The native engine moves between songs itself; the
  // webview backend asks the player for the next one.
  events.current = {
    time: (position) => positionStore.set(position),
    duration: (duration) => update({ duration }),
    playing: (playing) => update({ playing }),
    ended: () => {
      if (stateRef.current.repeat === "one") {
        const player = backendRef.current;
        player?.seek(0);
        void player?.play();
      } else {
        next();
      }
    },
    trackStarted: (path, duration) => {
      const { queue, index, repeat } = stateRef.current;
      const following = followingIndex(queue.length, index, repeat);
      const target = following >= 0 && queue[following]?.relativePath === path
        ? following
        : queue.findIndex((entry) => entry.relativePath === path);
      if (target < 0) return;
      positionStore.set(0);
      loadedPathRef.current = queue[target].relativePath;
      update({ index: target, duration: duration ?? queue[target].durationSeconds ?? 0, failed: false, error: null });
    },
    idle: () => update({ playing: false }),
    signal: (signal) => update({ signal }),
    error: (code) => {
      const player = backendRef.current;
      if (code === "audio_unavailable" && player?.kind === "native" && bridge.mediaUrl) {
        // The engine cannot run here: continue in the webview.
        nativeFailedRef.current = true;
        player.dispose();
        backendRef.current = null;
        const { queue, index } = stateRef.current;
        const entry = queue[index];
        if (entry) void backend()?.load(entry, positionStore.get());
        return;
      }
      update({ playing: false, failed: true, error: code });
    },
  };

  // Native gapless: keep the engine's "next" in step with the queue, repeat
  // mode and reordering.
  const following = followingIndex(state.queue.length, state.index, state.repeat);
  const nextPath = following >= 0 ? state.queue[following].relativePath : null;
  useEffect(() => {
    const player = backendRef.current;
    if (player?.kind !== "native" || state.index < 0) return;
    player.setNext(nextPath ? stateRef.current.queue.find((entry) => entry.relativePath === nextPath) ?? null : null);
  }, [nextPath, state.index, state.queue]);

  useEffect(() => () => backendRef.current?.dispose(), []);

  // Remember settings and the queue as they change, and the position every
  // few seconds, on pause and when the window goes away.
  useEffect(() => {
    writeSavedPlayer(state, positionStore.get());
  }, [state.volume, state.muted, state.shuffle, state.repeat, state.queue, state.ordered, state.index, state.playing]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    let last = 0;
    const unsubscribe = positionStore.subscribe(() => {
      const now = Date.now();
      if (now - last < SAVE_POSITION_MS) return;
      last = now;
      writeSavedPlayer(stateRef.current, positionStore.get());
    });
    const flush = () => writeSavedPlayer(stateRef.current, positionStore.get());
    window.addEventListener("pagehide", flush);
    return () => {
      unsubscribe();
      window.removeEventListener("pagehide", flush);
    };
  }, [positionStore]);

  // A restored queue may name songs that were renamed or deleted since.
  useEffect(() => {
    if (!saved.queue?.length) return;
    let active = true;
    void (async () => {
      try {
        const renames = (await bridge.libraryRenames?.().catch(() => [])) ?? [];
        const rename = renamer(renames);
        const library = new Map((await bridge.listLibrary()).map((entry) => [entry.relativePath, entry]));
        if (!active || loadedPathRef.current) return;
        const fresh = (entries: LibraryEntry[]) => entries.flatMap((entry) => library.get(rename(entry.relativePath)) ?? []);
        const { queue, index } = stateRef.current;
        const current = queue[index] ? library.get(rename(queue[index].relativePath)) : undefined;
        const nextQueue = fresh(queue);
        if (!current) {
          positionStore.set(0);
          update({ queue: [], ordered: [], index: -1, duration: 0 });
          return;
        }
        update({ queue: nextQueue, ordered: fresh(stateRef.current.ordered), index: nextQueue.indexOf(current), duration: current.durationSeconds ?? stateRef.current.duration });
      } catch {
        // Unreadable library: keep the restored queue; playing reports errors.
      }
    })();
    return () => { active = false; };
  }, [bridge, saved, positionStore, update]);

  // Windows/macOS media keys and the system media overlay.
  const current = state.index >= 0 ? state.queue[state.index] ?? null : null;
  const [videoActive, setVideoActive] = useState(false);
  useEffect(() => {
    const session = typeof navigator !== "undefined" ? navigator.mediaSession : undefined;
    if (!session || typeof MediaMetadata === "undefined" || videoActive) return;
    session.metadata = current ? new MediaMetadata({ title: mediaTitle(current), artist: "Qtmedia" }) : null;
    const handlers: Array<[MediaSessionAction, (() => void) | null]> = [
      ["play", current ? toggle : null], ["pause", current ? toggle : null],
      ["nexttrack", current ? next : null], ["previoustrack", current ? prev : null],
    ];
    for (const [action, handler] of handlers) {
      try { session.setActionHandler(action, handler); } catch { /* unsupported action */ }
    }
  }, [current, next, prev, toggle, videoActive]);

  const value = useMemo<PlayerValue>(() => ({
    ...state, available, backend: backendKind, current,
    playQueue, playAt, playNext, addToQueue, moveInQueue, toggle, next, prev, seek, setVolume, toggleMute, toggleShuffle, cycleRepeat, stop, releaseDevice, setVideoActive, openNowPlaying, closeNowPlaying,
  }), [state, available, backendKind, current, playQueue, playAt, playNext, addToQueue, moveInQueue, toggle, next, prev, seek, setVolume, toggleMute, toggleShuffle, cycleRepeat, stop, releaseDevice, openNowPlaying, closeNowPlaying]);

  return (
    <PositionContext.Provider value={positionStore}>
      <PlayerContext.Provider value={value}>{children}</PlayerContext.Provider>
    </PositionContext.Provider>
  );
}

/** Whether a key event is aimed at something that takes typing or its own keys. */
function isTypingTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  if (tag === "TEXTAREA" || tag === "SELECT") return true;
  if (tag === "INPUT") return (target as HTMLInputElement).type !== "range";
  return false;
}

/** Music keys anywhere in the app: Space play/pause, Ctrl+←/→ previous/next,
 * Ctrl+↑/↓ volume. Off while `enabled` is false (the video player has its own). */
export function usePlayerShortcuts(player: PlayerValue | null, enabled: boolean) {
  const ref = useRef(player);
  ref.current = player;
  useEffect(() => {
    if (!enabled) return;
    const onKey = (event: KeyboardEvent) => {
      const current = ref.current;
      if (!current?.current || event.defaultPrevented || event.altKey || event.metaKey || isTypingTarget(event.target)) return;
      const ctrl = event.ctrlKey;
      if (event.key === " " && !ctrl && !event.shiftKey) {
        // Space on a focused button or slider keeps its own meaning.
        if (event.target instanceof HTMLButtonElement || (event.target instanceof HTMLInputElement)) return;
        event.preventDefault();
        current.toggle();
      } else if (ctrl && event.key === "ArrowRight") {
        event.preventDefault();
        current.next();
      } else if (ctrl && event.key === "ArrowLeft") {
        event.preventDefault();
        current.prev();
      } else if (ctrl && (event.key === "ArrowUp" || event.key === "ArrowDown")) {
        event.preventDefault();
        current.setVolume(current.volume + (event.key === "ArrowUp" ? 0.05 : -0.05));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [enabled]);
}

export function usePlayer() {
  const value = useContext(PlayerContext);
  if (!value) throw new Error("PlayerProvider is required");
  return value;
}

/** For components that may render outside the player (e.g. isolated tests). */
export function useOptionalPlayer() {
  return useContext(PlayerContext);
}
