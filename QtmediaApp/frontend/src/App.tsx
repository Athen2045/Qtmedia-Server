import { useState } from "react";

import "./app.css";
import { ComingSoonPage } from "./components/ComingSoonPage";
import { ActivityTray } from "./components/ActivityTray";
import { FilesPage } from "./components/FilesPage";
import { HomePage } from "./components/HomePage";
import { NavRail, type Route } from "./components/NavRail";
import { detectDesktopPlatform, WindowControls } from "./components/WindowControls";
import { DesktopSessionProvider, useDesktopSession } from "./lib/DesktopSession";
import { desktopBridge, type DesktopBridge } from "./lib/bridge";
import { SettingsPage } from "./components/SettingsPage";

const futureTitles: Record<Exclude<Route, "home" | "files" | "settings">, string> = {
  video: "Video player",
  music: "Music player",
};

export function App({ bridge = desktopBridge }: { bridge?: DesktopBridge }) {
  return <DesktopSessionProvider bridge={bridge}><AppShell bridge={bridge} /></DesktopSessionProvider>;
}

function AppShell({ bridge }: { bridge: DesktopBridge }) {
  const [route, setRoute] = useState<Route>("home");
  const { libraryRevision } = useDesktopSession();
  const platform = detectDesktopPlatform();
  return (
    <div className={`app-shell platform-${platform}`}>
      <NavRail active={route} onNavigate={setRoute} />
      <div className="app-stage">
        <div className="drag-region" data-tauri-drag-region />
        <WindowControls bridge={bridge} platform={platform} />
        <main>
          {route === "home" ? <HomePage onOpenFiles={() => setRoute("files")} /> : null}
          {route === "files" ? <FilesPage bridge={bridge} refreshToken={libraryRevision} onGoHome={() => setRoute("home")} /> : null}
          {route === "settings" ? <SettingsPage bridge={bridge} /> : null}
          {route !== "home" && route !== "files" && route !== "settings" ? <ComingSoonPage title={futureTitles[route]} /> : null}
        </main>
        {route !== "home" ? <ActivityTray /> : null}
      </div>
    </div>
  );
}
