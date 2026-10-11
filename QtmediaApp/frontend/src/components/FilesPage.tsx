import { useEffect, useMemo, useRef, useState } from "react";

import type { DesktopBridge, LibraryEntry, MediaKind } from "../lib/bridge";
import { fileName, formatBytes, formatDuration, useLibrary } from "../lib/library";
import { useOptionalPlayer } from "../lib/player";
import { Artwork } from "./Artwork";
import { Icon } from "./Icon";
import { Toolbar } from "./Shell";

type Filter = "all" | MediaKind;
type SortKey = "name" | "kind" | "size" | "added";

function formatAdded(epochSeconds: number, now = new Date()) {
  const date = new Date(epochSeconds * 1000);
  if (date.toDateString() === now.toDateString()) {
    return `Today, ${new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(date)}`;
  }
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(date);
}

function kindLabel(entry: LibraryEntry) {
  const kind = entry.mediaType === "audio" ? "Music" : "Video";
  return entry.durationSeconds !== null ? `${kind} · ${formatDuration(entry.durationSeconds)}` : kind;
}

function plural(count: number, noun: string) {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

export function FilesPage({ bridge, refreshToken = 0, onGoHome, onShowDownload, onPlayVideo }: { bridge: DesktopBridge; refreshToken?: number; onGoHome?: () => void; onShowDownload?: () => void; onPlayVideo?: (entry: LibraryEntry) => void }) {
  const { entries, loading, failed, retry } = useLibrary(bridge, refreshToken);
  const player = useOptionalPlayer();
  const [filter, setFilter] = useState<Filter>("all");
  const [sort, setSort] = useState<{ key: SortKey; descending: boolean }>({ key: "added", descending: true });
  const [query, setQuery] = useState("");
  const [selection, setSelection] = useState<Set<string>>(() => new Set());
  const anchorRef = useRef<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [location, setLocation] = useState<string | null>(null);
  const canDelete = typeof bridge.deleteMedia === "function";
  const [importing, setImporting] = useState(false);

  const importFiles = async () => {
    if (!bridge.importMedia || importing) return;
    setImporting(true);
    setNotice(null);
    try {
      const report = await bridge.importMedia();
      if (report) {
        const parts = [
          report.imported.length ? `Imported ${plural(report.imported.length, "file")}.` : "Nothing was imported.",
          report.skipped ? `${plural(report.skipped, "file")} skipped (not MP3, FLAC, MP4, M4V, MOV, MKV, WebM or AVI, or couldn't be copied).` : "",
        ];
        setNotice(parts.filter(Boolean).join(" "));
        retry();
      }
    } catch {
      setNotice("Those files couldn’t be imported.");
    } finally {
      setImporting(false);
    }
  };

  useEffect(() => {
    let mounted = true;
    void Promise.resolve(bridge.getDownloadLocation()).then((value) => { if (mounted && value) setLocation(value.path); }).catch(() => undefined);
    return () => { mounted = false; };
  }, [bridge, refreshToken]);

  const visible = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    const filtered = entries.filter((entry) => (filter === "all" || entry.mediaType === filter)
      && (!normalized || fileName(entry).toLocaleLowerCase().includes(normalized)));
    const compare: Record<SortKey, (left: LibraryEntry, right: LibraryEntry) => number> = {
      name: (left, right) => fileName(left).localeCompare(fileName(right)),
      kind: (left, right) => left.mediaType.localeCompare(right.mediaType) || fileName(left).localeCompare(fileName(right)),
      size: (left, right) => left.sizeBytes - right.sizeBytes,
      added: (left, right) => left.modifiedAt - right.modifiedAt,
    };
    const sorted = [...filtered].sort(compare[sort.key]);
    return sort.descending ? sorted.reverse() : sorted;
  }, [entries, filter, query, sort]);

  // Actions apply only to selected items the user can currently see.
  const selectedVisible = useMemo(() => visible.filter((entry) => selection.has(entry.relativePath)), [visible, selection]);
  const allSelected = visible.length > 0 && selectedVisible.length === visible.length;
  const someSelected = selectedVisible.length > 0 && !allSelected;
  const selectedBytes = selectedVisible.reduce((sum, entry) => sum + entry.sizeBytes, 0);
  const totalBytes = entries.reduce((sum, entry) => sum + entry.sizeBytes, 0);

  const headerBox = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (headerBox.current) headerBox.current.indeterminate = someSelected;
  }, [someSelected]);

  const sortBy = (key: SortKey) => setSort((current) => current.key === key
    ? { key, descending: !current.descending }
    : { key, descending: key === "size" || key === "added" });

  const selectAll = () => setSelection(new Set(visible.map((entry) => entry.relativePath)));
  const clearSelection = () => { setSelection(new Set()); anchorRef.current = null; };
  const toggle = (path: string) => {
    setSelection((current) => {
      const next = new Set(current);
      if (next.has(path)) next.delete(path); else next.add(path);
      return next;
    });
    anchorRef.current = path;
  };

  /** Finder-style: click selects one, Ctrl/Cmd toggles, Shift extends a range. */
  const clickRow = (event: React.MouseEvent, entry: LibraryEntry) => {
    const path = entry.relativePath;
    if (event.shiftKey && anchorRef.current) {
      const paths = visible.map((item) => item.relativePath);
      const [from, to] = [paths.indexOf(anchorRef.current), paths.indexOf(path)].sort((a, b) => a - b);
      if (from >= 0) {
        setSelection(new Set(paths.slice(from, to + 1)));
        return;
      }
    }
    if (event.ctrlKey || event.metaKey) {
      toggle(path);
      return;
    }
    setSelection(new Set([path]));
    anchorRef.current = path;
  };

  const open = (entry: LibraryEntry) => {
    if (entry.mediaType === "audio" && player?.available) {
      const audio = visible.filter((item) => item.mediaType === "audio");
      player.playQueue(audio, audio.indexOf(entry));
    } else if (entry.mediaType === "video" && onPlayVideo) {
      onPlayVideo(entry);
    } else {
      void bridge.openMedia(entry.relativePath);
    }
  };

  const requestDelete = () => {
    if (canDelete && selectedVisible.length && !deleting) {
      setNotice(null);
      setConfirming(true);
    }
  };

  const confirmDelete = async () => {
    const targets = selectedVisible.map((entry) => entry.relativePath);
    setConfirming(false);
    setDeleting(true);
    try {
      const report = await bridge.deleteMedia!(targets);
      const removed = new Set(report.removed);
      // Don't keep playing a file that is no longer in the library.
      if (player?.current && removed.has(player.current.relativePath)) player.stop();
      setSelection((current) => new Set([...current].filter((path) => !removed.has(path))));
      if (report.failed) setNotice(`${plural(report.failed, "item")} couldn’t be moved to the Recycle Bin.`);
      retry();
    } catch (caught) {
      const code = typeof caught === "object" && caught !== null && "code" in caught ? String((caught as { code: unknown }).code) : "";
      setNotice(code === "storage_busy"
        ? "The library is changing location. Try again in a moment."
        : "Those files couldn’t be moved to the Recycle Bin.");
    } finally {
      setDeleting(false);
    }
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    const target = event.target as HTMLElement;
    if (target.tagName === "INPUT" && (target as HTMLInputElement).type !== "checkbox") return;
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "a") {
      event.preventDefault();
      selectAll();
    } else if (event.key === "Delete" || ((event.metaKey || event.ctrlKey) && event.key === "Backspace")) {
      event.preventDefault();
      requestDelete();
    } else if (event.key === "Escape" && selection.size) {
      clearSelection();
    }
  };

  const column = (key: SortKey, label: string) => (
    <button type="button" className={`th-sort ${sort.key === key ? "is-sorted" : ""}`} aria-label={`Sort by ${label}`} aria-pressed={sort.key === key} onClick={() => sortBy(key)}>
      {label}{sort.key === key ? <Icon name="chevron" className={sort.descending ? "" : "flip"} /> : null}
    </button>
  );

  return (
    <section className="page files-page" aria-labelledby="files-title" onKeyDown={onKeyDown}>
      <Toolbar title="Files" onShowDownload={onShowDownload}>
        {selectedVisible.length ? (
          <div className="selection-tools" role="group" aria-label="Selection">
            <span className="toolbar-count">{selectedVisible.length} selected</span>
            <button type="button" className="btn btn-plain" onClick={clearSelection}>Deselect</button>
            {canDelete ? <button type="button" className="btn btn-danger" disabled={deleting} onClick={requestDelete}><Icon name="trash" />{deleting ? "Deleting…" : "Delete"}</button> : null}
          </div>
        ) : (
          <>
            <div className="segmented" role="group" aria-label="Media type filter">
              {([["all", "All"], ["video", "Video"], ["audio", "Music"]] as const).map(([value, label]) => (
                <button key={value} type="button" aria-pressed={filter === value} className={filter === value ? "on" : ""} onClick={() => setFilter(value)}>{label}</button>
              ))}
            </div>
            <label className="field field--search"><span className="sr-only">Search downloaded files</span><Icon name="search" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search" /></label>
            {bridge.importMedia ? <button type="button" className="btn btn-default" disabled={importing} onClick={() => void importFiles()}><Icon name="plus" />{importing ? "Importing…" : "Import"}</button> : null}
            <button type="button" className="btn btn-default" onClick={() => void bridge.openLibrary()}><Icon name="open" />Open Folder</button>
          </>
        )}
      </Toolbar>
      <span id="files-title" className="sr-only">Files</span>
      {notice ? <p className="files-notice" role="alert">{notice}<button type="button" className="btn btn-icon btn-plain" aria-label="Dismiss" onClick={() => setNotice(null)}><Icon name="close" /></button></p> : null}

      <div className="page-body page-body--flush">
        {loading && entries.length === 0 ? <div className="list-skeleton" aria-label="Loading library"><span /><span /><span /></div> : null}
        {!loading && failed ? <EmptyState title="Library unavailable." body="Qtmedia could not read the selected download location." action={<button type="button" className="btn btn-default" onClick={retry}>Retry</button>} /> : null}
        {!loading && !failed && entries.length === 0 ? <EmptyState role="status" title="No downloads found" body="Paste a link on Home to save your first video or song." action={onGoHome ? <button type="button" className="btn btn-accent" onClick={onGoHome}>Go to Home</button> : null} /> : null}
        {!loading && !failed && entries.length > 0 && visible.length === 0 ? <EmptyState title="No files match." body="Try another search or show all kinds." action={<button type="button" className="btn btn-default" onClick={() => { setQuery(""); setFilter("all"); }}>Clear filters</button>} /> : null}

        {!failed && visible.length ? (
          <div className={`file-table ${selection.size ? "has-selection" : ""}`}>
            <div className="file-row file-row--head">
              <label className="file-check">
                <input ref={headerBox} type="checkbox" aria-label="Select all" checked={allSelected} onChange={() => (allSelected ? clearSelection() : selectAll())} />
              </label>
              {column("name", "Name")}{column("kind", "Kind")}{column("size", "Size")}{column("added", "Date Added")}<span />
            </div>
            <ul className="file-list" aria-multiselectable="true" role="listbox" aria-label="Library files">
              {visible.map((entry) => {
                const name = fileName(entry);
                const isSelected = selection.has(entry.relativePath);
                return (
                  <li
                    key={entry.relativePath}
                    role="option"
                    className={`file-row ${isSelected ? "is-selected" : ""}`}
                    aria-selected={isSelected}
                    onClick={(event) => clickRow(event, entry)}
                    onDoubleClick={() => open(entry)}
                  >
                    <label className="file-check" onClick={(event) => event.stopPropagation()}>
                      <input type="checkbox" aria-label={`Select ${name}`} checked={isSelected} onChange={() => toggle(entry.relativePath)} />
                    </label>
                    <span className="file-name"><Artwork bridge={bridge} entry={entry} name={name} className="file-art" /><span>{name}</span></span>
                    <span className="file-dim">{kindLabel(entry)}</span>
                    <span className="file-dim file-num">{formatBytes(entry.sizeBytes)}</span>
                    <span className="file-dim">{formatAdded(entry.modifiedAt)}</span>
                    <span className="file-action">
                      {entry.mediaType === "audio" && player?.available ? <button type="button" className="btn btn-icon btn-plain" aria-label={`Play ${name}`} onClick={(event) => { event.stopPropagation(); open(entry); }}><Icon name="play" /></button> : null}
                      <button type="button" className="btn btn-icon btn-plain" aria-label={`Open ${name}`} onClick={(event) => { event.stopPropagation(); void bridge.openMedia(entry.relativePath); }}><Icon name="open" /></button>
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        ) : null}
      </div>
      <footer className="status-bar">
        <span>{selectedVisible.length ? `${selectedVisible.length} of ${plural(visible.length, "item")} selected · ${formatBytes(selectedBytes)}` : `${plural(entries.length, "item")} · ${formatBytes(totalBytes)}`}</span>
        {location ? <span className="status-bar__path" title={location}>Library · {location}</span> : null}
      </footer>

      {confirming ? (
        <ConfirmDelete
          count={selectedVisible.length}
          name={selectedVisible.length === 1 ? fileName(selectedVisible[0]) : null}
          bytes={selectedBytes}
          onCancel={() => setConfirming(false)}
          onConfirm={() => void confirmDelete()}
        />
      ) : null}
    </section>
  );
}

/** Mac-style sheet confirming a destructive action; Cancel has focus by default. */
function ConfirmDelete({ count, name, bytes, onCancel, onConfirm }: { count: number; name: string | null; bytes: number; onCancel: () => void; onConfirm: () => void }) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    cancelRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);
  const title = name ? `Move “${name}” to the Recycle Bin?` : `Move ${count} items to the Recycle Bin?`;
  return (
    <div className="sheet-backdrop" onClick={onCancel}>
      <div className="sheet" role="alertdialog" aria-modal="true" aria-labelledby="delete-title" aria-describedby="delete-body" onClick={(event) => event.stopPropagation()} onKeyDown={(event) => event.stopPropagation()}>
        <span className="sheet-icon" aria-hidden="true"><Icon name="trash" /></span>
        <h2 id="delete-title">{title}</h2>
        <p id="delete-body">{formatBytes(bytes)} will be removed from your library. You can restore {count === 1 ? "it" : "them"} from the Recycle Bin.</p>
        <div className="sheet-actions">
          <button ref={cancelRef} type="button" className="btn btn-default" onClick={onCancel}>Cancel</button>
          <button type="button" className="btn btn-danger" onClick={onConfirm}>Move to Recycle Bin</button>
        </div>
      </div>
    </div>
  );
}

export function EmptyState({ title, body, action, role }: { title: string; body: string; action?: React.ReactNode; role?: "status" }) {
  return <div className="empty-state" role={role}><h2>{title}</h2><p>{body}</p>{action}</div>;
}
