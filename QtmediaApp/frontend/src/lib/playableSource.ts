import { useEffect, useState } from "react";

import type { DesktopBridge } from "./bridge";

/** Whether this webview decodes Dolby Digital (Plus); Windows editions without
 * the Dolby decoder get AC-3/E-AC-3 converted instead. */
function decodesDolby() {
  try {
    const probe = document.createElement("video");
    return Boolean(probe.canPlayType('audio/mp4; codecs="ec-3"')) && Boolean(probe.canPlayType('audio/mp4; codecs="ac-3"'));
  } catch {
    return false;
  }
}

export type PlayableSource =
  | { kind: "checking" }
  | { kind: "ready"; src: string }
  | { kind: "preparing"; id: string; mode: "remux" | "transcode" | "preparing"; percent: number | null }
  | { kind: "failed" }
  | { kind: "unavailable" };

/**
 * The URL the player can play for a library video: the file itself, or a
 * prepared copy for formats the webview can't play as they are (MKV, MOV,
 * AVI, AC-3 audio …). Closing the player stops an unfinished preparation.
 */
export function usePlayableSource(bridge: DesktopBridge, relativePath: string): PlayableSource {
  const [source, setSource] = useState<PlayableSource>(() => (
    !bridge.mediaUrl ? { kind: "unavailable" }
      : bridge.preparePlayback ? { kind: "checking" }
        : { kind: "ready", src: bridge.mediaUrl(relativePath) }
  ));

  useEffect(() => {
    const mediaUrl = bridge.mediaUrl;
    if (!mediaUrl) return;
    if (!bridge.preparePlayback) {
      setSource({ kind: "ready", src: mediaUrl(relativePath) });
      return;
    }
    // A different video: never keep playing the previous one's source.
    setSource((current) => (current.kind === "checking" ? current : { kind: "checking" }));
    let active = true;
    let jobId: string | null = null;
    let finished = false;
    let unlisten: (() => void) | null = null;
    const ready = (url: string) => {
      finished = true;
      if (active) setSource({ kind: "ready", src: mediaUrl(url) });
    };
    void (async () => {
      // Listen first so a quick "ready" is never missed.
      unlisten = (await bridge.subscribePlayback?.((event) => {
        if (!active || event.id !== jobId) return;
        if (event.type === "progress") setSource((current) => (current.kind === "preparing" ? { ...current, percent: event.percent } : current));
        else if (event.type === "ready") ready(event.url);
        else {
          finished = true;
          setSource({ kind: "failed" });
        }
      }).catch(() => null)) ?? null;
      if (!active) {
        unlisten?.();
        return;
      }
      try {
        const plan = await bridge.preparePlayback!(relativePath, { dolby: decodesDolby() });
        if (!active) return;
        if (plan.kind === "direct") ready(relativePath);
        else if (plan.kind === "ready") ready(plan.url);
        else {
          jobId = plan.id;
          setSource({ kind: "preparing", id: plan.id, mode: plan.mode, percent: null });
        }
      } catch {
        finished = true;
        if (active) setSource({ kind: "failed" });
      }
    })();
    return () => {
      active = false;
      unlisten?.();
      if (jobId && !finished) void bridge.cancelPlayback?.(jobId).catch(() => undefined);
    };
  }, [bridge, relativePath]);

  return source;
}
