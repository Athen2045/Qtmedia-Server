import { useState } from "react";

import { useDesktopSession } from "../lib/DesktopSession";
import type { FormatOption } from "../lib/bridge";
import { Icon } from "./Icon";

const errorMessages: Record<string, string> = {
  invalid_url: "Enter a valid direct media link.",
  unsupported_source: "This source is not supported by the approved adapters.",
  no_formats: "No compatible audio or video format was found.",
  format_unavailable: "That format is no longer available. Inspect the link again.",
  download_failed: "The download could not be completed.",
  sidecar_unavailable: "The local media engine is unavailable.",
  provider_unavailable: "The source could not be reached right now.",
  clipboard_unavailable: "Qtmedia could not read the clipboard.",
};

function formatDuration(seconds: number | null) {
  if (seconds === null) return "Duration unavailable";
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(seconds % 60).padStart(2, "0")}`;
}

export function HomePage({ onOpenFiles }: { onOpenFiles: () => void }) {
  const [input, setInput] = useState("");
  const [clipboardError, setClipboardError] = useState(false);
  const { state, inspect, selectFormat, startDownload, cancelDownload, reset } = useDesktopSession();
  const active = state.status !== "empty";

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const value = input.trim();
    await inspect(value);
    if (value) setInput("");
  };

  const paste = async () => {
    setClipboardError(false);
    try {
      setInput(await navigator.clipboard.readText());
    } catch {
      setClipboardError(true);
    }
  };

  const selectedFormat = state.status === "ready"
    ? state.formats.find((format) => format.key === state.selected)
    : undefined;
  const videoFormats = state.status === "ready" ? state.formats.filter((format) => format.kind === "video") : [];
  const audioFormats = state.status === "ready" ? state.formats.filter((format) => format.kind === "audio") : [];

  return (
    <section className={`home-page ${active ? "home-page--active" : ""}`} aria-label="Home">
      <div className="home-content">
        <header className="home-brand">
          <h1 className="brand-mark">QT MEDIA</h1>
          <p className="brand-kicker">Save media. Keep it yours.</p>
          <p className="brand-subtitle">Paste a supported link to choose a format.</p>
        </header>
        <form className="link-form" onSubmit={submit}>
          <label className="sr-only" htmlFor="media-link">Media link</label>
          <input id="media-link" value={input} onChange={(event) => setInput(event.target.value)} placeholder="Paste a video or audio link" disabled={state.status === "inspecting" || state.status === "downloading" || state.status === "cancelling"} autoComplete="off" spellCheck={false} />
          <button type="button" className="paste-button" aria-label="Paste from clipboard" onClick={() => void paste()}><Icon name="clipboard" /></button>
          <button type="submit" className="inspect-button" disabled={state.status === "inspecting" || state.status === "downloading" || state.status === "cancelling"}><Icon name="search" /><span>{state.status === "inspecting" ? "Inspecting…" : "Find formats"}</span></button>
        </form>
        <div className="home-meta"><span>Supported sources are checked locally</span><span>Enter ↵</span></div>
        <p className="privacy-note">Processed locally. Download only media you have permission to access.</p>
        {clipboardError ? <p className="inline-error home-clipboard-error" role="alert">{errorMessages.clipboard_unavailable}</p> : null}

        <div className={`home-result-panel ${active ? `home-result-panel--open home-result-panel--${state.status}` : ""}`} data-reveal="top-down" data-state={state.status} data-testid="home-result-panel">
          <div className="home-result-panel__inner" aria-live="polite">
            {state.status === "inspecting" ? <div className="inspection-skeleton" role="status" aria-label="Inspecting link"><span /><span /><span /></div> : null}
            {state.status === "ready" ? (
              <article className="inspection-card">
                <div className="inspection-summary">
                  <div className="inspection-preview"><Icon name="video" /></div>
                  <div className="inspection-copy"><p className="eyebrow">Link inspected</p><h2>{state.title}</h2><p>{state.site} · {formatDuration(state.durationSeconds)}</p></div>
                  <button type="button" className="text-button new-link-button" disabled={state.submitting} onClick={reset}>New link</button>
                </div>
                <div className="format-actions" aria-label="Available formats">
                  {videoFormats.length > 0 ? <FormatGroup title="Video" formats={videoFormats} selected={state.selected} onSelect={selectFormat} /> : null}
                  {audioFormats.length > 0 ? <FormatGroup title="Audio" formats={audioFormats} selected={state.selected} onSelect={selectFormat} /> : null}
                  <div className="format-footer"><span>Only available formats are shown.</span><button type="button" className="primary-button" onClick={() => void startDownload()} disabled={!selectedFormat || state.submitting}>{state.submitting ? "Starting…" : `Download ${selectedFormat?.label ?? "Media"}`}</button></div>
                </div>
              </article>
            ) : null}
            {state.status === "downloading" || state.status === "cancelling" ? (
              <article className="progress-card"><div><p className="eyebrow">{state.status === "cancelling" ? "Cancelling" : "Downloading"}</p><h2>{state.title}</h2><span>{state.formatLabel} · {state.percent === null ? "Preparing media" : `${Math.round(state.percent)}%`}</span></div><button type="button" className="secondary-button" disabled={state.status === "cancelling"} onClick={() => void cancelDownload()}>{state.status === "cancelling" ? "Cancelling…" : "Cancel"}</button><progress value={state.percent ?? undefined} max="100" aria-label="Download progress" /></article>
            ) : null}
            {state.status === "completed" ? <article className="completion-card"><div><p className="eyebrow">Saved locally</p><h2>{state.entry.relativePath.split("/").at(-1)}</h2></div><div className="completion-actions"><button className="secondary-button" type="button" onClick={reset}>New link</button><button className="primary-button" type="button" onClick={onOpenFiles}>Open Files</button></div></article> : null}
            {state.status === "error" ? <div className="home-error"><p className="inline-error" role="alert">{state.code === "cancelled" ? "Download cancelled." : errorMessages[state.code] ?? "The request could not be completed."}</p><button type="button" className="secondary-button" onClick={reset}>Try another link</button></div> : null}
          </div>
        </div>
      </div>
    </section>
  );
}

function FormatGroup({ title, formats, selected, onSelect }: { title: string; formats: FormatOption[]; selected: string; onSelect: (key: string) => void }) {
  return <fieldset className="format-section"><legend>{title}</legend><div className="format-list">{formats.map((format) => <label key={format.key} className={`format-option ${selected === format.key ? "selected" : ""}`}><input type="radio" name="media-format" value={format.key} checked={selected === format.key} onChange={() => onSelect(format.key)} /><span className="format-radio" aria-hidden="true" /><strong>{format.height ? `${format.height}p` : format.kind === "audio" ? "MP3" : "Video"}</strong><span>{format.kind === "audio" ? `${format.bitrateKbps ?? 192} kbps` : format.extension.toUpperCase()}</span></label>)}</div></fieldset>;
}
