import type { DesktopBridge, LibraryEntry, NativeAudio, SignalPath } from "./bridge";

/** What a backend reports back to the player. */
export type BackendListener = {
  time(seconds: number): void;
  duration(seconds: number): void;
  playing(playing: boolean): void;
  /** HTML backend: the song finished (the player picks what's next). */
  ended(): void;
  /** Native backend: the engine moved on to `path` by itself (gapless). */
  trackStarted(path: string, durationSeconds: number | null): void;
  /** Native backend: the queue ran out. */
  idle(): void;
  signal(signal: SignalPath | null): void;
  error(code: string): void;
};

export type AudioBackend = {
  readonly kind: "native" | "html";
  /** Starts `entry` from `startSeconds` and plays. */
  load(entry: LibraryEntry, startSeconds?: number): Promise<void>;
  play(): Promise<void>;
  pause(): void;
  seek(seconds: number): void;
  currentTime(): number;
  setVolume(volume: number): void;
  /** Native only: the song after the current one, so it joins gaplessly. */
  setNext(entry: LibraryEntry | null): void;
  /** Pause and free the output device (the video player opened). */
  release(): void;
  stop(): void;
  dispose(): void;
};

/** Today's webview `<audio>` playback through the `qtmedia://` scheme. */
export function createHtmlBackend(bridge: DesktopBridge, listener: BackendListener): AudioBackend | null {
  if (!bridge.mediaUrl) return null;
  const element = new Audio();
  element.preload = "metadata";
  const onTime = () => listener.time(element.currentTime);
  const onDuration = () => {
    if (Number.isFinite(element.duration) && element.duration > 0) listener.duration(element.duration);
  };
  const onEnded = () => listener.ended();
  const onError = () => listener.error("playback_failed");
  element.addEventListener("timeupdate", onTime);
  element.addEventListener("durationchange", onDuration);
  element.addEventListener("loadedmetadata", onDuration);
  element.addEventListener("ended", onEnded);
  element.addEventListener("error", onError);
  const start = () => Promise.resolve(element.play()).then(() => listener.playing(true), () => listener.playing(false));
  return {
    kind: "html",
    load: async (entry, startSeconds = 0) => {
      element.src = bridge.mediaUrl!(entry.relativePath);
      element.currentTime = startSeconds;
      listener.signal(null);
      await start();
    },
    play: start,
    pause: () => {
      element.pause();
      listener.playing(false);
    },
    seek: (seconds) => { element.currentTime = seconds; },
    currentTime: () => element.currentTime,
    setVolume: (volume) => { element.volume = volume; },
    setNext: () => undefined,
    release: () => {
      element.pause();
      listener.playing(false);
    },
    stop: () => {
      element.pause();
      element.removeAttribute("src");
    },
    dispose: () => {
      element.pause();
      element.removeEventListener("timeupdate", onTime);
      element.removeEventListener("durationchange", onDuration);
      element.removeEventListener("loadedmetadata", onDuration);
      element.removeEventListener("ended", onEnded);
      element.removeEventListener("error", onError);
    },
  };
}

/**
 * The native engine (WASAPI shared/exclusive, gapless). The engine owns
 * transitions: the player queues the next song with `setNext` and follows
 * `trackStarted`. Position comes from the frames the device actually played.
 */
export function createNativeBackend(audio: NativeAudio, listener: BackendListener): AudioBackend {
  let position = 0;
  let current: string | null = null;
  // After stop/idle/error the engine has no session; play() reloads.
  let active = false;
  let disposed = false;
  let unsubscribe: (() => void) | null = null;
  const fail = (error: unknown) => listener.error(typeof error === "string" ? error : "audio_unavailable");

  void audio.subscribe((event) => {
    if (disposed) return;
    switch (event.type) {
      case "position":
        position = event.seconds;
        listener.time(event.seconds);
        break;
      case "trackStarted":
        if (!event.path) break;
        position = 0;
        if (event.durationSeconds) listener.duration(event.durationSeconds);
        if (event.path !== current) {
          current = event.path;
          listener.trackStarted(event.path, event.durationSeconds);
        }
        break;
      case "state":
        if (event.state === "playing") {
          active = true;
          listener.playing(true);
        } else if (event.state === "paused") {
          listener.playing(false);
        } else if (event.state === "idle") {
          active = false;
          listener.playing(false);
          listener.idle();
        } else if (event.state === "stopped") {
          active = false;
          listener.playing(false);
        }
        break;
      case "signalPath": {
        const { type: _type, ...signal } = event;
        listener.signal(signal);
        break;
      }
      case "error":
        active = false;
        listener.error(event.code);
        break;
      default:
        break;
    }
  }).then((stop) => {
    if (disposed) stop();
    else unsubscribe = stop;
  }, () => undefined);

  const load = async (entry: LibraryEntry, startSeconds = 0) => {
    current = entry.relativePath;
    position = startSeconds;
    active = true;
    await audio.play(entry.relativePath, startSeconds).catch(fail);
  };

  return {
    kind: "native",
    load,
    play: async () => {
      if (!active) {
        if (current) await load({ relativePath: current } as LibraryEntry, position);
        return;
      }
      await audio.resume().catch(fail);
    },
    pause: () => void audio.pause().catch(fail),
    seek: (seconds) => {
      position = seconds;
      if (active) void audio.seek(seconds).catch(fail);
    },
    currentTime: () => position,
    setVolume: (volume) => void audio.setVolume(volume).catch(() => undefined),
    setNext: (entry) => void audio.setNext(entry?.relativePath ?? null).catch(() => undefined),
    release: () => void audio.release().catch(() => undefined),
    stop: () => {
      active = false;
      current = null;
      position = 0;
      void audio.stop().catch(() => undefined);
    },
    dispose: () => {
      disposed = true;
      unsubscribe?.();
      void audio.stop().catch(() => undefined);
    },
  };
}
