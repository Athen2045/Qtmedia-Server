import { lazy, Suspense, useState } from "react";

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
import { PlayerProvider, usePlayer } from "./lib/player";

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
  const [video, setVideo] = useState<LibraryEntry | null>(null);
  const showPlayerBar = player.available && (Boolean(player.current) || route === "music");
  const playVideo = (entry: LibraryEntry) => {
    // Pauses music and frees the audio device (exclusive mode would block video sound).
    player.releaseDevice();
    setVideo(entry);
  };
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
          <VideoOverlay key={video.relativePath} bridge={bridge} entry={video} onClose={() => setVideo(null)} />
        </Suspense>
      ) : null}
    </div>
  );
}
