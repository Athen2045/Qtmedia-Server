import { useEffect, useLayoutEffect, useRef, useState } from "react";

import type { DesktopBridge, LibraryEntry, SignalPath } from "../lib/bridge";
import { readable, rgb, useCoverColor } from "../lib/coverColor";
import { formatDuration, mediaTitle } from "../lib/library";
import { useLyrics, useTrackInfo } from "../lib/lyrics";
import { useBluetoothDelay } from "../lib/bluetoothDelay";
import { usePlayer, usePlayerPosition, type PlayerValue } from "../lib/player";
import { describeOutput, describeSource, signalBadge, signalReason } from "../lib/signalPath";
import { useDragReorder } from "../lib/useDragReorder";
import { Artwork } from "./Artwork";
import { Icon } from "./Icon";
import { LyricsPanel } from "./Lyrics";

function time(seconds: number) {
  return formatDuration(Number.isFinite(seconds) ? Math.max(0, seconds) : 0);
}

const LOCKED_VOLUME = "Bit-perfect: use your amplifier or DAC volume";

const playbackErrors: Record<string, string> = {
  audio_device_lost: "The audio device was disconnected",
  audio_device_busy: "Another app is using the audio device",
  audio_exclusive_denied: "Windows blocked exclusive mode for this device",
  audio_format_unsupported: "The device can't play this file",
  audio_decode_failed: "This file is damaged or can't be decoded",
  audio_io: "This file could not be read",
  audio_unavailable: "Audio output is unavailable",
  audio_hands_free_only: "This headset is only available in call mode; reconnect it or pick another output",
};

function playbackError(code: string | null) {
  return (code && playbackErrors[code]) || "This file could not be played";
}

/** Player bar quality chip, e.g. "Bit-perfect" or "Bluetooth · not lossless". */
function SignalChip({ player, fallback }: { player: PlayerValue; fallback: string }) {
  if (!player.signal) return <>{fallback}</>;
  const badge = signalBadge(player.signal);
  return <span className={`signal-chip signal-chip--${badge.tone}`} title={`${describeSource(player.signal.source)} → ${describeOutput(player.signal.output)}`}>{badge.label}</span>;
}

/** "Lossy source": the FLAC holds a decoded lossy stream (YouTube Opus/AAC). */
export function LossySourceChip({ source }: { source: string | null | undefined }) {
  if (!source) return null;
  const detail = source === "unknown"
    ? "Made by FFmpeg from what was most likely a lossy stream (YouTube Opus or AAC). FLAC keeps that sound exactly but cannot add back what the stream left out."
    : `Downloaded as ${source} and saved as FLAC. FLAC keeps that sound exactly but cannot add back what the stream left out.`;
  return <span className="signal-chip signal-chip--warn" title={detail}>Lossy source</span>;
}

/** Now Playing: just the quality chip; the path and reason are in its tooltip. */
function SignalDetails({ signal }: { signal: SignalPath | null }) {
  if (!signal) return null;
  const badge = signalBadge(signal);
  const details = [
    `${describeSource(signal.source)} → ${describeOutput(signal.output)}${signal.device ? ` · ${signal.device.name}` : ""}`,
    signalReason(signal),
    signal.volumeLocked ? `${LOCKED_VOLUME}.` : null,
  ].filter(Boolean).join("\n");
  return (
    <div className="np-signal" aria-label="Signal path">
      <span className={`signal-chip signal-chip--${badge.tone}`} title={details}>{badge.label}</span>
    </div>
  );
}

/** Seek/volume slider: native range input styled as a thin track with a fill.
 * With `live={false}` a pointer drag only moves the thumb and reports once,
 * on release (one seek instead of one per pixel); keys report each step. */
function Slider({ label, value, max, onChange, className = "", disabled = false, title, live = true }: { label: string; value: number; max: number; onChange: (value: number) => void; className?: string; disabled?: boolean; title?: string; live?: boolean }) {
  const [dragValue, setDragValue] = useState<number | null>(null);
  const draggingRef = useRef(false);
  const dragValueRef = useRef<number | null>(null);
  const shown = dragValue ?? value;
  const percent = max > 0 ? Math.min(100, (shown / max) * 100) : 0;
  const finish = () => {
    if (!draggingRef.current) return;
    draggingRef.current = false;
    const committed = dragValueRef.current;
    dragValueRef.current = null;
    setDragValue(null);
    if (committed !== null) onChange(committed);
  };
  return (
    <input
      type="range"
      className={`slider ${className}`}
      aria-label={label}
      min={0}
      max={max || 1}
      step={max > 1 ? 1 : 0.01}
      value={Math.min(shown, max || 1)}
      disabled={disabled || !max}
      title={title}
      style={{ "--fill": `${percent}%` } as React.CSSProperties}
      onPointerDown={() => { if (!live) draggingRef.current = true; }}
      onPointerUp={finish}
      onPointerCancel={finish}
      onLostPointerCapture={finish}
      onBlur={finish}
      onChange={(event) => {
        const next = Number(event.target.value);
        if (draggingRef.current) {
          dragValueRef.current = next;
          setDragValue(next);
        } else {
          onChange(next);
        }
      }}
    />
  );
}

/** Elapsed time, seek bar and length. Re-renders with the position on its own. */
function SeekBar({ player, className, max }: { player: PlayerValue; className?: string; max: number }) {
  const position = usePlayerPosition();
  return (
    <>
      <span>{time(position)}</span>
      <Slider label="Seek" className={className} value={position} max={max} onChange={player.seek} live={false} />
      <span>{time(player.duration)}</span>
    </>
  );
}

/** Lyrics follow what is heard: on Bluetooth, the headset's own delay is
 * taken off the engine's clock (Settings → Audio → Lyrics delay). */
function PositionedLyrics({ bluetooth, ...props }: Omit<React.ComponentProps<typeof LyricsPanel>, "position"> & { bluetooth: boolean }) {
  const position = usePlayerPosition();
  const delayMs = useBluetoothDelay();
  const heard = bluetooth ? Math.max(0, position - delayMs / 1000) : position;
  return <LyricsPanel {...props} position={heard} />;
}

function Transport({ player, large = false }: { player: PlayerValue; large?: boolean }) {
  const idle = !player.current;
  return (
    <div className={`transport ${large ? "transport--large" : ""}`}>
      <button type="button" className={`transport-btn ${player.shuffle ? "is-on" : ""}`} aria-label="Shuffle" aria-pressed={player.shuffle} disabled={idle} onClick={player.toggleShuffle}><Icon name="shuffle" /></button>
      <button type="button" className="transport-btn" aria-label="Previous" disabled={idle} onClick={player.prev}><Icon name="prev" /></button>
      <button type="button" className="transport-main" aria-label={player.playing ? "Pause" : "Play"} disabled={idle} onClick={player.toggle}><Icon name={player.playing ? "pause" : "play"} /></button>
      <button type="button" className="transport-btn" aria-label="Next" disabled={idle} onClick={player.next}><Icon name="next" /></button>
      <button type="button" className={`transport-btn ${player.repeat !== "off" ? "is-on" : ""}`} aria-label={`Repeat: ${player.repeat}`} disabled={idle} onClick={player.cycleRepeat}><Icon name={player.repeat === "one" ? "repeatOne" : "repeat"} /></button>
    </div>
  );
}

/** Full-width player bar. Shown whenever a track is loaded, and idle on Music. */
export function PlayerBar({ bridge }: { bridge: DesktopBridge }) {
  const player = usePlayer();
  const current = player.current;
  const title = current ? mediaTitle(current) : "Nothing playing";
  const volumeLocked = Boolean(player.signal?.volumeLocked);
  const info = useTrackInfo(bridge, current);
  return (
    <footer className="player-bar" aria-label="Music player">
      <div className="player-now">
        {current ? (
          <button type="button" className="player-now__open" aria-label="Open Now Playing" onClick={player.openNowPlaying}>
            <Artwork bridge={bridge} entry={current} name={title} className="player-art" />
          </button>
        ) : <span className="player-art artwork artwork--empty"><Icon name="music" /></span>}
        <div className="player-now__copy">
          <strong title={title}>{title}</strong>
          <span>{player.failed ? playbackError(player.error) : current ? <><SignalChip player={player} fallback="From your library" /> <LossySourceChip source={info?.lossySource} /></> : "Pick a song to start"}</span>
        </div>
      </div>
      <div className="player-center">
        <Transport player={player} />
        <div className="player-time">
          <SeekBar player={player} max={current ? player.duration : 0} />
        </div>
      </div>
      <div className="player-right">
        <button type="button" className="transport-btn" aria-label="Open Now Playing" disabled={!current} onClick={player.openNowPlaying}><Icon name="queue" /></button>
        <button type="button" className="transport-btn" aria-label={player.muted ? "Unmute" : "Mute"} disabled={volumeLocked} onClick={player.toggleMute}><Icon name={player.muted || player.volume === 0 ? "mute" : "volume"} /></button>
        <Slider label="Volume" className="slider--volume" value={volumeLocked ? 1 : player.muted ? 0 : player.volume} max={1} onChange={player.setVolume} disabled={volumeLocked} title={volumeLocked ? LOCKED_VOLUME : undefined} />
      </div>
    </footer>
  );
}

type Cover = { key: string; src: string | null };

/** Matches the np-backdrop-in animation in app.css. */
const BACKDROP_FADE_MS = 1400;

/**
 * The cover of the current track once it has loaded. Until then it keeps the
 * previous track's cover, so the backdrop and tint never flash to a placeholder
 * between songs; they change once, when the next cover is ready.
 */
function useSettledCover(bridge: DesktopBridge, entry: LibraryEntry | null): Cover | null {
  const [cover, setCover] = useState<Cover | null>(null);
  const key = entry?.relativePath ?? null;
  const path = entry?.artworkPath ?? null;
  useEffect(() => {
    if (!key) return;
    let live = true;
    if (!path) setCover({ key, src: null });
    else {
      bridge.readArtwork(path)
        .then((src) => { if (live) setCover({ key, src }); })
        .catch(() => { if (live) setCover({ key, src: null }); });
    }
    return () => { live = false; };
  }, [bridge, key, path]);
  return cover;
}

/**
 * Stacks a new blurred backdrop over the old one and fades it in, so the
 * background flows from one song's colours into the next. The old layer is
 * dropped once the new one is fully opaque.
 */
function Backdrop({ cover }: { cover: Cover | null }) {
  const [layers, setLayers] = useState<Array<Cover & { id: number }>>([]);
  const nextId = useRef(0);
  const last = layers[layers.length - 1];
  if (cover && (!last || last.key !== cover.key || last.src !== cover.src)) {
    nextId.current += 1;
    // Keep at most the layer underneath plus the one fading in.
    setLayers([...layers.slice(-1), { ...cover, id: nextId.current }]);
  }
  // Fallback for when animationend never fires (e.g. the window is hidden).
  useEffect(() => {
    if (layers.length < 2) return;
    const timer = window.setTimeout(() => setLayers((current) => current.slice(-1)), BACKDROP_FADE_MS + 200);
    return () => window.clearTimeout(timer);
  }, [layers]);
  return (
    <>
      {layers.map((layer, position) => (
        <div
          key={layer.id}
          className="np-backdrop"
          aria-hidden="true"
          style={layer.src ? { backgroundImage: `url("${layer.src}")` } : undefined}
          onAnimationEnd={position === layers.length - 1 ? () => setLayers((current) => current.slice(-1)) : undefined}
        />
      ))}
    </>
  );
}

/** Up Next: the playing song, then everything after it, which can be dragged into a new order. */
function UpNext({ bridge, player }: { bridge: DesktopBridge; player: PlayerValue }) {
  const listRef = useRef<HTMLOListElement>(null);
  // The whole queue: played songs (dimmed) above the playing one, so any song
  // can be dragged anywhere, including above the song that is playing.
  const { itemProps, listClassName, dragging } = useDragReorder({
    count: player.queue.length,
    onMove: player.moveInQueue,
    list: listRef,
    scroller: listRef,
  });
  const currentKey = player.current?.relativePath;
  // Bring the playing song near the top when Up Next opens and when the song
  // changes, leaving a little of the played songs above it.
  useLayoutEffect(() => {
    const list = listRef.current;
    const row = list?.querySelector<HTMLElement>("[aria-current=true]")?.closest("li");
    if (!list || !row || dragging) return;
    list.scrollTop = Math.max(0, row.offsetTop - list.offsetTop - row.offsetHeight * 0.6);
  }, [currentKey]); // only when the song changes, not on every reorder
  const seen = new Map<string, number>();
  return (
    <section className="np-queue" aria-label="Up next">
      <h3>Up Next{player.queue.length > 1 ? <span className="np-queue__hint">Drag to reorder</span> : null}</h3>
      <ol ref={listRef} className={listClassName}>
        {player.queue.map((entry, index) => {
          const name = mediaTitle(entry);
          const current = index === player.index;
          const past = index < player.index;
          // Stable keys let rows keep their identity when the order changes.
          const repeat = seen.get(entry.relativePath) ?? 0;
          seen.set(entry.relativePath, repeat + 1);
          const { className, ...drag } = itemProps(index);
          return (
            <li key={`${entry.relativePath}#${repeat}`} className={`${className} is-movable`} {...drag}>
              <button
                type="button"
                className={`np-item ${current ? "is-current" : ""} ${past ? "is-past" : ""}`}
                aria-current={current ? "true" : undefined}
                aria-description="Drag, or press Alt and an arrow key, to move"
                onClick={() => player.playAt(index)}
              >
                <Artwork bridge={bridge} entry={entry} name={name} className="np-item__art" />
                <span className="np-item__copy"><strong>{name}</strong><span>{current ? (player.playing ? "Playing" : "Paused") : past ? "Played" : "From your library"}</span></span>
                <span className="np-item__time">{entry.durationSeconds !== null ? formatDuration(entry.durationSeconds) : ""}</span>
                <span className="np-item__grip" aria-hidden="true"><Icon name="grip" /></span>
              </button>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

/**
 * Full-window Now Playing. The backdrop is the current cover itself, enlarged and
 * heavily blurred, so the colours follow the artwork; a colour sampled from the
 * cover tints the scrim (and stands in when a track has no artwork) and drives the
 * progress fill.
 */
export function NowPlaying({ bridge }: { bridge: DesktopBridge }) {
  const player = usePlayer();
  const current = player.current;
  const cover = useSettledCover(bridge, current);
  const art = cover?.src ?? null;
  const title = current ? mediaTitle(current) : "";
  // The tint follows the settled cover, and CSS eases it to the new colour.
  const tint = useCoverColor(art, cover?.key ?? title);
  const closeRef = useRef<HTMLButtonElement>(null);
  const lyrics = useLyrics(bridge, player.nowPlayingOpen ? current : null);
  const info = useTrackInfo(bridge, player.nowPlayingOpen ? current : null);
  const rootRef = useRef<HTMLDivElement>(null);
  // null = automatic: lyrics when the song has them, otherwise Up Next.
  const [choice, setChoice] = useState<"lyrics" | "queue" | null>(null);

  useEffect(() => {
    if (!player.nowPlayingOpen) return;
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      // Space is handled by the app-wide music shortcuts.
      if (event.key === "Escape") player.closeNowPlaying();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [player.nowPlayingOpen, player.closeNowPlaying]);

  if (!player.nowPlayingOpen || !current) return null;
  const accent = readable(tint, 150);
  const view = choice ?? (lyrics.status === "none" ? "queue" : "lyrics");
  // Tags first; untagged songs fall back to the lyrics' LRC headers.
  const meta = lyrics.status === "ready" ? lyrics.lyrics.meta : undefined;
  const shownTitle = info?.title || title;
  const artist = info?.artist || meta?.artist || null;
  const album = info?.album || meta?.album || null;
  // Depth: the cover tilts toward the pointer and the backdrop drifts away.
  const onPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    const x = ((event.clientX - box.left) / box.width - 0.5) * 2;
    const y = ((event.clientY - box.top) / box.height - 0.5) * 2;
    event.currentTarget.style.setProperty("--px", x.toFixed(3));
    event.currentTarget.style.setProperty("--py", y.toFixed(3));
  };
  const onPointerLeave = () => {
    rootRef.current?.style.setProperty("--px", "0");
    rootRef.current?.style.setProperty("--py", "0");
  };

  return (
    <div
      ref={rootRef}
      className="now-playing"
      onPointerMove={onPointerMove}
      onPointerLeave={onPointerLeave}
      role="dialog"
      aria-modal="true"
      aria-label={`Now playing: ${shownTitle}${artist ? ` by ${artist}` : ""}`}
      style={{ "--np-tint": rgb(tint), "--np-accent": rgb(accent) } as React.CSSProperties}
    >
      <Backdrop cover={cover} />
      <div className="np-scrim" aria-hidden="true" />
      <div className="np-drag" aria-hidden="true" data-tauri-drag-region />
      <button ref={closeRef} type="button" className="np-round np-close" aria-label="Close Now Playing" onClick={player.closeNowPlaying}><Icon name="chevron" /></button>

      <div className="np-body">
        <div className="np-hero">
          <div className="np-cover-stage">
            <div key={`glow-${cover?.key}`} className="np-cover-glow" aria-hidden="true" style={art ? { backgroundImage: `url("${art}")` } : undefined} />
            {art
              ? <img key={cover?.key} className="artwork np-cover" src={art} alt={`Artwork for ${shownTitle}`} />
              : <div key={cover?.key ?? "none"} className="artwork artwork--empty np-cover"><Icon name="music" /></div>}
          </div>
          <h2 title={shownTitle}>{shownTitle}</h2>
          {artist ? <p className="np-artist">{artist}</p> : <p>From your library</p>}
          {album ? <p className="np-album">{album}</p> : null}
          <SignalDetails signal={player.signal} />
          {info?.lossySource ? <div className="np-signal"><LossySourceChip source={info.lossySource} /></div> : null}
        </div>
        {view === "lyrics" ? (
          <section className="np-side" aria-label="Lyrics view">
            <PositionedLyrics bluetooth={player.signal?.device?.transport === "bluetooth" || player.signal?.reason === "bluetooth_output"} state={lyrics} playing={player.playing} onSeek={player.seek} trackKey={current.relativePath} />
          </section>
        ) : (
          <UpNext bridge={bridge} player={player} />
        )}
      </div>

      <div className="np-controls">
        <div className="np-progress">
          <SeekBar player={player} className="slider--np" max={player.duration} />
        </div>
        <Transport player={player} large />
      </div>
      <button
        type="button"
        className={`np-round np-switch ${view === "lyrics" ? "is-on" : ""}`}
        aria-label={view === "lyrics" ? "Show Up Next" : "Show lyrics"}
        aria-pressed={view === "lyrics"}
        title={view === "lyrics" ? "Up Next" : "Lyrics"}
        onClick={() => setChoice(view === "lyrics" ? "queue" : "lyrics")}
      >
        <Icon name={view === "lyrics" ? "queue" : "lyrics"} />
      </button>
    </div>
  );
}
