import { lazy, Suspense, useEffect, useMemo, useState } from "react";

import "./app.css";
import { FilesPage } from "./components/FilesPage";
import { HomePage } from "./components/HomePage";
import { MusicPage, VideoPage } from "./components/MediaPages";
import { NowPlaying, PlayerBar } from "./components/Player";
import { SettingsPage } from "./components/SettingsPage";
import { Sidebar, type Route } from "./components/Shell";
import { detectDesktopPlatform, WindowControls } from "./components/WindowControls";
import { DesktopSessionProvider, useDesktopSession } from "./lib/DesktopSession";
import { desktopBridge, type DesktopBridge, type LibraryEntry } from "./lib/bridge";
import { PlayerProvider, usePlayer, usePlayerShortcuts } from "./lib/player";
import { applyRenames } from "./lib/renames";

// Video.js loads only when a video is opened.
const VideoOverlay = lazy(() => import("./components/VideoOverlay"));

export function App({ bridge = desktopBridge }: { bridge?: DesktopBridge }) {
  return (
    <DesktopSessionProvider bridge={bridge}>
      <PlayerProvider bridge={bridge}>
        <AppShell bridge={bridge} />
      </PlayerProvider>
    </DesktopSessionProvider>
  );
}

function AppShell({ bridge }: { bridge: DesktopBridge }) {
  const [route, setRoute] = useState<Route>("home");
  const { libraryRevision } = useDesktopSession();
  const player = usePlayer();
  const platform = detectDesktopPlatform();
  const goHome = () => setRoute("home");
  // The opened video and the list it was opened from (array + index, like the music queue).
  const [videos, setVideos] = useState<{ list: LibraryEntry[]; index: number } | null>(null);
  const video = videos ? videos.list[videos.index] ?? null : null;
  // Playlists and resume positions follow files renamed to clean names, even
  // before a library page is opened.
  useEffect(() => {
    void bridge.libraryRenames?.().then(applyRenames, () => undefined);
  }, [bridge, libraryRevision]);
  usePlayerShortcuts(player, !video);
  // The Private folder locked (idle, library switch): stop any private video.
  useEffect(() => {
    let stop: (() => void) | null = null;
    let active = true;
    void bridge.vault?.subscribe((event) => {
      if (event.type === "locked") setVideos((current) => (current && current.list[current.index]?.relativePath.startsWith("vault/") ? null : current));
    }).then((unlisten) => { if (active) stop = unlisten; else unlisten(); }).catch(() => undefined);
    return () => { active = false; stop?.(); };
  }, [bridge]);
  const showPlayerBar = player.available && (Boolean(player.current) || route === "music");
  const playVideo = (entry: LibraryEntry, list: LibraryEntry[] = [entry]) => {
    // Pauses music and frees the audio device (exclusive mode would block video sound).
    player.releaseDevice();
    const index = list.findIndex((item) => item.relativePath === entry.relativePath);
    setVideos(index >= 0 ? { list, index } : { list: [entry], index: 0 });
  };
  const navigation = useMemo(() => {
    if (!videos || videos.list.length < 2) return undefined;
    const { list, index } = videos;
    const step = (by: number) => setVideos((current) => {
      if (!current) return current;
      const target = current.index + by;
      return target >= 0 && target < current.list.length ? { ...current, index: target } : current;
    });
    return {
      previous: list[index - 1] ?? null,
      next: list[index + 1] ?? null,
      onPrevious: () => step(-1),
      onNext: () => step(1),
    };
  }, [videos]);
  return (
    <div className={`app-shell platform-${platform}`}>
      <Sidebar active={route} onNavigate={setRoute} />
      <div className="app-stage">
        <div className="drag-region" data-tauri-drag-region />
        <WindowControls bridge={bridge} platform={platform} />
        <main>
          {route === "home" ? <HomePage bridge={bridge} onOpenFiles={() => setRoute("files")} onPlayVideo={playVideo} /> : null}
          {route === "video" ? <VideoPage bridge={bridge} refreshToken={libraryRevision} onGoHome={goHome} onShowDownload={goHome} onPlayVideo={playVideo} /> : null}
          {route === "music" ? <MusicPage bridge={bridge} refreshToken={libraryRevision} onGoHome={goHome} onShowDownload={goHome} /> : null}
          {route === "files" ? <FilesPage bridge={bridge} refreshToken={libraryRevision} onGoHome={goHome} onShowDownload={goHome} onPlayVideo={playVideo} /> : null}
          {route === "settings" ? <SettingsPage bridge={bridge} onShowDownload={goHome} /> : null}
        </main>
        {showPlayerBar ? <PlayerBar bridge={bridge} /> : null}
      </div>
      <NowPlaying bridge={bridge} />
      {video ? (
        <Suspense fallback={<div className="video-overlay video-overlay--loading" role="status" aria-label="Loading player" />}>
          <VideoOverlay bridge={bridge} entry={video} navigation={navigation} onClose={() => setVideos(null)} />
        </Suspense>
      ) : null}
    </div>
  );
}
