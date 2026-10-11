import "@videojs/react/video/skin.css";

import { SeekButton } from "@videojs/react";
import { Video, VideoPlayer, VideoSkin } from "@videojs/react/video";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { DesktopBridge, LibraryEntry } from "../lib/bridge";
import { formatDuration, mediaTitle } from "../lib/library";
import { createResumeStore, type ResumeStore } from "../lib/resume";
import { useStableVolume } from "../lib/stableVolume";
import { Icon } from "./Icon";

/** Save at most this often while playing; pause, close and end always save. */
const SAVE_INTERVAL_MS = 5000;
/** Matches the skin's ←/→ and J/L hotkeys (Video.js DEFAULT_SEEK_STEP). */
const SKIP_SECONDS = 10;

function SkipIcon({ forward }: { forward?: boolean }) {
  return (
    <svg viewBox="0 0 24 24" width="36" height="36" aria-hidden="true" style={forward ? { transform: "scaleX(-1)" } : undefined}>
      <path d="M12 5V2L7 6l5 4V7a6 6 0 1 1-6 6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      <text x="12.4" y="16.6" textAnchor="middle" fontSize="7" fontWeight="700" fill="currentColor" style={forward ? { transform: "scaleX(-1)", transformOrigin: "12.4px 0" } : undefined}>{SKIP_SECONDS}</text>
    </svg>
  );
}

/** Full-window Video.js player for one library video. Loaded lazily by App. */
export default function VideoOverlay({ bridge, entry, onClose, resume }: {
  bridge: DesktopBridge;
  entry: LibraryEntry;
  onClose: () => void;
  resume?: ResumeStore;
}) {
  const store = useMemo(() => resume ?? createResumeStore(), [resume]);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [videoElement, setVideoElement] = useState<HTMLVideoElement | null>(null);
  const stable = useStableVolume(videoElement);
  const closeRef = useRef<HTMLButtonElement>(null);
  const lastSaveRef = useRef(0);
  const [resumedAt, setResumedAt] = useState<number | null>(null);
  const [failed, setFailed] = useState(false);
  const overlayRef = useRef<HTMLDivElement>(null);
  const windowFullscreenRef = useRef(false);
  const title = mediaTitle(entry);
  const source = usePlayableSource(bridge, entry.relativePath);
  const src = source.kind === "ready" ? source.src : undefined;

  const save = useCallback(() => {
    const element = videoRef.current;
    if (element) store.save(entry.relativePath, element.currentTime, element.duration);
  }, [entry.relativePath, store]);

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
      if (event.key === "Escape" && !document.fullscreenElement) close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [close]);

  const onLoadedMetadata = () => {
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

  return (
    <div ref={overlayRef} className="video-overlay" role="dialog" aria-modal="true" aria-label={`Playing ${title}`}>
      <header className="video-overlay__bar" data-tauri-drag-region>
        <button ref={closeRef} type="button" className="np-round video-overlay__close" aria-label="Close video" onClick={close}><Icon name="close" /></button>
        <h2 className="video-overlay__title" title={title}>{title}</h2>
        {resumedAt !== null ? (
          <span className="video-overlay__resume" role="status">
            Resumed at {formatDuration(resumedAt)}
            <button type="button" onClick={startOver}>Start over</button>
          </span>
        ) : null}
        {source.kind === "ready" && !failed ? (
          <button
            type="button"
            className={`video-overlay__stable ${stable.enabled ? "is-on" : ""}`}
            aria-pressed={stable.enabled}
            title="Stable volume lifts quiet passages and holds peaks, like YouTube. Off plays the original mix."
            onClick={stable.toggle}
          >
            <Icon name="volume" />Stable volume
          </button>
        ) : null}
      </header>
      <div className="video-overlay__stage">
        {source.kind === "checking" ? (
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
        ) : src && !failed && source.kind === "ready" ? (
          <VideoPlayer>
            <VideoSkin className="video-overlay__skin">
              <div className="video-skip">
                <SeekButton seconds={-SKIP_SECONDS} className="video-skip__button" aria-label={`Back ${SKIP_SECONDS} seconds`} title={`Back ${SKIP_SECONDS} seconds (←)`}><SkipIcon /></SeekButton>
                <SeekButton seconds={SKIP_SECONDS} className="video-skip__button" aria-label={`Forward ${SKIP_SECONDS} seconds`} title={`Forward ${SKIP_SECONDS} seconds (→)`}><SkipIcon forward /></SeekButton>
              </div>
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
                onEnded={() => store.clear(entry.relativePath)}
                onError={() => setFailed(true)}
              />
            </VideoSkin>
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

/** Whether this webview decodes Dolby Digital (Plus); Windows editions without
 * the Dolby decoder get AC-3/E-AC-3 converted instead. */
function decodesDolby() {
  try {
    const probe = document.createElement("video");
    return Boolean(probe.canPlayType('audio/mp4; codecs="ec-3"')) && Boolean(probe.canPlayType('audio/mp4; codecs="ac-3"'));
  } catch {
    return false;
  }
}

type PlayableSource =
  | { kind: "checking" }
  | { kind: "ready"; src: string }
  | { kind: "preparing"; id: string; mode: "remux" | "transcode" | "preparing"; percent: number | null }
  | { kind: "failed" }
  | { kind: "unavailable" };

/**
 * The URL the player can play for a library video: the file itself, or a
 * prepared copy for formats the webview can't play as they are (MKV, MOV,
 * AVI, AC-3 audio …). Closing the player stops an unfinished preparation.
 */
function usePlayableSource(bridge: DesktopBridge, relativePath: string): PlayableSource {
  const [source, setSource] = useState<PlayableSource>(() => (
    !bridge.mediaUrl ? { kind: "unavailable" }
      : bridge.preparePlayback ? { kind: "checking" }
        : { kind: "ready", src: bridge.mediaUrl(relativePath) }
  ));

  useEffect(() => {
    const mediaUrl = bridge.mediaUrl;
    if (!mediaUrl || !bridge.preparePlayback) return;
    let active = true;
    let jobId: string | null = null;
    let finished = false;
    let unlisten: (() => void) | null = null;
    const ready = (url: string) => {
      finished = true;
      if (active) setSource({ kind: "ready", src: mediaUrl(url) });
    };
    void (async () => {
      // Listen first so a quick "ready" is never missed.
      unlisten = (await bridge.subscribePlayback?.((event) => {
        if (!active || event.id !== jobId) return;
        if (event.type === "progress") setSource((current) => (current.kind === "preparing" ? { ...current, percent: event.percent } : current));
        else if (event.type === "ready") ready(event.url);
        else {
          finished = true;
          setSource({ kind: "failed" });
        }
      }).catch(() => null)) ?? null;
      if (!active) {
        unlisten?.();
        return;
      }
      try {
        const plan = await bridge.preparePlayback!(relativePath, { dolby: decodesDolby() });
        if (!active) return;
        if (plan.kind === "direct") ready(relativePath);
        else if (plan.kind === "ready") ready(plan.url);
        else {
          jobId = plan.id;
          setSource({ kind: "preparing", id: plan.id, mode: plan.mode, percent: null });
        }
      } catch {
        finished = true;
        if (active) setSource({ kind: "failed" });
      }
    })();
    return () => {
      active = false;
      unlisten?.();
      if (jobId && !finished) void bridge.cancelPlayback?.(jobId).catch(() => undefined);
    };
  }, [bridge, relativePath]);

  return source;
}
