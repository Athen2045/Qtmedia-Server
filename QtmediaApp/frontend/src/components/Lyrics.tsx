import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { activeLineIndex, type Lyrics, type LyricsState } from "../lib/lyrics";

/** How long a manual scroll pauses auto-centring. */
const MANUAL_SCROLL_PAUSE_MS = 2500;

/**
 * Smooths the player position between `timeupdate` events (about 4 per second)
 * so lines change on the beat rather than up to 250 ms late.
 */
function useSmoothPosition(position: number, playing: boolean) {
  const anchor = useRef({ position, at: performance.now() });
  const [smooth, setSmooth] = useState(position);
  useEffect(() => {
    anchor.current = { position, at: performance.now() };
    setSmooth(position);
  }, [position]);
  useEffect(() => {
    if (!playing) return;
    let frame = 0;
    const tick = () => {
      const { position: base, at } = anchor.current;
      // Never run more than one update interval ahead of the real clock.
      setSmooth(base + Math.min(0.35, (performance.now() - at) / 1000));
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing]);
  return smooth;
}

export function LyricsPanel({ state, position, playing, onSeek, trackKey }: {
  state: LyricsState;
  position: number;
  playing: boolean;
  onSeek: (seconds: number) => void;
  trackKey: string;
}) {
  if (state.status === "loading") {
    return <div className="np-lyrics np-lyrics--loading" role="status" aria-label="Looking for lyrics"><span /><span /><span /></div>;
  }
  if (state.status === "none") {
    return <div className="np-lyrics np-lyrics--empty"><p>No lyrics found for this song.</p><span>Add a matching .lrc file next to the song to use your own.</span></div>;
  }
  return state.lyrics.kind === "synced"
    ? <SyncedLyrics key={trackKey} lyrics={state.lyrics} position={position} playing={playing} onSeek={onSeek} />
    : (
      <div className="np-lyrics np-lyrics--plain" tabIndex={0} aria-label="Lyrics">
        <p>{state.lyrics.text}</p>
        <Credit source={state.lyrics.source} synced={false} />
      </div>
    );
}

/** Credits LRCLIB; the user's own .lrc files need no label. */
function Credit({ source, synced }: { source: Lyrics["source"]; synced: boolean }) {
  if (source === "local") return synced ? null : <span className="np-lyrics__credit">Not time-synced</span>;
  return <span className="np-lyrics__credit">Lyrics from LRCLIB{synced ? "" : " · not time-synced"}</span>;
}

function SyncedLyrics({ lyrics, position, playing, onSeek }: { lyrics: Extract<Lyrics, { kind: "synced" }>; position: number; playing: boolean; onSeek: (seconds: number) => void }) {
  const [offset, setOffset] = useState(0);
  const smooth = useSmoothPosition(position, playing);
  const active = activeLineIndex(lyrics.lines, smooth + offset);
  const scroller = useRef<HTMLDivElement>(null);
  const manualUntil = useRef(0);

  const pauseAutoScroll = () => { manualUntil.current = performance.now() + MANUAL_SCROLL_PAUSE_MS; };

  // Keep the active line centred (unless the user is reading elsewhere).
  useLayoutEffect(() => {
    const box = scroller.current;
    if (!box || performance.now() < manualUntil.current) return;
    const line = box.querySelectorAll<HTMLElement>(".lyric-line")[Math.max(0, active)];
    if (!line) return;
    const top = line.offsetTop - box.clientHeight / 2 + line.offsetHeight / 2;
    if (typeof box.scrollTo === "function") box.scrollTo({ top, behavior: "smooth" });
  }, [active]);

  return (
    <div className="np-lyrics-wrap">
      <div className="np-sync" role="group" aria-label="Lyrics timing">
        <button type="button" className="np-sync__btn" aria-label="Show lyrics later" onClick={() => setOffset((value) => value - 0.5)}>−</button>
        <span aria-live="polite">{offset === 0 ? "In sync" : `${offset > 0 ? "+" : ""}${offset.toFixed(1)}s`}</span>
        <button type="button" className="np-sync__btn" aria-label="Show lyrics earlier" onClick={() => setOffset((value) => value + 0.5)}>+</button>
      </div>
      <div
        ref={scroller}
        className={`np-lyrics ${active === -1 ? "is-waiting" : ""}`}
        aria-label="Lyrics"
        onWheel={pauseAutoScroll}
        onTouchMove={pauseAutoScroll}
        onKeyDown={pauseAutoScroll}
      >
        <div className="np-lyrics__pad" aria-hidden="true" />
        {lyrics.lines.map((line, index) => {
          const distance = active === -1 ? Math.min(index + 1, 4) : Math.abs(index - active);
          return (
            <button
              key={`${line.time}-${index}`}
              type="button"
              className={`lyric-line ${index === active ? "is-active" : ""} ${index < active ? "is-past" : ""}`}
              style={{ "--d": Math.min(distance, 5) } as React.CSSProperties}
              aria-current={index === active ? "true" : undefined}
              onClick={() => { manualUntil.current = 0; onSeek(Math.max(0, line.time - offset)); }}
            >
              {line.text || <span className="lyric-gap" aria-label="Instrumental">• • •</span>}
            </button>
          );
        })}
        <div className="np-lyrics__pad" aria-hidden="true" />
      </div>
      <Credit source={lyrics.source} synced />
    </div>
  );
}
