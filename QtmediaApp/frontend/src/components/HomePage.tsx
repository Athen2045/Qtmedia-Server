import { useRef, useState } from "react";

import { useDesktopSession } from "../lib/DesktopSession";
import type { DesktopBridge, FormatOption, LibraryEntry } from "../lib/bridge";
import { fileName, formatBytes, formatDuration } from "../lib/library";
import { readSearchMode, writeSearchMode, type SearchMode } from "../lib/modes";
import { describeProgress } from "../lib/progress";
import { useOptionalPlayer } from "../lib/player";
import { Icon } from "./Icon";
import { QMark } from "./QMark";

const errorMessages: Record<string, string> = {
  invalid_url: "Enter a valid direct media link.",
  unsupported_source: "This source is not supported by the approved adapters.",
  no_formats: "No compatible audio or video format was found.",
  format_unavailable: "That format is no longer available. Look up the link again.",
  download_failed: "The download could not be completed.",
  sidecar_unavailable: "The local media engine is unavailable.",
  provider_unavailable: "The source could not be reached right now.",
  source_blocked: "The site blocked this connection with an anti-bot check. This is common on VPNs. Turn on Settings → Network → Browser cookies (Firefox) and open the video once in Firefox, or try another VPN server.",
  cookies_unavailable: "Qtmedia could not read Firefox’s cookies. Open Firefox once, or turn off Settings → Network → Browser cookies.",
  source_changed: "This site changed and yt-dlp needs an update. Go to Settings → Media engine → Check for update.",
  clipboard_unavailable: "Qtmedia could not read the clipboard.",
  no_video_format: "This link has no video to save. Try Music mode.",
  no_music_format: "This link has no audio to save as music. Try Video mode.",
};

const qualityNames: Array<[number, string]> = [[2160, "4K"], [1440, "QHD"], [1080, "Full HD"], [720, "HD"], [480, "SD"], [0, "Low"]];

function describe(format: FormatOption) {
  if (format.kind === "audio") {
    // The engine's label carries the honest detail, e.g. "FLAC · from Opus 160 kbps".
    const detail = format.label.split(" · ")[1] ?? (format.bitrateKbps ? `${format.bitrateKbps} kbps` : "");
    return { name: format.extension.toUpperCase(), detail };
  }
  if (!format.height) return { name: "Video", detail: format.extension.toUpperCase() };
  return { name: `${format.height}p`, detail: qualityNames.find(([minimum]) => format.height! >= minimum)?.[1] ?? "Low" };
}

export function HomePage({ onOpenFiles, bridge, onPlayVideo }: { onOpenFiles: () => void; bridge?: DesktopBridge; onPlayVideo?: (entry: LibraryEntry) => void }) {
  const [input, setInput] = useState("");
  const [mode, setMode] = useState<SearchMode>(readSearchMode);
  const [clipboardError, setClipboardError] = useState(false);
  const [lastSite, setLastSite] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const { state, inspect, startDownload, cancelDownload, reset } = useDesktopSession();
  const player = useOptionalPlayer();
  const active = state.status !== "empty";
  const editable = state.status === "empty" || state.status === "error";
  if (state.status === "ready" && state.site !== lastSite) setLastSite(state.site);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const value = input.trim();
    if (!value) return;
    await inspect(value, mode);
    setInput("");
  };

  const chooseMode = (next: SearchMode) => {
    setMode(next);
    writeSearchMode(next);
  };

  const paste = async () => {
    setClipboardError(false);
    try {
      setInput(await navigator.clipboard.readText());
    } catch {
      setClipboardError(true);
    }
  };

  // Arrow keys move between format rows, like a native menu.
  const moveFocus = (event: React.KeyboardEvent) => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    const rows = [...(listRef.current?.querySelectorAll<HTMLButtonElement>(".format-row") ?? [])];
    const index = rows.indexOf(document.activeElement as HTMLButtonElement);
    const next = rows[Math.max(0, Math.min(rows.length - 1, index + (event.key === "ArrowDown" ? 1 : -1)))];
    next?.focus();
    event.preventDefault();
  };

  const videoFormats = state.status === "ready" ? state.formats.filter((format) => format.kind === "video") : [];
  const audioFormats = state.status === "ready" ? state.formats.filter((format) => format.kind === "audio") : [];
  const progress = state.status === "downloading" || state.status === "cancelling" ? describeProgress(state) : null;
  const playSaved = () => {
    if (state.status !== "completed") return;
    if (state.entry.mediaType === "audio" && player?.available) {
      player.playQueue([state.entry], 0);
      player.openNowPlaying();
    } else if (state.entry.mediaType === "video" && onPlayVideo) {
      onPlayVideo(state.entry);
    } else {
      void bridge?.openMedia(state.entry.relativePath);
    }
  };

  return (
    <section className={`home ${active ? "home--active" : ""}`} aria-label="Home">
      <div className="home-intro">
        <QMark size={56} />
        <h1>Qtmedia</h1>
        <p>Save videos and music from a link. Everything stays on this device.</p>
      </div>

      {editable ? (
        <form className="search-bar" onSubmit={submit}>
          <div className="search-mode" role="group" aria-label="What to save">
            {(["video", "music"] as const).map((item) => (
              <button key={item} type="button" className="search-mode__option" aria-label={item === "video" ? "Video mode" : "Music mode"} aria-pressed={mode === item} title={item === "video" ? "Saves the highest available resolution" : "Saves FLAC with cover art"} onClick={() => chooseMode(item)}>
                <Icon name={item} />{item === "video" ? "Video" : "Music"}
              </button>
            ))}
          </div>
          <label className="sr-only" htmlFor="media-link">Media link</label>
          <input id="media-link" value={input} onChange={(event) => setInput(event.target.value)} placeholder={mode === "video" ? "Paste a video link" : "Paste a song or music video link"} autoComplete="off" spellCheck={false} autoFocus />
          <button type="button" className="btn btn-plain" aria-label="Paste from clipboard" onClick={() => void paste()}><Icon name="clipboard" /><span aria-hidden="true">Paste</span></button>
          <button type="submit" className="kbd-button" aria-label="Find formats" disabled={!input.trim()}>↵</button>
        </form>
      ) : (
        <div className="search-bar search-bar--locked">
          <Icon name="link" className="search-bar__icon" />
          {state.status === "inspecting"
            ? <><span className="search-bar__value">Looking up link…</span><span className="spinner" aria-hidden="true" /></>
            : <><span className="token"><Icon name="check" />{state.status === "ready" ? `${state.site} link` : lastSite ? `${lastSite} link` : "Link checked"}</span><span className="grow" /></>}
          {state.status === "ready" || state.status === "completed"
            ? <button type="button" className="btn btn-icon btn-plain" aria-label="New link" disabled={state.status === "ready" && state.submitting} onClick={reset}><Icon name="close" /></button>
            : null}
        </div>
      )}
      {clipboardError ? <p className="inline-error" role="alert">{errorMessages.clipboard_unavailable}</p> : null}

      <div className={`home-result-panel ${active ? `home-result-panel--open home-result-panel--${state.status}` : ""}`} data-reveal="top-down" data-state={state.status} data-testid="home-result-panel">
        {active ? (
          <div className="panel" aria-live="polite">
            {state.status === "inspecting" ? (
              <div className="panel-search" role="status" aria-label="Inspecting link">
                <div className="panel-line"><strong>Looking up link…</strong></div>
                <progress className="meter" aria-label="Looking up link" />
                <span className="panel-note">Checking which video and audio formats are available.</span>
              </div>
            ) : null}

            {state.status === "ready" ? (
              <>
                <PanelHead title={state.title} detail={`${state.site} · ${state.durationSeconds === null ? "Duration unavailable" : formatDuration(state.durationSeconds)}`} audio={!videoFormats.length} />
                <div className="format-list" ref={listRef} onKeyDown={moveFocus} aria-label="Available formats">
                  {videoFormats.length ? <FormatGroup title="Video" note={videoFormats[0].extension.toUpperCase()} formats={videoFormats} disabled={state.submitting} onPick={(key) => void startDownload(key)} /> : null}
                  {audioFormats.length ? <FormatGroup title="Audio" formats={audioFormats} disabled={state.submitting} onPick={(key) => void startDownload(key)} /> : null}
                </div>
                <div className="panel-foot">{state.submitting ? "Starting download…" : "Click a format to download it to your Library."}</div>
              </>
            ) : null}

            {state.status === "downloading" || state.status === "cancelling" ? (
              <>
                <PanelHead title={state.title} detail={state.formatLabel} audio={state.formatLabel.startsWith("MP3")} />
                <div className="panel-progress">
                  <div className="panel-line"><strong>{progress?.label}</strong><span className="pct">{progress?.value}</span></div>
                  <progress className="meter meter--lg" value={progress?.percent ?? undefined} max="100" aria-label="Download progress" />
                  <div className="panel-line panel-line--meta">
                    <span>{state.stage !== "downloading" ? "This can take a moment for long videos" : state.totalBytes ? `${formatBytes(state.downloadedBytes)} of ${formatBytes(state.totalBytes)}` : state.downloadedBytes ? `${formatBytes(state.downloadedBytes)} received` : "Waiting for the source"}</span>
                    <button type="button" className="btn btn-default" disabled={state.status === "cancelling"} onClick={() => void cancelDownload()}>{state.status === "cancelling" ? "Cancelling…" : "Cancel"}</button>
                  </div>
                </div>
              </>
            ) : null}

            {state.status === "completed" ? (
              <div className="panel-done">
                <span className="done-check" aria-hidden="true"><Icon name="check" /></span>
                <div className="panel-done__copy"><strong>Saved to your Library</strong><span>{fileName(state.entry)} · {formatBytes(state.entry.sizeBytes)}</span></div>
                <button type="button" className="btn btn-default" onClick={onOpenFiles}>Show in Files</button>
                <button type="button" className="btn btn-accent" onClick={playSaved}><Icon name="play" />Play</button>
              </div>
            ) : null}

            {state.status === "error" ? (
              <div className="panel-error">
                <p role="alert">{state.code === "cancelled" ? "Download cancelled." : errorMessages[state.code] ?? "The request could not be completed."}</p>
                <button type="button" className="btn btn-default" onClick={reset}>Try another link</button>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </section>
  );
}

function PanelHead({ title, detail, audio }: { title: string; detail: string; audio: boolean }) {
  return (
    <div className="panel-head">
      <div className="panel-thumb" aria-hidden="true"><Icon name={audio ? "music" : "video"} /></div>
      <div className="panel-title"><h2>{title}</h2><span>{detail}</span></div>
    </div>
  );
}

function FormatGroup({ title, note, formats, disabled, onPick }: { title: string; note?: string; formats: FormatOption[]; disabled: boolean; onPick: (key: string) => void }) {
  return (
    <div role="group" aria-label={title} className="format-group">
      <div className="format-label" aria-hidden="true">{title}{note ? ` · ${note}` : ""}</div>
      {formats.map((format) => {
        const { name, detail } = describe(format);
        return (
          <button key={format.key} type="button" className="format-row" aria-label={`Download ${format.label}`} disabled={disabled} onClick={() => onPick(format.key)}>
            <b>{name}</b><span>{detail}</span><span className="format-row__go"><Icon name="download" /><span>Download</span></span>
          </button>
        );
      })}
    </div>
  );
}
