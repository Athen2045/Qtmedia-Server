import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

import { createHtmlBackend, createNativeBackend, type AudioBackend, type BackendListener } from "./audioBackend";
import type { DesktopBridge, LibraryEntry, SignalPath } from "./bridge";
import { mediaTitle } from "./library";

export type RepeatMode = "off" | "all" | "one";

type PlayerState = {
  queue: LibraryEntry[];
  /** Original order, restored when shuffle is turned off. */
  ordered: LibraryEntry[];
  index: number;
  playing: boolean;
  position: number;
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
  openNowPlaying(): void;
  closeNowPlaying(): void;
};

const initial: PlayerState = {
  queue: [], ordered: [], index: -1, playing: false, position: 0, duration: 0,
  volume: 0.8, muted: false, shuffle: false, repeat: "off", failed: false, error: null, signal: null, nowPlayingOpen: false,
};

const PlayerContext = createContext<PlayerValue | null>(null);

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
  const [state, setState] = useState<PlayerState>(initial);
  const [backendKind, setBackendKind] = useState<"native" | "html" | null>(null);
  const stateRef = useRef(state);
  stateRef.current = state;
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
      backendRef.current?.setVolume(muted ? 0 : volume);
      setBackendKind(backendRef.current?.kind ?? null);
    }
    return backendRef.current;
  }, [bridge, listener]);

  const load = useCallback((queue: LibraryEntry[], index: number, extra: Partial<PlayerState> = {}) => {
    const entry = queue[index];
    const player = backend();
    if (!entry || !player) return;
    update({ ...extra, queue, index, position: 0, duration: entry.durationSeconds ?? 0, failed: false, error: null, playing: true });
    void player.load(entry);
  }, [backend, update]);

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
    if (player.currentTime() > RESTART_THRESHOLD || index === 0) {
      player.seek(0);
      update({ position: 0 });
      return;
    }
    load(queue, index - 1);
  }, [backend, load, update]);

  const toggle = useCallback(() => {
    const { index, playing } = stateRef.current;
    const player = backend();
    if (index < 0 || !player) return;
    if (playing) {
      player.pause();
      update({ playing: false });
    } else {
      update({ playing: true, failed: false, error: null });
      void player.play();
    }
  }, [backend, update]);

  const seek = useCallback((seconds: number) => {
    const clamped = Math.max(0, Math.min(seconds, stateRef.current.duration || seconds));
    backend()?.seek(clamped);
    update({ position: clamped });
  }, [backend, update]);

  const setVolume = useCallback((volume: number) => {
    const clamped = Math.max(0, Math.min(1, volume));
    backendRef.current?.setVolume(clamped);
    update({ volume: clamped, muted: false });
  }, [update]);

  const toggleMute = useCallback(() => {
    const muted = !stateRef.current.muted;
    backendRef.current?.setVolume(muted ? 0 : stateRef.current.volume);
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
    const { volume, muted, shuffle, repeat } = stateRef.current;
    update({ ...initial, volume, muted, shuffle, repeat });
  }, [update]);

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
    time: (position) => update({ position }),
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
      update({ index: target, position: 0, duration: duration ?? queue[target].durationSeconds ?? 0, failed: false, error: null });
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
        const { queue, index, position } = stateRef.current;
        const entry = queue[index];
        if (entry) void backend()?.load(entry, position);
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

  // Windows/macOS media keys and the system media overlay.
  const current = state.index >= 0 ? state.queue[state.index] ?? null : null;
  useEffect(() => {
    const session = typeof navigator !== "undefined" ? navigator.mediaSession : undefined;
    if (!session || typeof MediaMetadata === "undefined") return;
    session.metadata = current ? new MediaMetadata({ title: mediaTitle(current), artist: "Qtmedia" }) : null;
    const handlers: Array<[MediaSessionAction, (() => void) | null]> = [
      ["play", current ? toggle : null], ["pause", current ? toggle : null],
      ["nexttrack", current ? next : null], ["previoustrack", current ? prev : null],
    ];
    for (const [action, handler] of handlers) {
      try { session.setActionHandler(action, handler); } catch { /* unsupported action */ }
    }
  }, [current, next, prev, toggle]);

  const value = useMemo<PlayerValue>(() => ({
    ...state, available, backend: backendKind, current,
    playQueue, playAt, moveInQueue, toggle, next, prev, seek, setVolume, toggleMute, toggleShuffle, cycleRepeat, stop, releaseDevice, openNowPlaying, closeNowPlaying,
  }), [state, available, backendKind, current, playQueue, playAt, moveInQueue, toggle, next, prev, seek, setVolume, toggleMute, toggleShuffle, cycleRepeat, stop, releaseDevice, openNowPlaying, closeNowPlaying]);

  return <PlayerContext.Provider value={value}>{children}</PlayerContext.Provider>;
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
