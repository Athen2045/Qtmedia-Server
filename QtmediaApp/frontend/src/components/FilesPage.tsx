import { useEffect, useMemo, useState } from "react";

import type { DesktopBridge, LibraryEntry, MediaKind } from "../lib/bridge";
import { Icon } from "./Icon";

type Filter = "all" | MediaKind;
type Sort = "recent" | "name" | "size";

function displayName(entry: LibraryEntry) {
  return entry.relativePath.split("/").at(-1) ?? entry.relativePath;
}

function formatBytes(bytes: number) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDuration(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
}

function formatModified(epochSeconds: number) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(epochSeconds * 1000));
}

function Artwork({ bridge, entry, name }: { bridge: DesktopBridge; entry: LibraryEntry; name: string }) {
  const [source, setSource] = useState<string | null>(null);
  useEffect(() => {
    let mounted = true;
    if (entry.artworkPath) {
      void bridge.readArtwork(entry.artworkPath).then((value) => {
        if (mounted) setSource(value);
      }).catch(() => undefined);
    }
    return () => { mounted = false; };
  }, [bridge, entry.artworkPath]);
  if (source) return <img className="file-artwork" src={source} alt={`Artwork for ${name}`} />;
  return <div className={`file-type ${entry.mediaType}`}>{entry.mediaType === "audio" ? "A" : "V"}</div>;
}

export function FilesPage({ bridge, refreshToken = 0, onGoHome }: { bridge: DesktopBridge; refreshToken?: number; onGoHome?: () => void }) {
  const [entries, setEntries] = useState<LibraryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<Filter>("all");
  const [sort, setSort] = useState<Sort>("recent");
  const [query, setQuery] = useState("");
  const [loadError, setLoadError] = useState(false);
  const [retryToken, setRetryToken] = useState(0);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    setLoadError(false);
    void bridge.listLibrary().then((items) => {
      if (mounted) {
        setEntries(items);
        setLoading(false);
      }
    }).catch(() => {
      if (mounted) {
        setLoadError(true);
        setLoading(false);
      }
    });
    return () => { mounted = false; };
  }, [bridge, refreshToken, retryToken]);

  const visible = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    const filtered = entries.filter((entry) => {
      const matchesType = filter === "all" || entry.mediaType === filter;
      const matchesQuery = !normalized || displayName(entry).toLocaleLowerCase().includes(normalized);
      return matchesType && matchesQuery;
    });
    return [...filtered].sort((left, right) => {
      if (sort === "name") return displayName(left).localeCompare(displayName(right));
      if (sort === "size") return right.sizeBytes - left.sizeBytes;
      return right.modifiedAt - left.modifiedAt;
    });
  }, [entries, filter, query, sort]);

  return (
    <section className="files-page page-panel" aria-labelledby="files-title">
      <header className="page-header">
        <div><p className="eyebrow">Local media</p><h1 id="files-title">Your library</h1></div>
        <button type="button" className="secondary-button" onClick={() => void bridge.openLibrary()}>Open library folder</button>
      </header>
      <div className="library-toolbar">
        <div className="segmented" aria-label="Media type filter">
          {(["all", "audio", "video"] as const).map((item) => <button key={item} type="button" className={filter === item ? "selected" : ""} onClick={() => setFilter(item)}>{item[0].toUpperCase() + item.slice(1)}</button>)}
        </div>
        <label className="library-search"><span className="sr-only">Search downloaded files</span><Icon name="search" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search files" /></label>
        <label><span className="sr-only">Sort library</span><select value={sort} onChange={(event) => setSort(event.target.value as Sort)}><option value="recent">Recent</option><option value="name">Name</option><option value="size">Size</option></select></label>
      </div>
      {loading ? <div className="library-skeleton" aria-label="Loading library"><span /><span /><span /></div> : null}
      {!loading && loadError ? <div className="library-empty"><h2>Library unavailable.</h2><p>Qtmedia could not read the selected download location.</p><button type="button" className="secondary-button" onClick={() => setRetryToken((value) => value + 1)}>Retry</button></div> : null}
      {!loading && !loadError && entries.length === 0 ? <div className="library-empty" role="status"><h2>No downloads found</h2><p>No audio or video files were detected in your current download location.</p><p>Paste a media link on Home to download your first file, or check your download location in Settings.</p>{onGoHome ? <button type="button" className="primary-button" onClick={onGoHome}>Go to Home</button> : null}</div> : null}
      {!loading && !loadError && entries.length > 0 && visible.length === 0 ? <div className="library-empty"><h2>No files match.</h2><p>Try another search or show all media types.</p><button type="button" className="secondary-button" onClick={() => { setQuery(""); setFilter("all"); }}>Clear filters</button></div> : null}
      {visible.length ? <div className="library-table"><div className="library-table__header" aria-hidden="true"><span>Name</span><span>Format</span><span>Size</span><span>Added</span><span /></div><ul className="library-list">{visible.map((entry) => {
        const name = displayName(entry);
        return <li key={entry.relativePath}><Artwork bridge={bridge} entry={entry} name={name} /><div className="file-copy"><strong>{name}</strong><span>{entry.mediaType === "audio" ? "Audio" : "Video"}{entry.durationSeconds !== null ? ` · ${formatDuration(entry.durationSeconds)}` : ""}</span></div><span className="file-format">{entry.extension.toUpperCase()}</span><span className="file-size">{formatBytes(entry.sizeBytes)}</span><span className="file-date">{formatModified(entry.modifiedAt)}</span><button type="button" className="secondary-button" aria-label={`Open ${name}`} onClick={() => void bridge.openMedia(entry.relativePath)}>Open</button></li>;
      })}</ul></div> : null}
    </section>
  );
}
