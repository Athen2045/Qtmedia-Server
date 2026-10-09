import type { DesktopBridge } from "../lib/bridge";
import { Icon } from "./Icon";

export type DesktopPlatform = "windows" | "macos";

export function detectDesktopPlatform(): DesktopPlatform {
  return /Macintosh|Mac OS X/.test(navigator.userAgent) ? "macos" : "windows";
}

export function WindowControls({
  bridge,
  platform = detectDesktopPlatform(),
}: {
  bridge: DesktopBridge;
  platform?: DesktopPlatform;
}) {
  if (platform === "macos") return null;
  return (
    <div className="window-controls" aria-label="Window controls">
      <button type="button" aria-label="Minimize" onClick={() => void bridge.minimizeWindow()}>
        <Icon name="minimize" />
      </button>
      <button type="button" aria-label="Maximize or restore" onClick={() => void bridge.toggleMaximizeWindow()}>
        <Icon name="maximize" />
      </button>
      <button type="button" className="window-close" aria-label="Close" onClick={() => void bridge.closeWindow()}>
        <Icon name="close" />
      </button>
    </div>
  );
}
