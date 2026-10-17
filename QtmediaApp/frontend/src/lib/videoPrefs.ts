/** Video player preferences kept in local storage (conveniences only). */

const AUTOPLAY_KEY = "qtmedia.video.autoplay";
const VOLUME_KEY = "qtmedia.video.volume";

export function readAutoplay() {
  try {
    return localStorage.getItem(AUTOPLAY_KEY) !== "off";
  } catch {
    return true;
  }
}

export function writeAutoplay(on: boolean) {
  try {
    localStorage.setItem(AUTOPLAY_KEY, on ? "on" : "off");
  } catch {
    // A convenience only.
  }
}

/** The player's last volume and mute, applied to each video it opens. */
export function readVideoVolume(): { volume: number; muted: boolean } | null {
  try {
    const saved = JSON.parse(localStorage.getItem(VOLUME_KEY) ?? "null") as { volume?: unknown; muted?: unknown } | null;
    if (!saved || typeof saved.volume !== "number" || saved.volume < 0 || saved.volume > 1) return null;
    return { volume: saved.volume, muted: saved.muted === true };
  } catch {
    return null;
  }
}

export function writeVideoVolume(volume: number, muted: boolean) {
  try {
    localStorage.setItem(VOLUME_KEY, JSON.stringify({ volume, muted }));
  } catch {
    // A convenience only.
  }
}
