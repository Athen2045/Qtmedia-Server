import { useEffect, useMemo, useState } from "react";

import type { DesktopBridge, LibraryEntry, MediaKind } from "../lib/bridge";
import { formatAdded, formatBytes, formatDuration, mediaTitle, useLibrary } from "../lib/library";
import { useOptionalPlayer } from "../lib/player";
import { usePlaylists, type Playlist } from "../lib/playlists";
import { Artwork } from "./Artwork";
import { EmptyState } from "./FilesPage";
import { Icon } from "./Icon";
import { AddToPlaylist, PlaylistSheet, PlaylistShelf, PlaylistView } from "./Playlists";
import { Toolbar } from "./Shell";

type Sort = "recent" | "name";

function useMediaList(bridge: DesktopBridge, kind: MediaKind, refreshToken: number, sort: Sort, query = "") {
  const library = useLibrary(bridge, refreshToken);
  const all = useMemo(() => library.entries
    .filter((entry) => entry.mediaType === kind)
    .sort((left, right) => sort === "name" ? mediaTitle(left).localeCompare(mediaTitle(right)) : right.modifiedAt - left.modifiedAt), [library.entries, kind, sort]);
  const items = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    return normalized ? all.filter((entry) => mediaTitle(entry).toLocaleLowerCase().includes(normalized)) : all;
  }, [all, query]);
  return { ...library, all, items };
}

function SortMenu({ value, onChange, label }: { value: Sort; onChange: (value: Sort) => void; label: string }) {
  return (
    <label className="sort-menu">
      <span className="sr-only">{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value as Sort)}>
        <option value="recent">Date Added</option>
        <option value="name">Name</option>
      </select>
      <Icon name="chevron" />
    </label>
  );
}

function ListStates({ loading, failed, retry, empty, kind, onGoHome }: { loading: boolean; failed: boolean; retry: () => void; empty: boolean; kind: MediaKind; onGoHome?: () => void }) {
  if (loading && empty) return <div className={`grid-skeleton grid-skeleton--${kind}`} aria-label={`Loading ${kind === "audio" ? "music" : "videos"}`}><span /><span /><span /><span /></div>;
  if (failed) return <EmptyState title="Library unavailable." body="Qtmedia could not read the selected download location." action={<button type="button" className="btn btn-default" onClick={retry}>Retry</button>} />;
  if (empty) {
    return <EmptyState
      role="status"
      title={kind === "video" ? "No videos yet" : "No music yet"}
      body={kind === "video" ? "Videos you save from Home will appear here." : "Choose MP3 when you save from Home and your songs will collect here."}
      action={onGoHome ? <button type="button" className="btn btn-accent" onClick={onGoHome}>Go to Home</button> : null}
    />;
  }
  return null;
}

export function VideoPage({ bridge, refreshToken = 0, onGoHome, onShowDownload, onPlayVideo }: { bridge: DesktopBridge; refreshToken?: number; onGoHome?: () => void; onShowDownload?: () => void; onPlayVideo?: (entry: LibraryEntry) => void }) {
  const [sort, setSort] = useState<Sort>("recent");
  const { items, loading, failed, retry } = useMediaList(bridge, "video", refreshToken, sort);
  return (
    <section className="page media-page" aria-labelledby="video-title">
      <Toolbar title="Video" badge={onPlayVideo ? undefined : "Player coming soon"} onShowDownload={onShowDownload}>
        {!loading && !failed && items.length ? <span className="toolbar-count">{items.length} {items.length === 1 ? "video" : "videos"}</span> : null}
        <SortMenu value={sort} onChange={setSort} label="Sort video" />
      </Toolbar>
      <span id="video-title" className="sr-only">Video</span>
      <div className="page-body">
        <ListStates loading={loading} failed={failed} retry={retry} empty={items.length === 0} kind="video" onGoHome={onGoHome} />
        {!failed && items.length ? (
          <ul className="video-grid">
            {items.map((entry) => {
              const title = mediaTitle(entry);
              return (
                <li key={entry.relativePath} className="video-card">
                  <button type="button" className="video-thumb" aria-label={`Play ${title}`} onClick={() => (onPlayVideo ? onPlayVideo(entry) : void bridge.openMedia(entry.relativePath))}>
                    <Artwork bridge={bridge} entry={entry} name={title} className="video-art" />
                    {entry.durationSeconds !== null ? <span className="video-duration">{formatDuration(entry.durationSeconds)}</span> : null}
                    <span className="play-overlay" aria-hidden="true"><span className="play-disc"><Icon name="play" /></span></span>
                  </button>
                  <div className="media-meta"><strong title={title}>{title}</strong><span>{formatAdded(entry.modifiedAt)} · {formatBytes(entry.sizeBytes)}</span></div>
                </li>
              );
            })}
          </ul>
        ) : null}
      </div>
    </section>
  );
}

function LevelBars() {
  return <span className="level-bars" aria-hidden="true"><i /><i /><i /></span>;
}

export function MusicPage({ bridge, refreshToken = 0, onGoHome, onShowDownload }: { bridge: DesktopBridge; refreshToken?: number; onGoHome?: () => void; onShowDownload?: () => void }) {
  const [query, setQuery] = useState("");
  const { all, items, loading, failed, retry } = useMediaList(bridge, "audio", refreshToken, "recent", query);
  const player = useOptionalPlayer();
  const playlists = usePlaylists();
  const [openId, setOpenId] = useState<string | null>(null);
  const [sheet, setSheet] = useState<{ mode: "create"; preselected: string[] } | { mode: "add"; playlist: Playlist } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const openPlaylist = playlists.find((playlist) => playlist.id === openId);
  const recent = items.slice(0, 6);
  const currentPath = player?.current?.relativePath;

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 2400);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const play = (entry: LibraryEntry) => {
    if (player?.available) player.playQueue(items, items.indexOf(entry));
    else void bridge.openMedia(entry.relativePath);
  };

  return (
    <section className="page media-page music-page" aria-labelledby="music-title">
      <Toolbar title="Music" onShowDownload={onShowDownload}>
        {!openPlaylist && !loading && !failed && items.length ? <span className="toolbar-count">{items.length} {items.length === 1 ? "song" : "songs"}</span> : null}
        {!failed && all.length ? <button type="button" className="btn btn-default" onClick={() => setSheet({ mode: "create", preselected: [] })}><Icon name="plus" />New Playlist</button> : null}
        {openPlaylist ? null : <label className="field field--search"><span className="sr-only">Search music</span><Icon name="search" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search music" /></label>}
      </Toolbar>
      <span id="music-title" className="sr-only">Music</span>
      <div className="page-body">
        {openPlaylist && !failed ? (
          <PlaylistView bridge={bridge} playlist={openPlaylist} library={all} onBack={() => setOpenId(null)} onAddSongs={() => setSheet({ mode: "add", playlist: openPlaylist })} />
        ) : <>
        <ListStates loading={loading} failed={failed} retry={retry} empty={items.length === 0 && !query} kind="audio" onGoHome={onGoHome} />
        {!failed && query && !items.length ? <EmptyState title="No songs match." body="Try another search." action={<button type="button" className="btn btn-default" onClick={() => setQuery("")}>Clear search</button>} /> : null}
        {!failed && items.length ? (
          <>
            {!query ? (
              <>
                <h2 className="section-title">Recently Added</h2>
                <ul className="cover-grid">
                  {recent.map((entry) => {
                    const title = mediaTitle(entry);
                    const isCurrent = currentPath === entry.relativePath;
                    return (
                      <li key={entry.relativePath} className={`cover-card ${isCurrent ? "is-current" : ""}`}>
                        <button type="button" className="cover" aria-label={`Play ${title}`} onClick={() => play(entry)}>
                          <Artwork bridge={bridge} entry={entry} name={title} className="cover-art" />
                          <span className="play-disc play-disc--corner" aria-hidden="true"><Icon name={isCurrent && player?.playing ? "pause" : "play"} /></span>
                        </button>
                        <div className="media-meta"><strong title={title}>{title}</strong><span>{entry.durationSeconds !== null ? formatDuration(entry.durationSeconds) : "MP3"}</span></div>
                      </li>
                    );
                  })}
                </ul>
                <PlaylistShelf bridge={bridge} playlists={playlists} library={all} onOpen={setOpenId} onCreate={() => setSheet({ mode: "create", preselected: [] })} />
              </>
            ) : null}
            <h2 className="section-title">Songs</h2>
            <div className="song-table" role="list" aria-label="Songs">
              <div className="song-row song-row--head" aria-hidden="true"><span className="song-n">#</span><span>Title</span><span>Date Added</span><span className="song-time">Time</span><span /></div>
              {items.map((entry, index) => {
                const title = mediaTitle(entry);
                const isCurrent = currentPath === entry.relativePath;
                return (
                  <div key={entry.relativePath} role="listitem" className={`song-row ${isCurrent ? "is-current" : ""}`} onDoubleClick={() => play(entry)}>
                    <span className="song-n">{isCurrent && player?.playing ? <LevelBars /> : index + 1}</span>
                    <button type="button" className="song-title" aria-label={`Play ${title}`} onClick={() => play(entry)}>{title}</button>
                    <span className="song-dim">{formatAdded(entry.modifiedAt)}</span>
                    <span className="song-time">{entry.durationSeconds !== null ? formatDuration(entry.durationSeconds) : "–"}</span>
                    <AddToPlaylist song={entry} playlists={playlists} onAdded={(playlist) => setNotice(`Added to “${playlist.name}”`)} onNew={(path) => setSheet({ mode: "create", preselected: [path] })} />
                  </div>
                );
              })}
            </div>
          </>
        ) : null}
        </>}
      </div>
      {sheet ? (
        <PlaylistSheet
          mode={sheet.mode}
          songs={all}
          playlist={sheet.mode === "add" ? playlists.find((playlist) => playlist.id === sheet.playlist.id) : undefined}
          preselected={sheet.mode === "create" ? sheet.preselected : []}
          onCancel={() => setSheet(null)}
          onDone={(playlist, added) => {
            setSheet(null);
            if (sheet.mode === "create" && sheet.preselected.length) setNotice(`Created “${playlist.name}”`);
            else if (sheet.mode === "create") {
              setOpenId(playlist.id);
              setQuery("");
            } else if (added) setNotice(`Added ${added} ${added === 1 ? "song" : "songs"} to “${playlist.name}”`);
          }}
        />
      ) : null}
      {notice ? <div className="toast" role="status">{notice}</div> : null}
    </section>
  );
}
