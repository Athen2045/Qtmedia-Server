import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PlayerBar, NowPlaying } from "../components/Player";
import { SettingsPage } from "../components/SettingsPage";
import { DesktopSessionProvider } from "./DesktopSession";
import type { AudioEvent, AudioSettings, DesktopBridge, LibraryEntry, NativeAudio, SignalPath } from "./bridge";
import { followingIndex, PLAYER_KEY, PlayerProvider, usePlayer, usePlayerPosition, usePlayerShortcuts, volumeGain } from "./player";
import { readBluetoothDelay, writeBluetoothDelay } from "./bluetoothDelay";
import { describeOutput, describeSource, signalBadge, signalReason } from "./signalPath";

const song = (name: string): LibraryEntry => ({
  relativePath: `audio/${name}.flac`, mediaType: "audio", extension: "flac", sizeBytes: 1, modifiedAt: 1, durationSeconds: 200, artworkPath: null,
});
const songs = [song("A"), song("B"), song("C")];

/** A fake engine: records commands, and lets tests emit `audio-event`s. */
function fakeAudio(settings: AudioSettings = { deviceId: null, mode: "shared", rateMismatch: "strict", exclusiveVolume: false, levelling: true }) {
  const listeners = new Set<(event: AudioEvent) => void>();
  const audio = {
    play: vi.fn(async () => undefined),
    pause: vi.fn(async () => undefined),
    resume: vi.fn(async () => undefined),
    seek: vi.fn(async () => undefined),
    stop: vi.fn(async () => undefined),
    release: vi.fn(async () => undefined),
    setVolume: vi.fn(async () => undefined),
    setNext: vi.fn(async () => undefined),
    devices: vi.fn(async () => [
      { id: "speakers", name: "Speakers (Realtek)", transport: "wired" as const, isDefault: false },
      { id: "airbass", name: "Headphones (AirBass)", transport: "bluetooth" as const, isDefault: true },
    ]),
    getSettings: vi.fn(async () => settings),
    setSettings: vi.fn(async (next: AudioSettings) => next),
    subscribe: vi.fn(async (listener: (event: AudioEvent) => void) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    }),
  } satisfies NativeAudio;
  const emit = (event: AudioEvent) => act(() => listeners.forEach((listener) => listener(event)));
  return { audio, emit };
}

function bridgeWith(audio: NativeAudio, playable = true): DesktopBridge {
  return {
    inspectLink: vi.fn(), startDownload: vi.fn(), cancelDownload: vi.fn(),
    listLibrary: vi.fn().mockResolvedValue(songs), openMedia: vi.fn(), openLibrary: vi.fn(), readArtwork: vi.fn().mockResolvedValue(null),
    getDownloadLocation: vi.fn().mockResolvedValue({ path: "C:\\lib", isDefault: true }), chooseDownloadLocation: vi.fn(), useDefaultDownloadLocation: vi.fn(),
    minimizeWindow: vi.fn(), toggleMaximizeWindow: vi.fn(), closeWindow: vi.fn(),
    subscribe: vi.fn().mockResolvedValue(() => undefined),
    audio,
    ...(playable ? { mediaUrl: (path: string) => `qtmedia://localhost/${encodeURIComponent(path)}` } : {}),
  };
}

let api: ReturnType<typeof usePlayer>;
let position = 0;
function Probe() {
  api = usePlayer();
  position = usePlayerPosition();
  return null;
}

const bitPerfect: SignalPath = {
  source: { codec: "flac", sampleRate: 96000, channels: 2, bitsPerSample: 24 },
  output: { mode: "exclusive", sampleRate: 96000, channels: 2, bits: 24, containerBits: 32, float: false },
  bitPerfect: true, reason: null, device: { name: "Speakers (Realtek)", transport: "wired" }, volumeLocked: true,
};
const bluetooth: SignalPath = {
  source: { codec: "flac", sampleRate: 44100, channels: 2, bitsPerSample: 16 },
  output: { mode: "shared", sampleRate: 48000, channels: 2, bits: 32, containerBits: 32, float: true },
  bitPerfect: false, reason: "shared_mode", device: { name: "Headphones (AirBass)", transport: "bluetooth" }, volumeLocked: false,
};

describe("native playback", () => {
  it("plays through the engine and queues the next song for gapless joins", async () => {
    const { audio, emit } = fakeAudio();
    render(<PlayerProvider bridge={bridgeWith(audio)}><Probe /></PlayerProvider>);
    act(() => api.playQueue(songs, 0));
    expect(audio.play).toHaveBeenCalledWith("audio/A.flac", 0);
    expect(api.backend).toBe("native");
    expect(audio.setNext).toHaveBeenLastCalledWith("audio/B.flac");

    // The engine joins B by itself: the player follows and queues C.
    emit({ type: "state", state: "playing" });
    emit({ type: "trackStarted", path: "audio/B.flac", durationSeconds: 180, source: bitPerfect.source });
    expect(api.current?.relativePath).toBe("audio/B.flac");
    expect(api.duration).toBe(180);
    expect(audio.play).toHaveBeenCalledOnce();
    expect(audio.setNext).toHaveBeenLastCalledWith("audio/C.flac");

    act(() => api.cycleRepeat()); // all
    emit({ type: "trackStarted", path: "audio/C.flac", durationSeconds: 200, source: bitPerfect.source });
    expect(audio.setNext).toHaveBeenLastCalledWith("audio/A.flac");
    act(() => api.cycleRepeat()); // one
    expect(audio.setNext).toHaveBeenLastCalledWith("audio/C.flac");

    emit({ type: "position", seconds: 42.5 });
    expect(position).toBe(42.5);
    emit({ type: "state", state: "idle" });
    expect(api.playing).toBe(false);
  });

  it("pauses, resumes, seeks, sets volume and frees the device for video", () => {
    const { audio, emit } = fakeAudio();
    render(<PlayerProvider bridge={bridgeWith(audio)}><Probe /></PlayerProvider>);
    act(() => api.playQueue(songs, 1));
    emit({ type: "state", state: "playing" });
    act(() => api.toggle());
    expect(audio.pause).toHaveBeenCalled();
    act(() => api.toggle());
    expect(audio.resume).toHaveBeenCalled();
    act(() => api.seek(30));
    expect(audio.seek).toHaveBeenCalledWith(30);
    act(() => api.setVolume(0.4));
    // A cubic loudness curve: 40 % on the slider is 0.064 gain (about -24 dB).
    expect(audio.setVolume).toHaveBeenLastCalledWith(expect.closeTo(0.064, 5));
    act(() => api.toggleMute());
    expect(audio.setVolume).toHaveBeenLastCalledWith(0);
    act(() => api.releaseDevice());
    expect(audio.release).toHaveBeenCalled();
    expect(api.playing).toBe(false);
  });

  it("reloads at the last position when play is pressed after the engine stopped", () => {
    const { audio, emit } = fakeAudio();
    render(<PlayerProvider bridge={bridgeWith(audio)}><Probe /></PlayerProvider>);
    act(() => api.playQueue(songs, 0));
    emit({ type: "state", state: "playing" });
    emit({ type: "position", seconds: 12 });
    emit({ type: "error", code: "audio_device_lost" });
    expect(api.failed).toBe(true);
    expect(api.error).toBe("audio_device_lost");
    act(() => api.toggle());
    expect(audio.play).toHaveBeenLastCalledWith("audio/A.flac", 12);
  });

  it("falls back to webview playback when the engine is unavailable", () => {
    const { audio, emit } = fakeAudio();
    const play = vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
    render(<PlayerProvider bridge={bridgeWith(audio)}><Probe /></PlayerProvider>);
    act(() => api.playQueue(songs, 0));
    emit({ type: "error", code: "audio_unavailable" });
    expect(api.backend).toBe("html");
    expect(play).toHaveBeenCalled();
    expect(api.failed).toBe(false);
    play.mockRestore();
  });

  it("knows which song follows in each repeat mode", () => {
    expect(followingIndex(3, 0, "off")).toBe(1);
    expect(followingIndex(3, 2, "off")).toBe(-1);
    expect(followingIndex(3, 2, "all")).toBe(0);
    expect(followingIndex(3, 1, "one")).toBe(1);
    expect(followingIndex(0, -1, "all")).toBe(-1);
  });
});

describe("signal path display", () => {
  it("describes the file, the output and why it isn't bit-perfect", () => {
    expect(describeSource(bitPerfect.source)).toBe("FLAC 96 kHz · 24-bit");
    expect(describeSource({ codec: "mp3", sampleRate: 44100, channels: 2, bitsPerSample: null })).toBe("MP3 44.1 kHz");
    expect(describeOutput(bitPerfect.output)).toBe("Exclusive 96 kHz · 24-bit");
    expect(describeOutput(bluetooth.output)).toBe("Shared 48 kHz");
    expect(signalBadge(bitPerfect)).toEqual({ label: "Bit-perfect", tone: "perfect" });
    expect(signalBadge(bluetooth).label).toBe("Bluetooth · not lossless");
    expect(signalReason(bluetooth)).toMatch(/never lossless/);
    expect(signalReason({ ...bluetooth, reason: "exclusive_format_unsupported" })).toMatch(/never lossless/);
    expect(signalBadge({ ...bluetooth, device: { name: "Headset", transport: "bluetoothHandsFree" } }).tone).toBe("warn");
    expect(signalBadge({ ...bluetooth, device: null, reason: "exclusive_denied" }).label).toBe("Shared · exclusive unavailable");
    expect(signalReason(bitPerfect)).toBeNull();
  });

  it("shows the chip, locks volume in strict exclusive mode, and details it in Now Playing", () => {
    const { audio, emit } = fakeAudio();
    const bridge = bridgeWith(audio);
    render(<PlayerProvider bridge={bridge}><Probe /><PlayerBar bridge={bridge} /><NowPlaying bridge={bridge} /></PlayerProvider>);
    act(() => api.playQueue(songs, 0));
    emit({ type: "signalPath", ...bitPerfect });
    const bar = screen.getByRole("contentinfo", { name: "Music player" });
    expect(within(bar).getByText("Bit-perfect")).toBeInTheDocument();
    const volume = within(bar).getByRole("slider", { name: "Volume" });
    expect(volume).toBeDisabled();
    expect(volume).toHaveAttribute("title", "Bit-perfect: use your amplifier or DAC volume");

    act(() => api.openNowPlaying());
    // Now Playing shows only the chip; the path is in its tooltip.
    const path = screen.getByLabelText("Signal path");
    expect(path).toHaveTextContent(/^Bit-perfect$/);
    expect(within(path).getByText("Bit-perfect")).toHaveAttribute("title", expect.stringContaining("FLAC 96 kHz · 24-bit → Exclusive 96 kHz · 24-bit · Speakers (Realtek)"));

    emit({ type: "signalPath", ...bluetooth });
    expect(within(bar).getByText("Bluetooth · not lossless")).toBeInTheDocument();
    expect(within(bar).getByRole("slider", { name: "Volume" })).not.toBeDisabled();
    expect(screen.getByLabelText("Signal path")).not.toHaveTextContent(/never lossless/);
    expect(within(screen.getByLabelText("Signal path")).getByText("Bluetooth · not lossless")).toHaveAttribute("title", expect.stringMatching(/never lossless/));
  });
});

describe("Settings → Audio", () => {
  it("lists devices, saves mode changes and explains Bluetooth", async () => {
    const { audio, emit } = fakeAudio();
    const bridge = bridgeWith(audio);
    render(<DesktopSessionProvider bridge={bridge}><PlayerProvider bridge={bridge}><SettingsPage bridge={bridge} /></PlayerProvider></DesktopSessionProvider>);

    const device = await screen.findByRole("combobox", { name: "Output device" });
    expect(await within(device).findByRole("option", { name: "Headphones (AirBass) · Bluetooth" })).toBeInTheDocument();
    expect(within(device).getByRole("option", { name: "Windows default (Headphones (AirBass))" })).toBeInTheDocument();
    expect(screen.getByText(/never lossless/)).toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox", { name: "Mode" }), { target: { value: "exclusive" } });
    expect(audio.setSettings).toHaveBeenCalledWith({ deviceId: null, mode: "exclusive", rateMismatch: "strict", exclusiveVolume: false, levelling: true });
    expect(await screen.findByRole("combobox", { name: "If the device can't play the file's sample rate" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("switch", { name: "Allow volume control in exclusive mode" }));
    expect(audio.setSettings).toHaveBeenLastCalledWith(expect.objectContaining({ exclusiveVolume: true }));

    fireEvent.change(device, { target: { value: "speakers" } });
    expect(audio.setSettings).toHaveBeenLastCalledWith(expect.objectContaining({ deviceId: "speakers" }));
    expect(await screen.findByText(/Bit-perfect" means/)).toBeInTheDocument();

    emit({ type: "deviceChanged", devices: [{ id: "airbass", name: "Headphones (AirBass)", transport: "bluetooth", isDefault: true }], fallback: true });
    expect(screen.getByText(/isn't connected, so music plays on the Windows default/)).toBeInTheDocument();
  });
});

describe("remembering the player", () => {
  it("brings back settings, the queue and the position, paused, and plays from there", async () => {
    const first = fakeAudio();
    const view = render(<PlayerProvider bridge={bridgeWith(first.audio)}><Probe /></PlayerProvider>);
    act(() => api.setVolume(0.5));
    act(() => api.toggleShuffle());
    act(() => api.cycleRepeat());
    act(() => api.playQueue(songs, 1));
    first.emit({ type: "position", seconds: 61 });
    act(() => api.toggle());
    view.unmount();

    const second = fakeAudio();
    render(<PlayerProvider bridge={bridgeWith(second.audio)}><Probe /></PlayerProvider>);

    expect(api.volume).toBe(0.5);
    expect(api.shuffle).toBe(true);
    expect(api.repeat).toBe("all");
    expect(api.current?.relativePath).toBe("audio/B.flac");
    expect(api.playing).toBe(false);
    expect(position).toBe(61);
    expect(second.audio.play).not.toHaveBeenCalled();
    // Seeking a cued song only moves where it will start.
    act(() => api.seek(70));
    expect(second.audio.seek).not.toHaveBeenCalled();
    act(() => api.toggle());
    expect(second.audio.play).toHaveBeenCalledWith("audio/B.flac", 70);
  });

  it("drops restored songs that are no longer in the library", async () => {
    localStorage.setItem(PLAYER_KEY, JSON.stringify({ queue: [songs[0], song("Gone")], ordered: [songs[0], song("Gone")], index: 1, position: 12 }));
    render(<PlayerProvider bridge={bridgeWith(fakeAudio().audio)}><Probe /></PlayerProvider>);
    expect(api.current?.relativePath).toBe("audio/Gone.flac");
    await waitFor(() => expect(api.current).toBeNull());
    expect(position).toBe(0);
  });

  it("ignores a corrupt saved player", () => {
    localStorage.setItem(PLAYER_KEY, "{not json");
    render(<PlayerProvider bridge={bridgeWith(fakeAudio().audio)}><Probe /></PlayerProvider>);
    expect(api.current).toBeNull();
    expect(api.volume).toBe(0.8);
  });

  it("maps the slider to a cubic gain", () => {
    expect(volumeGain(0)).toBe(0);
    expect(volumeGain(1)).toBe(1);
    expect(volumeGain(0.5)).toBeCloseTo(0.125);
    expect(volumeGain(2)).toBe(1);
  });
});

describe("player rendering", () => {
  it("does not re-render ordinary player consumers on position ticks", () => {
    const { audio, emit } = fakeAudio();
    let renders = 0;
    function Counter() {
      usePlayer();
      renders += 1;
      return null;
    }
    render(<PlayerProvider bridge={bridgeWith(audio)}><Probe /><Counter /></PlayerProvider>);
    act(() => api.playQueue(songs, 0));
    const before = renders;
    for (const seconds of [1, 1.25, 1.5, 1.75]) emit({ type: "position", seconds });
    expect(renders).toBe(before);
    expect(position).toBe(1.75);
  });

  it("seeks once when a drag on the seek bar ends", () => {
    const { audio, emit } = fakeAudio();
    render(<PlayerProvider bridge={bridgeWith(audio)}><Probe /><PlayerBar bridge={bridgeWith(audio)} /></PlayerProvider>);
    act(() => api.playQueue(songs, 0));
    emit({ type: "state", state: "playing" });
    const bar = screen.getByRole("slider", { name: "Seek" });

    fireEvent.pointerDown(bar);
    fireEvent.change(bar, { target: { value: "40" } });
    fireEvent.change(bar, { target: { value: "90" } });
    expect(audio.seek).not.toHaveBeenCalled();
    expect(bar).toHaveValue("90");
    fireEvent.pointerUp(bar);
    expect(audio.seek).toHaveBeenCalledTimes(1);
    expect(audio.seek).toHaveBeenCalledWith(90);

    // Keyboard steps seek straight away.
    fireEvent.change(bar, { target: { value: "95" } });
    expect(audio.seek).toHaveBeenLastCalledWith(95);
  });
});

describe("play next and add to queue", () => {
  const more = [song("D"), song("E")];

  it("puts songs after the current one or at the end, moving duplicates", () => {
    const { audio } = fakeAudio();
    render(<PlayerProvider bridge={bridgeWith(audio)}><Probe /></PlayerProvider>);
    act(() => api.playQueue(songs, 0));

    act(() => api.addToQueue([more[0]]));
    act(() => api.playNext([more[1]]));
    expect(api.queue.map((item) => item.relativePath)).toEqual(["audio/A.flac", "audio/E.flac", "audio/B.flac", "audio/C.flac", "audio/D.flac"]);
    // A song already queued moves; the playing song stays put.
    act(() => api.playNext([songs[2], songs[0]]));
    expect(api.queue.map((item) => item.relativePath)).toEqual(["audio/A.flac", "audio/C.flac", "audio/E.flac", "audio/B.flac", "audio/D.flac"]);
    expect(api.current?.relativePath).toBe("audio/A.flac");
    expect(audio.setNext).toHaveBeenLastCalledWith("audio/C.flac");
  });

  it("starts playing when nothing is queued", () => {
    const { audio } = fakeAudio();
    render(<PlayerProvider bridge={bridgeWith(audio)}><Probe /></PlayerProvider>);
    act(() => api.addToQueue([more[0]]));
    expect(api.current?.relativePath).toBe("audio/D.flac");
    expect(audio.play).toHaveBeenCalledWith("audio/D.flac", 0);
  });
});

describe("music shortcuts", () => {
  function Shortcuts({ enabled }: { enabled: boolean }) {
    api = usePlayer();
    usePlayerShortcuts(api, enabled);
    return <input aria-label="Search" />;
  }

  it("Space, Ctrl+arrows control music, but not while typing or with a video open", () => {
    const { audio, emit } = fakeAudio();
    const view = render(<PlayerProvider bridge={bridgeWith(audio)}><Shortcuts enabled /></PlayerProvider>);
    act(() => api.playQueue(songs, 0));
    emit({ type: "state", state: "playing" });

    fireEvent.keyDown(document.body, { key: " " });
    expect(audio.pause).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(document.body, { key: "ArrowRight", ctrlKey: true });
    expect(api.current?.relativePath).toBe("audio/B.flac");
    fireEvent.keyDown(document.body, { key: "ArrowLeft", ctrlKey: true });
    expect(api.current?.relativePath).toBe("audio/A.flac");
    act(() => api.setVolume(0.5));
    fireEvent.keyDown(document.body, { key: "ArrowUp", ctrlKey: true });
    expect(api.volume).toBeCloseTo(0.55);

    fireEvent.keyDown(screen.getByRole("textbox", { name: "Search" }), { key: " " });
    expect(audio.pause).toHaveBeenCalledTimes(1);

    view.rerender(<PlayerProvider bridge={bridgeWith(audio)}><Shortcuts enabled={false} /></PlayerProvider>);
    fireEvent.keyDown(document.body, { key: "ArrowRight", ctrlKey: true });
    expect(api.current?.relativePath).toBe("audio/A.flac");
  });
});

describe("Bluetooth lyrics delay", () => {
  it("is set in Settings for a Bluetooth output and clamped", async () => {
    const { audio } = fakeAudio();
    const bridge = bridgeWith(audio);
    render(<DesktopSessionProvider bridge={bridge}><PlayerProvider bridge={bridge}><SettingsPage bridge={bridge} /></PlayerProvider></DesktopSessionProvider>);

    const slider = await screen.findByRole("slider", { name: "Lyrics delay on Bluetooth" });
    fireEvent.change(slider, { target: { value: "180" } });
    expect(readBluetoothDelay()).toBe(180);
    expect(screen.getByText(/\(180 ms\)/)).toBeInTheDocument();
    writeBluetoothDelay(9000);
    expect(readBluetoothDelay()).toBe(500);
  });

  it("is not offered for wired outputs", async () => {
    const { audio } = fakeAudio();
    audio.devices.mockResolvedValue([{ id: "speakers", name: "Speakers (Realtek)", transport: "wired", isDefault: true }]);
    const bridge = bridgeWith(audio);
    render(<DesktopSessionProvider bridge={bridge}><PlayerProvider bridge={bridge}><SettingsPage bridge={bridge} /></PlayerProvider></DesktopSessionProvider>);
    await screen.findByRole("combobox", { name: "Output device" });
    expect(screen.queryByRole("slider", { name: "Lyrics delay on Bluetooth" })).not.toBeInTheDocument();
  });
});

describe("lossy source chip", () => {
  it("marks FLACs made from a lossy stream in the player bar", async () => {
    const { audio, emit } = fakeAudio();
    const bridge = { ...bridgeWith(audio), readTrackInfo: vi.fn(async (path: string) => ({ title: null, artist: null, album: null, durationSeconds: 200, lossySource: path.endsWith("A.flac") ? "Opus 160 kbps" : null })) };
    render(<PlayerProvider bridge={bridge}><Probe /><PlayerBar bridge={bridge} /></PlayerProvider>);
    act(() => api.playQueue(songs, 0));
    emit({ type: "state", state: "playing" });

    const chip = await screen.findByText("Lossy source");
    expect(chip).toHaveAttribute("title", expect.stringContaining("Downloaded as Opus 160 kbps and saved as FLAC"));
    act(() => api.next());
    await waitFor(() => expect(screen.queryByText("Lossy source")).not.toBeInTheDocument());
  });
});

describe("volume levelling", () => {
  it("is switched in Settings and explained in the signal path", async () => {
    const { audio } = fakeAudio();
    const bridge = bridgeWith(audio);
    render(<DesktopSessionProvider bridge={bridge}><PlayerProvider bridge={bridge}><SettingsPage bridge={bridge} /></PlayerProvider></DesktopSessionProvider>);

    const toggle = await screen.findByRole("switch", { name: "Volume levelling" });
    expect(toggle).toHaveAttribute("aria-checked", "true");
    fireEvent.click(toggle);
    await waitFor(() => expect(audio.setSettings).toHaveBeenLastCalledWith(expect.objectContaining({ levelling: false })));

    const levelled = { ...bitPerfect, bitPerfect: false, reason: "volume_levelling", device: { name: "DAC", transport: "wired" as const } };
    expect(signalBadge(levelled).label).toBe("Exclusive · levelled");
    expect(signalReason(levelled)).toMatch(/same loudness/);
  });
});
