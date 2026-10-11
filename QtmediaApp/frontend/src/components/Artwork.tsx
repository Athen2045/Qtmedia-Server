import { useEffect, useState } from "react";

import type { DesktopBridge, LibraryEntry } from "../lib/bridge";
import { Icon } from "./Icon";

/** Loads a library artwork file as a local data URL (null while loading or absent). */
export function useArtwork(bridge: DesktopBridge, artworkPath: string | null) {
  const [source, setSource] = useState<string | null>(null);
  useEffect(() => {
    let mounted = true;
    setSource(null);
    if (artworkPath) {
      void bridge.readArtwork(artworkPath).then((value) => {
        if (mounted) setSource(value);
      }).catch(() => undefined);
    }
    return () => { mounted = false; };
  }, [bridge, artworkPath]);
  return source;
}

/** Local artwork for a library entry, with a typed placeholder when absent. */
export function Artwork({ bridge, entry, name, className = "" }: { bridge: DesktopBridge; entry: LibraryEntry; name: string; className?: string }) {
  const source = useArtwork(bridge, entry.artworkPath);
  if (source) return <img className={`artwork ${className}`} src={source} alt={`Artwork for ${name}`} />;
  return <div className={`artwork artwork--empty ${className}`}><Icon name={entry.mediaType === "audio" ? "music" : "video"} /></div>;
}
