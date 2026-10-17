import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { isTauri } from "@tauri-apps/api/core";

import { App } from "./App";
import type { DesktopBridge } from "./lib/bridge";
import { installResizeHint } from "./lib/resizeHint";

async function resolveBridge(): Promise<DesktopBridge | undefined> {
  // `import.meta.env.DEV` is statically false in release builds, so the mock
  // module is dropped from the production bundle.
  if (import.meta.env.DEV && !isTauri()) {
    const { createMockBridge, mockOptionsFromLocation } = await import("./lib/mockBridge");
    console.info("[mock bridge] Running outside Tauri with sample data.");
    return createMockBridge(mockOptionsFromLocation(window.location.search));
  }
  return undefined;
}

installResizeHint();

void resolveBridge().then((bridge) => {
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App bridge={bridge} />
    </StrictMode>,
  );
});
