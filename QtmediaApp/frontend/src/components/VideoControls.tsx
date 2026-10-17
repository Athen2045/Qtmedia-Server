import { Controls, FullscreenButton, Gesture, Hotkey, MuteButton, PlayButton, SeekButton, Time, TimeSlider, VolumeSlider } from "@videojs/react";
import { useEffect, useRef, useState } from "react";

import { Icon } from "./Icon";

/** Matches the ←/→ and J/L hotkeys below. */
export const SKIP_SECONDS = 10;
export const SPEEDS = [0.5, 0.75, 1, 1.25, 1.5, 2] as const;

export type SubtitleOption = { id: string; label: string };

export type VideoControlsProps = {
  video: HTMLVideoElement | null;
  /** Previous/next video buttons; omitted for a single video. */
  navigation?: { previous: { title: string; go: () => void } | null; next: { title: string; go: () => void } | null };
  /** A short note above the bar ("Resumed at…", "Subtitles added."). */
  note?: React.ReactNode;
  stable: { enabled: boolean; toggle: () => void } | null;
  autoplay: { on: boolean; toggle: () => void } | null;
  subtitles: {
    options: SubtitleOption[];
    /** Turns a track on (or all off with null). */
    choose: (id: string | null) => void;
    /** The track to use when CC is switched on. */
    preferred: () => string | null;
    add?: () => void;
    /** Picture-based tracks in the file that can't be shown. */
    unsupported: number;
  };
};

function SkipIcon({ forward }: { forward?: boolean }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d={forward ? "M12 5V2l5 4-5 4V7a6 6 0 1 0 6 6" : "M12 5V2L7 6l5 4V7a6 6 0 1 1-6 6"} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      <text x={forward ? 11.6 : 12.4} y="16.6" textAnchor="middle" fontSize="7" fontWeight="700" fill="currentColor">{SKIP_SECONDS}</text>
    </svg>
  );
}

/** The track currently showing on the element, kept in sync with its change events. */
function useShowingTrack(video: HTMLVideoElement | null, options: SubtitleOption[]) {
  const [showing, setShowing] = useState<string | null>(null);
  useEffect(() => {
    const list = video?.textTracks;
    if (!list || typeof list.addEventListener !== "function") {
      setShowing(null);
      return;
    }
    const read = () => setShowing(Array.from(list).find((track) => track.kind === "subtitles" && track.mode === "showing")?.id ?? null);
    read();
    list.addEventListener("change", read);
    return () => list.removeEventListener("change", read);
  }, [video, options]);
  return options.some((option) => option.id === showing) ? showing : null;
}

function usePlaybackRate(video: HTMLVideoElement | null) {
  const [rate, setRate] = useState(1);
  useEffect(() => {
    if (!video) return;
    const read = () => setRate(video.playbackRate || 1);
    read();
    video.addEventListener("ratechange", read);
    return () => video.removeEventListener("ratechange", read);
  }, [video]);
  return rate;
}

const speedLabel = (rate: number) => (rate === 1 ? "Normal" : `${rate}×`);

/**
 * The player's single control bar (design/2026-10-18-video-controls):
 * Previous · −10 · Play · +10 · Next | volume · time · seek | CC · settings · full screen.
 * Built from Video.js parts instead of its packaged skin, so the bar keeps the
 * same pixel size in full screen and holds our own settings menu.
 */
export function VideoControls({ video, navigation, note, stable, autoplay, subtitles }: VideoControlsProps) {
  const [menu, setMenu] = useState<null | "main" | "subtitles" | "speed">(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const gearRef = useRef<HTMLButtonElement>(null);
  const showing = useShowingTrack(video, subtitles.options);
  const rate = usePlaybackRate(video);
  const hasSubtitles = subtitles.options.length > 0;

  // Close on a press outside the menu, and on Esc (without closing the player).
  useEffect(() => {
    if (!menu) return;
    const onPointer = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!menuRef.current?.contains(target) && !gearRef.current?.contains(target)) setMenu(null);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.stopPropagation();
      setMenu((page) => (page === "main" ? null : "main"));
      if (menu === "main") gearRef.current?.focus();
    };
    window.addEventListener("pointerdown", onPointer, true);
    window.addEventListener("keydown", onKey, true);
    return () => {
      window.removeEventListener("pointerdown", onPointer, true);
      window.removeEventListener("keydown", onKey, true);
    };
  }, [menu]);

  // Focus the first item whenever a menu page opens.
  useEffect(() => {
    if (menu) menuRef.current?.querySelector<HTMLElement>("[role^=menuitem]")?.focus();
  }, [menu]);

  const toggleCaptions = () => subtitles.choose(showing ? null : subtitles.preferred() ?? subtitles.options[0]?.id ?? null);
  const setRate = (value: number) => {
    if (video) video.playbackRate = value;
    setMenu("main");
  };
  const onMenuKey = (event: React.KeyboardEvent) => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    const items = [...(menuRef.current?.querySelectorAll<HTMLElement>("[role^=menuitem]") ?? [])];
    const at = items.indexOf(document.activeElement as HTMLElement);
    items[(at + (event.key === "ArrowDown" ? 1 : items.length - 1)) % items.length]?.focus();
  };

  return (
    <>
      {/* Same shortcuts and clicks as the packaged skin. */}
      <Hotkey keys="Space" action="togglePaused" />
      <Hotkey keys="k" action="togglePaused" />
      <Hotkey keys="m" action="toggleMuted" />
      <Hotkey keys="f" action="toggleFullscreen" />
      <Hotkey keys="c" action="toggleSubtitles" />
      <Hotkey keys="ArrowLeft" action="seekStep" value={-SKIP_SECONDS} />
      <Hotkey keys="ArrowRight" action="seekStep" value={SKIP_SECONDS} />
      <Hotkey keys="j" action="seekStep" value={-SKIP_SECONDS} />
      <Hotkey keys="l" action="seekStep" value={SKIP_SECONDS} />
      <Hotkey keys="ArrowUp" action="volumeStep" />
      <Hotkey keys="ArrowDown" action="volumeStep" />
      <Hotkey keys="0-9" action="seekToPercent" />
      <Hotkey keys=">" action="speedUp" />
      <Hotkey keys="<" action="speedDown" />
      <Gesture type="tap" action="togglePaused" pointer="mouse" region="center" />
      <Gesture type="tap" action="toggleControls" pointer="touch" />
      <Gesture type="doubletap" action="seekStep" value={-SKIP_SECONDS} region="left" />
      <Gesture type="doubletap" action="toggleFullscreen" region="center" />
      <Gesture type="doubletap" action="seekStep" value={SKIP_SECONDS} region="right" />

      {/* The menu keeps the controls on screen while it is open. */}
      <Controls.Root visibility={menu ? "always" : "auto"}>
        <Controls.Backdrop className="vbar-shade" />
        <Controls.Content className="vbar-layer">
          {note ? <div className="vbar-note">{note}</div> : null}
          <Controls.Group className="vbar" aria-label="Video controls">
            {navigation ? (
              <button type="button" className="vbar-btn" aria-label="Previous video" title={navigation.previous ? `Previous: ${navigation.previous.title} (Shift+P)` : "No previous video"} disabled={!navigation.previous} onClick={navigation.previous?.go}>
                <Icon name="prev" />
              </button>
            ) : null}
            <SeekButton seconds={-SKIP_SECONDS} className="vbar-btn" aria-label={`Back ${SKIP_SECONDS} seconds`} title={`Back ${SKIP_SECONDS} seconds (←)`}><SkipIcon /></SeekButton>
            <PlayButton className="vbar-btn vbar-btn--main" render={(props, state) => <button {...props} title={state.paused ? "Play (Space)" : "Pause (Space)"}><Icon name={state.paused ? "play" : "pause"} /></button>} />
            <SeekButton seconds={SKIP_SECONDS} className="vbar-btn" aria-label={`Forward ${SKIP_SECONDS} seconds`} title={`Forward ${SKIP_SECONDS} seconds (→)`}><SkipIcon forward /></SeekButton>
            {navigation ? (
              <button type="button" className="vbar-btn" aria-label="Next video" title={navigation.next ? `Next: ${navigation.next.title} (Shift+N)` : "No next video"} disabled={!navigation.next} onClick={navigation.next?.go}>
                <Icon name="next" />
              </button>
            ) : null}
            <span className="vbar-sep" aria-hidden="true" />
            <div className="vbar-volume">
              <MuteButton className="vbar-btn" render={(props, state) => <button {...props} title={state.muted ? "Unmute (M)" : "Mute (M)"}><Icon name={state.muted ? "mute" : "volume"} /></button>} />
              <VolumeSlider.Root className="vslider vslider--volume">
                <VolumeSlider.Track className="vslider-track"><VolumeSlider.Fill className="vslider-fill" /></VolumeSlider.Track>
                <VolumeSlider.Thumb className="vslider-thumb" />
              </VolumeSlider.Root>
            </div>
            <Time.Group className="vbar-time">
              <Time.Value type="current" />
              <Time.Separator> / </Time.Separator>
              <Time.Value type="duration" />
            </Time.Group>
            <TimeSlider.Root className="vslider vslider--seek">
              <TimeSlider.Track className="vslider-track">
                <TimeSlider.Buffer className="vslider-buffer" />
                <TimeSlider.Fill className="vslider-fill" />
              </TimeSlider.Track>
              <TimeSlider.Thumb className="vslider-thumb" />
              <TimeSlider.Preview className="vslider-preview"><TimeSlider.Value type="pointer" /></TimeSlider.Preview>
            </TimeSlider.Root>
            {hasSubtitles ? (
              <button type="button" className={`vbar-btn vbar-cc ${showing ? "is-on" : ""}`} aria-label="Subtitles" aria-pressed={Boolean(showing)} title={showing ? "Subtitles off (C)" : "Subtitles on (C)"} onClick={toggleCaptions}>
                <Icon name="cc" />
              </button>
            ) : null}
            <button ref={gearRef} type="button" className={`vbar-btn ${menu ? "is-open" : ""}`} aria-label="Settings" aria-haspopup="menu" aria-expanded={Boolean(menu)} title="Settings" onClick={() => setMenu(menu ? null : "main")}>
              <Icon name="gear" />
            </button>
            <FullscreenButton className="vbar-btn" render={(props, state) => <button {...props} title={state.fullscreen ? "Exit full screen (F)" : "Full screen (F)"}><Icon name={state.fullscreen ? "exitFullscreen" : "fullscreen"} /></button>} />
          </Controls.Group>

          {menu ? (
            <div ref={menuRef} className="vmenu" role="menu" aria-label={menu === "main" ? "Settings" : menu === "subtitles" ? "Subtitles" : "Speed"} onKeyDown={onMenuKey}>
              {menu === "main" ? (
                <>
                  {stable ? (
                    <button type="button" role="menuitemcheckbox" aria-checked={stable.enabled} aria-label="Stable volume" aria-description="Evens out loud and quiet parts" className="vmenu-row" onClick={stable.toggle}>
                      <Icon name="wave" /><span className="vmenu-label">Stable volume<small>Evens out loud and quiet parts</small></span><span className={`vmenu-switch ${stable.enabled ? "is-on" : ""}`} aria-hidden="true" />
                    </button>
                  ) : null}
                  {autoplay ? (
                    <button type="button" role="menuitemcheckbox" aria-checked={autoplay.on} aria-label="Autoplay next" className="vmenu-row" onClick={autoplay.toggle}>
                      <Icon name="autoplay" /><span className="vmenu-label">Autoplay next</span><span className={`vmenu-switch ${autoplay.on ? "is-on" : ""}`} aria-hidden="true" />
                    </button>
                  ) : null}
                  {stable || autoplay ? <span className="vmenu-sep" role="separator" /> : null}
                  <button type="button" role="menuitem" className="vmenu-row" onClick={() => setMenu("subtitles")}>
                    <Icon name="cc" /><span className="vmenu-label">Subtitles</span>
                    <span className="vmenu-value">{showing ? subtitles.options.find((option) => option.id === showing)?.label : hasSubtitles ? "Off" : "None"}</span><Icon name="forward" className="vmenu-chev" />
                  </button>
                  <button type="button" role="menuitem" className="vmenu-row" onClick={() => setMenu("speed")}>
                    <Icon name="speed" /><span className="vmenu-label">Speed</span><span className="vmenu-value">{speedLabel(rate)}</span><Icon name="forward" className="vmenu-chev" />
                  </button>
                </>
              ) : menu === "subtitles" ? (
                <>
                  <button type="button" role="menuitem" className="vmenu-head" onClick={() => setMenu("main")}><Icon name="back" />Subtitles</button>
                  {hasSubtitles ? (
                    [{ id: null as string | null, label: "Off" }, ...subtitles.options].map((option) => (
                      <button key={option.id ?? "off"} type="button" role="menuitemradio" aria-checked={showing === option.id} className="vmenu-row vmenu-row--check" onClick={() => subtitles.choose(option.id)}>
                        <Icon name="check" className="vmenu-tick" /><span className="vmenu-label">{option.label}</span>
                      </button>
                    ))
                  ) : <p className="vmenu-empty">This video has no subtitles.</p>}
                  {subtitles.unsupported > 0 ? <p className="vmenu-empty" role="note">This video's subtitles are pictures, which can't be shown here.</p> : null}
                  {subtitles.add ? (
                    <>
                      <span className="vmenu-sep" role="separator" />
                      <button type="button" role="menuitem" className="vmenu-row vmenu-row--add" onClick={() => { setMenu(null); subtitles.add?.(); }}>
                        <Icon name="plus" /><span className="vmenu-label">Add subtitle file…<small>.srt or .vtt</small></span>
                      </button>
                    </>
                  ) : null}
                </>
              ) : (
                <>
                  <button type="button" role="menuitem" className="vmenu-head" onClick={() => setMenu("main")}><Icon name="back" />Speed</button>
                  {SPEEDS.map((value) => (
                    <button key={value} type="button" role="menuitemradio" aria-checked={rate === value} className="vmenu-row vmenu-row--check" onClick={() => setRate(value)}>
                      <Icon name="check" className="vmenu-tick" /><span className="vmenu-label">{speedLabel(value)}</span>
                    </button>
                  ))}
                </>
              )}
            </div>
          ) : null}
        </Controls.Content>
      </Controls.Root>
    </>
  );
}
