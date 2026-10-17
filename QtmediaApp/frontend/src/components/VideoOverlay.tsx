import { Container } from "@videojs/react";
import { Video, VideoPlayer } from "@videojs/react/video";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { DesktopBridge, LibraryEntry } from "../lib/bridge";
import { formatDuration, mediaTitle } from "../lib/library";
import { useOptionalPlayer } from "../lib/player";
import { createResumeStore, type ResumeStore } from "../lib/resume";
import { useStableVolume } from "../lib/stableVolume";
import { usePlayableSource } from "../lib/playableSource";
import { languageTag, pickTrack, readSubtitleChoice, trackLabels, useSubtitles, writeSubtitleChoice } from "../lib/subtitles";
import { readAutoplay, readVideoVolume, writeAutoplay, writeVideoVolume } from "../lib/videoPrefs";
import { Icon } from "./Icon";
import { VideoControls } from "./VideoControls";

/** Save at most this often while playing; pause, close and end always save. */
const SAVE_INTERVAL_MS = 5000;
/** Seconds the "Up next" card counts down before the next video starts. */
export const AUTOPLAY_SECONDS = 5;
/** How long the "Resumed at" note stays before it fades away by itself. */
const RESUME_NOTE_MS = 6000;

/** The videos either side of the playing one, in the order the opening page showed. */
export type VideoNavigation = {
  previous: LibraryEntry | null;
  next: LibraryEntry | null;
  onPrevious(): void;
  onNext(): void;
};

/** Full-window Video.js player for library videos. Loaded lazily by App. The
 * player stays mounted when `entry` changes, so full screen survives Next. */
export default function VideoOverlay({ bridge, entry, onClose, resume, navigation }: {
  bridge: DesktopBridge;
  entry: LibraryEntry;
  onClose: () => void;
  resume?: ResumeStore;
  navigation?: VideoNavigation;
}) {
  const store = useMemo(() => resume ?? createResumeStore(), [resume]);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [videoElement, setVideoElement] = useState<HTMLVideoElement | null>(null);
  const stable = useStableVolume(videoElement);
  const closeRef = useRef<HTMLButtonElement>(null);
  const lastSaveRef = useRef(0);
  const [resumedAt, setResumedAt] = useState<number | null>(null);
  const [failed, setFailed] = useState(false);
  const [autoplay, setAutoplay] = useState(readAutoplay);
  // Seconds left before the next video starts, while the "Up next" card shows.
  const [upNext, setUpNext] = useState<number | null>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const windowFullscreenRef = useRef(false);
  const title = mediaTitle(entry);
  const source = usePlayableSource(bridge, entry.relativePath);
  const [subtitlesToken, setSubtitlesToken] = useState(0);
  const subtitles = useSubtitles(bridge, entry.relativePath, subtitlesToken);
  const [subtitleNote, setSubtitleNote] = useState<string | null>(null);
  const subtitleLabels = useMemo(() => trackLabels(subtitles.tracks), [subtitles.tracks]);
  const subtitleOptions = useMemo(() => subtitles.tracks.map((track, index) => ({ id: track.id, label: subtitleLabels[index] })), [subtitles.tracks, subtitleLabels]);
  const src = source.kind === "ready" ? source.src : undefined;
  // Whether the player was on screen last render (kept while switching videos).
  const playerShownRef = useRef(false);
  useEffect(() => {
    if (source.kind !== "checking") playerShownRef.current = source.kind === "ready" && !failed;
  });

  // True from a switch until the next video's metadata loads: the old video's
  // late pause/time events must not be saved under the new video's path.
  const switchingRef = useRef(false);
  const save = useCallback(() => {
    const element = videoRef.current;
    if (element && !switchingRef.current) store.save(entry.relativePath, element.currentTime, element.duration);
  }, [entry.relativePath, store]);

  // A new video starts with a clean slate (the old one's position is saved
  // before navigating). Removing `src` alone would leave the old one playing.
  const shownPathRef = useRef(entry.relativePath);
  useEffect(() => {
    if (shownPathRef.current === entry.relativePath) return;
    shownPathRef.current = entry.relativePath;
    setResumedAt(null);
    setFailed(false);
    setUpNext(null);
    lastSaveRef.current = 0;
    const element = videoRef.current;
    if (element?.hasAttribute("src")) {
      switchingRef.current = true;
      element.pause();
      element.removeAttribute("src");
      element.load();
    }
  }, [entry.relativePath]);

  const goPrevious = useMemo(() => (navigation?.previous ? () => { save(); navigation.onPrevious(); } : null), [navigation, save]);
  const goNext = useMemo(() => (navigation?.next ? () => { save(); navigation.onNext(); } : null), [navigation, save]);

  const toggleAutoplay = () => {
    setAutoplay((on) => {
      writeAutoplay(!on);
      return !on;
    });
    setUpNext(null);
  };

  // The "Up next" countdown; it starts when a video ends with autoplay on.
  useEffect(() => {
    if (upNext === null) return;
    if (upNext <= 0) {
      setUpNext(null);
      goNext?.();
      return;
    }
    const timer = window.setTimeout(() => setUpNext((left) => (left === null ? null : left - 1)), 1000);
    return () => window.clearTimeout(timer);
  }, [goNext, upNext]);

  const onEnded = () => {
    if (switchingRef.current) return;
    store.clear(entry.relativePath);
    if (autoplay && goNext) setUpNext(AUTOPLAY_SECONDS);
  };

  // Show the remembered subtitle choice on each video's tracks, and remember
  // what the viewer picks with the player's captions button, menu or C key.
  const applyingRef = useRef(false);
  useEffect(() => {
    const list = videoElement?.textTracks;
    if (!list || typeof list.addEventListener !== "function" || !subtitles.tracks.length) return;
    const chosen = pickTrack(subtitles.tracks, readSubtitleChoice());
    applyingRef.current = true;
    for (let index = 0; index < list.length; index += 1) {
      const track = list[index];
      if (track.kind !== "subtitles") continue;
      const mode = chosen && track.id === chosen.id ? "showing" : "disabled";
      if (track.mode !== mode) track.mode = mode;
    }
    applyingRef.current = false;
    let kept = chosen?.id ?? null;
    const record = () => {
      if (applyingRef.current) return;
      const tracks = Array.from(list).filter((track) => track.kind === "subtitles" && subtitles.tracks.some((item) => item.id === track.id));
      if (!tracks.length) return;
      const on = tracks.filter((track) => track.mode === "showing");
      if (on.length > 1) {
        // The player's menu always leaves one track on; two means the webview
        // switched one on by itself. Keep the track already chosen.
        const keep = on.find((track) => track.id === kept) ?? on[0];
        applyingRef.current = true;
        for (const track of on) if (track !== keep) track.mode = "disabled";
        applyingRef.current = false;
      }
      kept = tracks.find((track) => track.mode === "showing")?.id ?? null;
      const showing = subtitles.tracks.find((item) => item.id === kept);
      writeSubtitleChoice(showing ? { enabled: true, ...(showing.language ? { language: showing.language } : {}), ...(showing.label ? { label: showing.label } : {}) } : { enabled: false });
    };
    list.addEventListener("change", record);
    return () => list.removeEventListener("change", record);
  }, [videoElement, subtitles.tracks]);

  const addSubtitles = async () => {
    if (!bridge.addSubtitles) return;
    try {
      const added = await bridge.addSubtitles(entry.relativePath);
      if (!added) {
        if (added === 0) setSubtitleNote("Only .srt and .vtt files can be added.");
        return;
      }
      // Show the new subtitles straight away.
      writeSubtitleChoice({ enabled: true });
      setSubtitleNote(added === 1 ? "Subtitles added." : `${added} subtitle files added.`);
      setSubtitlesToken((token) => token + 1);
    } catch {
      setSubtitleNote("The subtitles could not be added.");
    }
  };

  useEffect(() => {
    if (!subtitleNote) return;
    const timer = window.setTimeout(() => setSubtitleNote(null), 3000);
    return () => window.clearTimeout(timer);
  }, [subtitleNote]);

  // The player keeps one volume across videos and sessions.
  useEffect(() => {
    if (!videoElement) return;
    const saved = readVideoVolume();
    if (saved) {
      videoElement.volume = saved.volume;
      videoElement.muted = saved.muted;
    }
    const remember = () => writeVideoVolume(videoElement.volume, videoElement.muted);
    videoElement.addEventListener("volumechange", remember);
    return () => videoElement.removeEventListener("volumechange", remember);
  }, [videoElement]);

  // Media keys and the system media overlay follow the video while it is open.
  const setVideoActive = useOptionalPlayer()?.setVideoActive;
  useEffect(() => {
    setVideoActive?.(true);
    return () => setVideoActive?.(false);
  }, [setVideoActive]);
  useEffect(() => {
    const session = typeof navigator !== "undefined" ? navigator.mediaSession : undefined;
    if (!session) return;
    const togglePlay = () => {
      const element = videoRef.current;
      if (!element) return;
      if (element.paused) void element.play().catch(() => undefined);
      else element.pause();
    };
    const handlers: Array<[MediaSessionAction, (() => void) | null]> = [
      ["play", togglePlay], ["pause", togglePlay], ["nexttrack", goNext], ["previoustrack", goPrevious],
    ];
    try {
      if (typeof MediaMetadata !== "undefined") session.metadata = new MediaMetadata({ title, artist: "Qtmedia" });
    } catch { /* metadata unsupported */ }
    for (const [action, handler] of handlers) {
      try { session.setActionHandler(action, handler); } catch { /* unsupported action */ }
    }
    return () => {
      for (const [action] of handlers) {
        try { session.setActionHandler(action, null); } catch { /* unsupported action */ }
      }
    };
  }, [goNext, goPrevious, title]);

  useEffect(() => {
    if (resumedAt === null) return;
    const timer = window.setTimeout(() => setResumedAt(null), RESUME_NOTE_MS);
    return () => window.clearTimeout(timer);
  }, [resumedAt]);

  // Subtitles chosen from the CC button or the settings menu; the change
  // listener above remembers the choice.
  const chooseSubtitle = (id: string | null) => {
    const list = videoElement?.textTracks;
    if (!list) return;
    for (let index = 0; index < list.length; index += 1) {
      const track = list[index];
      if (track.kind === "subtitles") track.mode = track.id === id ? "showing" : "disabled";
    }
  };
  const preferredSubtitle = () => pickTrack(subtitles.tracks, { ...readSubtitleChoice(), enabled: true })?.id ?? null;
  const playable = source.kind === "ready" && !failed;
  const close = useCallback(() => {
    save();
    if (document.fullscreenElement) void document.exitFullscreen().catch(() => undefined);
    onClose();
  }, [onClose, save]);

  // Video.js owns full screen (its button, F, double-click). HTML full screen
  // only fills the webview, so the app window follows it to cover the display.
  useEffect(() => {
    const setWindow = (on: boolean) => {
      if (!bridge.setFullscreen || windowFullscreenRef.current === on) return;
      windowFullscreenRef.current = on;
      void bridge.setFullscreen(on).catch(() => { windowFullscreenRef.current = false; });
    };
    const sync = () => {
      const element = document.fullscreenElement;
      setWindow(Boolean(element && overlayRef.current?.contains(element)));
    };
    document.addEventListener("fullscreenchange", sync);
    return () => {
      document.removeEventListener("fullscreenchange", sync);
      // Never leave the window full screen behind the player.
      setWindow(false);
    };
  }, [bridge]);

  // Focus the close control on open and give focus back to the opener on close.
  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeRef.current?.focus();
    return () => opener?.focus();
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      // In full screen the browser uses Esc to leave full screen first.
      if (event.key === "Escape" && upNext !== null) setUpNext(null);
      else if (event.key === "Escape" && !document.fullscreenElement) close();
      // YouTube's keys: Shift+N next video, Shift+P previous video.
      else if (event.shiftKey && !event.ctrlKey && !event.metaKey && !event.altKey) {
        const go = event.code === "KeyN" ? goNext : event.code === "KeyP" ? goPrevious : null;
        if (go) {
          event.preventDefault();
          go();
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [close, goNext, goPrevious, upNext]);

  const onLoadedMetadata = () => {
    switchingRef.current = false;
    const saved = store.get(entry.relativePath);
    const element = videoRef.current;
    if (saved === null || !element) return;
    element.currentTime = saved;
    setResumedAt(saved);
  };

  const onTimeUpdate = () => {
    const now = Date.now();
    if (now - lastSaveRef.current < SAVE_INTERVAL_MS) return;
    lastSaveRef.current = now;
    save();
  };

  const startOver = () => {
    if (videoRef.current) videoRef.current.currentTime = 0;
    store.clear(entry.relativePath);
    setResumedAt(null);
  };

  const openExternally = () => void bridge.openMedia(entry.relativePath);

  const note = subtitleNote ? <span role="status">{subtitleNote}</span>
    : resumedAt !== null ? (
      <span role="status">Resumed at {formatDuration(resumedAt)}<button type="button" onClick={startOver}>Start over</button></span>
    ) : null;

  return (
    <div ref={overlayRef} className="video-overlay" role="dialog" aria-modal="true" aria-label={`Playing ${title}`}>
      <header className="video-overlay__bar" data-tauri-drag-region>
        <button ref={closeRef} type="button" className="np-round video-overlay__close" aria-label="Close video" onClick={close}><Icon name="close" /></button>
        <h2 className="video-overlay__title" title={title}>{title}</h2>
      </header>
      <div className="video-overlay__stage">
        {source.kind === "checking" && !playerShownRef.current ? (
          <div className="video-overlay__fallback" role="status" aria-label="Checking video">
            <span className="spinner" aria-hidden="true" />
          </div>
        ) : source.kind === "preparing" ? (
          <div className="video-overlay__fallback video-overlay__prepare" role="status" aria-label="Preparing video">
            <p>{source.mode === "remux" ? "Preparing for playback…" : "Converting for playback…"}</p>
            <progress className="meter" max={100} value={source.percent ?? undefined} aria-label="Preparation progress" />
            <span className="video-overlay__prepare-note">
              {source.percent !== null ? `${Math.round(source.percent)}% · ` : ""}
              {source.mode === "remux" ? "Copying into a playable file, no quality change." : "This format needs converting once; the copy is kept for next time."}
            </span>
            <button type="button" className="btn btn-default" onClick={close}>Cancel</button>
          </div>
        ) : !failed && (source.kind === "ready" || (source.kind === "checking" && playerShownRef.current)) ? (
          // While the next video is checked the player stays (with no source),
          // so full screen and focus are kept.
          <VideoPlayer>
            <Container className="vplayer">
              <Video
                ref={(element: HTMLVideoElement | null) => {
                  videoRef.current = element;
                  setVideoElement(element);
                }}
                // Web Audio (stable volume) needs CORS-clean media; the
                // qtmedia:// scheme allows the app's own origin.
                crossOrigin="anonymous"
                src={src}
                autoPlay
                playsInline
                onLoadedMetadata={onLoadedMetadata}
                onTimeUpdate={onTimeUpdate}
                onPause={save}
                onEnded={onEnded}
                onError={() => setFailed(true)}
              >
                {bridge.mediaUrl ? subtitles.tracks.map((track, index) => (
                  <track key={`${entry.relativePath}|${track.id}|${track.url}`} id={track.id} kind="subtitles" src={bridge.mediaUrl!(track.url)} label={subtitleLabels[index]} srcLang={languageTag(track.language) || undefined} />
                )) : null}
              </Video>
              <VideoControls
                video={videoElement}
                navigation={navigation ? {
                  previous: navigation.previous && goPrevious ? { title: mediaTitle(navigation.previous), go: goPrevious } : null,
                  next: navigation.next && goNext ? { title: mediaTitle(navigation.next), go: goNext } : null,
                } : undefined}
                note={note}
                stable={playable ? { enabled: stable.enabled, toggle: stable.toggle } : null}
                autoplay={navigation ? { on: autoplay, toggle: toggleAutoplay } : null}
                subtitles={{
                  options: subtitleOptions,
                  choose: chooseSubtitle,
                  preferred: preferredSubtitle,
                  add: bridge.addSubtitles ? () => void addSubtitles() : undefined,
                  unsupported: !subtitles.loading && !subtitles.tracks.length ? subtitles.unsupported : 0,
                }}
              />
              {upNext !== null && navigation?.next ? (
                <div className="video-upnext" role="status" aria-label="Up next">
                  <p>Up next in {upNext}</p>
                  <strong title={mediaTitle(navigation.next)}>{mediaTitle(navigation.next)}</strong>
                  <div className="video-upnext__actions">
                    <button type="button" onClick={() => { setUpNext(null); goNext?.(); }}>Play now</button>
                    <button type="button" onClick={() => setUpNext(null)}>Cancel</button>
                  </div>
                </div>
              ) : null}
            </Container>
          </VideoPlayer>
        ) : (
          <div className="video-overlay__fallback">
            <p role={failed ? "alert" : undefined}>
              {failed || source.kind === "failed" ? "This video can't be played here." : "Built-in playback isn't available here."}
            </p>
            <button type="button" className="btn btn-default" onClick={openExternally}><Icon name="open" />Open in default player</button>
          </div>
        )}
      </div>
    </div>
  );
}
