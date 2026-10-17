import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import type { DesktopBridge, LibraryEntry } from "../lib/bridge";
import { hashColor, rgb } from "../lib/coverColor";
import { formatDuration, mediaTitle } from "../lib/library";
import { useOptionalPlayer } from "../lib/player";
import { MAX_PLAYLIST_NAME, playlistStore, usePlaylistSongs, type Playlist } from "../lib/playlists";
import { useDragReorder } from "../lib/useDragReorder";
import { Artwork } from "./Artwork";
import { EmptyState } from "./FilesPage";
import { Icon } from "./Icon";

const songCount = (count: number) => `${count} ${count === 1 ? "song" : "songs"}`;

function totalLength(songs: LibraryEntry[]) {
  const seconds = songs.reduce((sum, song) => sum + (song.durationSeconds ?? 0), 0);
  if (!seconds) return null;
  const minutes = Math.round(seconds / 60);
  return minutes >= 60 ? `${Math.floor(minutes / 60)} hr ${minutes % 60} min` : `${Math.max(1, minutes)} min`;
}

/** Mosaic of the first four covers, one cover, or a tinted tile with the playlist glyph. */
export function PlaylistCover({ bridge, playlist, songs, className = "" }: { bridge: DesktopBridge; playlist: Playlist; songs: LibraryEntry[]; className?: string }) {
  const covers = songs.filter((song) => song.artworkPath).slice(0, 4);
  if (covers.length === 4) {
    return (
      <div className={`playlist-cover playlist-cover--mosaic ${className}`} aria-hidden="true">
        {covers.map((song) => <Artwork key={song.relativePath} bridge={bridge} entry={song} name={mediaTitle(song)} />)}
      </div>
    );
  }
  if (covers.length) return <div className={`playlist-cover ${className}`} aria-hidden="true"><Artwork bridge={bridge} entry={covers[0]} name={mediaTitle(covers[0])} /></div>;
  const tint = hashColor(playlist.name + playlist.id);
  return (
    <div className={`playlist-cover playlist-cover--blank ${className}`} aria-hidden="true" style={{ background: `linear-gradient(140deg, ${rgb(tint)}, ${rgb(tint, 0.35)})` }}>
      <Icon name="playlist" />
    </div>
  );
}

/** "Playlists" shelf on the Music page: a New Playlist tile, then each playlist. */
export function PlaylistShelf({ bridge, playlists, library, onOpen, onCreate }: {
  bridge: DesktopBridge;
  playlists: Playlist[];
  library: LibraryEntry[];
  onOpen: (id: string) => void;
  onCreate: () => void;
}) {
  return (
    <>
      <h2 className="section-title">Playlists</h2>
      <ul className="cover-grid playlist-grid" aria-label="Playlists">
        <li className="cover-card">
          <button type="button" className="cover playlist-new" onClick={onCreate}>
            <span className="playlist-new__icon" aria-hidden="true"><Icon name="plus" /></span>
            <span>New Playlist</span>
          </button>
        </li>
        {playlists.map((playlist) => <ShelfItem key={playlist.id} bridge={bridge} playlist={playlist} library={library} onOpen={onOpen} />)}
      </ul>
    </>
  );
}

function ShelfItem({ bridge, playlist, library, onOpen }: { bridge: DesktopBridge; playlist: Playlist; library: LibraryEntry[]; onOpen: (id: string) => void }) {
  const songs = usePlaylistSongs(playlist, library);
  return (
    <li className="cover-card">
      <button type="button" className="cover" aria-label={`Open playlist ${playlist.name}`} onClick={() => onOpen(playlist.id)}>
        <PlaylistCover bridge={bridge} playlist={playlist} songs={songs} />
      </button>
      <div className="media-meta"><strong title={playlist.name}>{playlist.name}</strong><span>{songCount(songs.length)}</span></div>
    </li>
  );
}

/** One playlist: play/shuffle, rename, add or remove songs, drag to reorder, delete. */
export function PlaylistView({ bridge, playlist, library, onBack, onAddSongs }: {
  bridge: DesktopBridge;
  playlist: Playlist;
  library: LibraryEntry[];
  onBack: () => void;
  onAddSongs: () => void;
}) {
  const songs = usePlaylistSongs(playlist, library);
  const player = useOptionalPlayer();
  const [renaming, setRenaming] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const listRef = useRef<HTMLOListElement>(null);
  const currentPath = player?.current?.relativePath;
  const length = totalLength(songs);

  const play = (index: number) => {
    if (player?.available) player.playQueue(songs, index);
    else if (songs[index]) void bridge.openMedia(songs[index].relativePath);
  };
  const shuffle = () => {
    if (!player?.available || !songs.length) return;
    if (!player.shuffle) player.toggleShuffle();
    player.playQueue(songs, Math.floor(Math.random() * songs.length));
  };
  // Rows show only songs still in the library; map back to stored positions.
  const { itemProps, listClassName } = useDragReorder({
    count: songs.length,
    list: listRef,
    onMove: (from, to) => playlistStore.moveSong(playlist.id, playlist.paths.indexOf(songs[from].relativePath), playlist.paths.indexOf(songs[to].relativePath)),
  });

  return (
    <div className="playlist-view">
      <button type="button" className="btn btn-plain playlist-back" onClick={onBack}><Icon name="back" />Music</button>
      <header className="playlist-head">
        <PlaylistCover bridge={bridge} playlist={playlist} songs={songs} className="playlist-cover--large" />
        <div className="playlist-head__copy">
          <span className="playlist-eyebrow">Playlist</span>
          {renaming
            ? <RenameField name={playlist.name} onDone={(name) => { if (name !== null) playlistStore.rename(playlist.id, name); setRenaming(false); }} />
            : <h2 title={playlist.name}>{playlist.name}</h2>}
          <p>{songCount(songs.length)}{length ? ` · ${length}` : ""}</p>
          <div className="playlist-actions">
            <button type="button" className="btn btn-accent" aria-label="Play playlist" disabled={!songs.length} onClick={() => play(0)}><Icon name="play" />Play</button>
            <button type="button" className="btn btn-default" aria-label="Shuffle playlist" disabled={!songs.length || !player?.available} onClick={shuffle}><Icon name="shuffle" />Shuffle</button>
            <button type="button" className="btn btn-default" onClick={onAddSongs}><Icon name="plus" />Add Songs</button>
            <button type="button" className="btn btn-plain btn-icon" aria-label="Rename playlist" title="Rename" onClick={() => setRenaming(true)}><Icon name="pencil" /></button>
            <button type="button" className="btn btn-plain btn-icon" aria-label="Delete playlist" title="Delete playlist" onClick={() => setConfirming(true)}><Icon name="trash" /></button>
          </div>
        </div>
      </header>

      {songs.length ? (
        <ol ref={listRef} className={`song-table playlist-songs ${listClassName}`} aria-label="Playlist songs">
          {songs.map((song, index) => {
            const title = mediaTitle(song);
            const isCurrent = currentPath === song.relativePath;
            const { className, ...drag } = itemProps(index);
            return (
              <li key={song.relativePath} className={className} {...drag}>
                <div className={`song-row song-row--playlist ${isCurrent ? "is-current" : ""}`} onDoubleClick={() => play(index)}>
                  <span className="song-n">{index + 1}</span>
                  <button type="button" className="song-title" aria-label={`Play ${title}`} aria-description="Drag, or press Alt and an arrow key, to move" onClick={() => play(index)}>{title}</button>
                  <span className="song-time">{song.durationSeconds !== null ? formatDuration(song.durationSeconds) : "–"}</span>
                  <button type="button" className="row-action" aria-label={`Remove ${title} from playlist`} title="Remove from playlist" onPointerDown={(event) => event.stopPropagation()} onClick={() => playlistStore.removeSong(playlist.id, song.relativePath)}><Icon name="close" /></button>
                </div>
              </li>
            );
          })}
        </ol>
      ) : (
        <EmptyState title="This playlist is empty." body="Add songs from your library to start listening." action={<button type="button" className="btn btn-accent" onClick={onAddSongs}><Icon name="plus" />Add Songs</button>} />
      )}

      {confirming ? (
        <ConfirmSheet
          title={`Delete “${playlist.name}”?`}
          body="The playlist will be removed. Its songs stay in your library."
          confirm="Delete Playlist"
          onCancel={() => setConfirming(false)}
          onConfirm={() => { playlistStore.remove(playlist.id); onBack(); }}
        />
      ) : null}
    </div>
  );
}

function RenameField({ name, onDone }: { name: string; onDone: (name: string | null) => void }) {
  const [value, setValue] = useState(name);
  const done = useRef(false);
  const finish = (result: string | null) => {
    if (done.current) return;
    done.current = true;
    onDone(result);
  };
  return (
    <input
      className="playlist-rename"
      aria-label="Playlist name"
      value={value}
      maxLength={MAX_PLAYLIST_NAME}
      autoFocus
      onFocus={(event) => event.currentTarget.select()}
      onChange={(event) => setValue(event.target.value)}
      onKeyDown={(event) => {
        if (event.key === "Enter") finish(value);
        if (event.key === "Escape") { event.stopPropagation(); finish(null); }
      }}
      onBlur={() => finish(value)}
    />
  );
}

function useEscape(onEscape: () => void) {
  const ref = useRef(onEscape);
  ref.current = onEscape;
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") ref.current(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}

function ConfirmSheet({ title, body, confirm, onCancel, onConfirm }: { title: string; body: string; confirm: string; onCancel: () => void; onConfirm: () => void }) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  useEffect(() => cancelRef.current?.focus(), []);
  useEscape(onCancel);
  return (
    <div className="sheet-backdrop" onClick={onCancel}>
      <div className="sheet" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" aria-describedby="confirm-body" onClick={(event) => event.stopPropagation()}>
        <span className="sheet-icon" aria-hidden="true"><Icon name="trash" /></span>
        <h2 id="confirm-title">{title}</h2>
        <p id="confirm-body">{body}</p>
        <div className="sheet-actions">
          <button ref={cancelRef} type="button" className="btn btn-default" onClick={onCancel}>Cancel</button>
          <button type="button" className="btn btn-danger" onClick={onConfirm}>{confirm}</button>
        </div>
      </div>
    </div>
  );
}

/**
 * New Playlist (name plus optional songs) or Add Songs to an existing playlist.
 * Songs already in the playlist show as added and can't be picked twice.
 */
export function PlaylistSheet({ mode, songs, playlist, preselected = [], onCancel, onDone }: {
  mode: "create" | "add";
  songs: LibraryEntry[];
  playlist?: Playlist;
  preselected?: string[];
  onCancel: () => void;
  onDone: (playlist: Playlist, added: number) => void;
}) {
  const [name, setName] = useState("");
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState<Set<string>>(() => new Set(preselected));
  const already = useMemo(() => new Set(playlist?.paths ?? []), [playlist]);
  const firstField = useRef<HTMLInputElement>(null);
  useLayoutEffect(() => firstField.current?.focus(), []);
  useEscape(onCancel);

  const shown = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    return normalized ? songs.filter((song) => mediaTitle(song).toLocaleLowerCase().includes(normalized)) : songs;
  }, [songs, query]);

  const toggle = (path: string) => setPicked((current) => {
    const next = new Set(current);
    if (next.has(path)) next.delete(path); else next.add(path);
    return next;
  });
  // Keep library order, whatever order the boxes were ticked in.
  const chosen = songs.map((song) => song.relativePath).filter((path) => picked.has(path) && !already.has(path));

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (mode === "create") {
      const created = playlistStore.create(name, chosen);
      onDone(created, chosen.length);
    } else if (playlist && chosen.length) {
      onDone(playlist, playlistStore.addSongs(playlist.id, chosen));
    }
  };

  const heading = mode === "create" ? "New Playlist" : `Add Songs to “${playlist?.name ?? ""}”`;
  return (
    <div className="sheet-backdrop" onClick={onCancel}>
      <form className="sheet sheet--wide" role="dialog" aria-modal="true" aria-labelledby="playlist-sheet-title" onClick={(event) => event.stopPropagation()} onSubmit={submit}>
        <h2 id="playlist-sheet-title">{heading}</h2>
        {mode === "create" ? (
          <label className="field sheet-field">
            <span className="sr-only">Playlist name</span>
            <Icon name="playlist" />
            <input ref={firstField} value={name} maxLength={MAX_PLAYLIST_NAME} placeholder="Untitled Playlist" onChange={(event) => setName(event.target.value)} />
          </label>
        ) : null}
        {songs.length ? (
          <>
            <div className="pick-head">
              <span>{mode === "create" ? "Add songs (optional)" : "Choose songs"}</span>
              <label className="field field--search">
                <span className="sr-only">Search songs</span>
                <Icon name="search" />
                <input ref={mode === "add" ? firstField : undefined} value={query} placeholder="Search songs" onChange={(event) => setQuery(event.target.value)} />
              </label>
            </div>
            <ul className="pick-list" aria-label="Songs to add">
              {shown.map((song) => {
                const title = mediaTitle(song);
                const inList = already.has(song.relativePath);
                return (
                  <li key={song.relativePath}>
                    <label className={`pick-row ${inList ? "is-added" : ""}`}>
                      <input type="checkbox" checked={inList || picked.has(song.relativePath)} disabled={inList} onChange={() => toggle(song.relativePath)} />
                      <span className="pick-title" title={title}>{title}</span>
                      <span className="pick-meta">{inList ? "Added" : song.durationSeconds !== null ? formatDuration(song.durationSeconds) : ""}</span>
                    </label>
                  </li>
                );
              })}
              {!shown.length ? <li className="pick-empty">No songs match.</li> : null}
            </ul>
          </>
        ) : <p>Songs you save from Home can be added here later.</p>}
        <div className="sheet-actions">
          <button type="button" className="btn btn-default" onClick={onCancel}>Cancel</button>
          <button type="submit" className="btn btn-accent" disabled={mode === "add" && !chosen.length}>
            {mode === "create" ? (chosen.length ? `Create with ${songCount(chosen.length)}` : "Create") : chosen.length ? `Add ${songCount(chosen.length)}` : "Add"}
          </button>
        </div>
      </form>
    </div>
  );
}

/** Per-song "Add to Playlist" button with a small menu of playlists. */
export function AddToPlaylist({ song, playlists, onAdded, onNew, onPlayNext, onAddToQueue }: {
  song: LibraryEntry;
  playlists: Playlist[];
  onAdded: (playlist: Playlist) => void;
  onNew: (path: string) => void;
  /** With these, the button opens a song menu: queue actions, then playlists. */
  onPlayNext?: (song: LibraryEntry) => void;
  onAddToQueue?: (song: LibraryEntry) => void;
}) {
  const queueActions = Boolean(onPlayNext || onAddToQueue);
  const [anchor, setAnchor] = useState<DOMRect | null>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const title = mediaTitle(song);
  const close = () => {
    setAnchor(null);
    buttonRef.current?.focus();
  };

  useEffect(() => {
    if (!anchor) return;
    menuRef.current?.querySelector<HTMLElement>("[role=menuitem]:not([aria-disabled=true])")?.focus();
    const onPointer = (event: PointerEvent) => {
      if (!menuRef.current?.contains(event.target as Node) && !buttonRef.current?.contains(event.target as Node)) setAnchor(null);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.stopPropagation(); close(); }
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        const items = [...(menuRef.current?.querySelectorAll<HTMLElement>("[role=menuitem]:not([aria-disabled=true])") ?? [])];
        const at = items.indexOf(document.activeElement as HTMLElement);
        items[(at + (event.key === "ArrowDown" ? 1 : items.length - 1)) % items.length]?.focus();
      }
    };
    const onScroll = () => setAnchor(null);
    window.addEventListener("pointerdown", onPointer, true);
    window.addEventListener("keydown", onKey, true);
    window.addEventListener("resize", onScroll);
    document.addEventListener("scroll", onScroll, true);
    return () => {
      window.removeEventListener("pointerdown", onPointer, true);
      window.removeEventListener("keydown", onKey, true);
      window.removeEventListener("resize", onScroll);
      document.removeEventListener("scroll", onScroll, true);
    };
  }, [anchor]);

  // Opens below the button, or above it near the bottom of the window.
  const style: React.CSSProperties | undefined = anchor ? {
    right: Math.max(8, window.innerWidth - anchor.right),
    ...(anchor.bottom + 260 > window.innerHeight ? { bottom: window.innerHeight - anchor.top + 4 } : { top: anchor.bottom + 4 }),
  } : undefined;

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        className={`row-action ${anchor ? "is-open" : ""}`}
        aria-label={queueActions ? `More options for ${title}` : `Add ${title} to a playlist`}
        title={queueActions ? "More" : "Add to Playlist"}
        aria-haspopup="menu"
        aria-expanded={Boolean(anchor)}
        onClick={(event) => setAnchor(anchor ? null : event.currentTarget.getBoundingClientRect())}
      >
        <Icon name={queueActions ? "more" : "addToPlaylist"} />
      </button>
      {anchor ? createPortal(
        <div ref={menuRef} className="menu" role="menu" aria-label={queueActions ? `Options for ${title}` : "Add to Playlist"} style={style}>
          {onPlayNext ? (
            <button type="button" role="menuitem" className="menu-item" onClick={() => { close(); onPlayNext(song); }}>
              <Icon name="next" /><span>Play Next</span>
            </button>
          ) : null}
          {onAddToQueue ? (
            <button type="button" role="menuitem" className="menu-item" onClick={() => { close(); onAddToQueue(song); }}>
              <Icon name="queue" /><span>Add to Queue</span>
            </button>
          ) : null}
          {queueActions ? <span className="menu-sep" role="separator" /> : null}
          <span className="menu-label">Add to Playlist</span>
          {playlists.map((playlist) => {
            const added = playlist.paths.includes(song.relativePath);
            return (
              <button
                key={playlist.id}
                type="button"
                role="menuitem"
                className="menu-item"
                aria-disabled={added || undefined}
                onClick={() => {
                  if (added) return;
                  playlistStore.addSongs(playlist.id, [song.relativePath]);
                  onAdded(playlist);
                  close();
                }}
              >
                <span>{playlist.name}</span>
                {added ? <Icon name="check" /> : null}
              </button>
            );
          })}
          {playlists.length ? <span className="menu-sep" role="separator" /> : null}
          <button type="button" role="menuitem" className="menu-item" onClick={() => { setAnchor(null); onNew(song.relativePath); }}>
            <Icon name="plus" /><span>New Playlist…</span>
          </button>
        </div>,
        // Portalled so the menu sits above the player bar and is never clipped by the page.
        document.body,
      ) : null}
    </>
  );
}
