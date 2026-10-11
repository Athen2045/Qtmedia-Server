import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PlayerBar, NowPlaying } from "../components/Player";
import { SettingsPage } from "../components/SettingsPage";
import { DesktopSessionProvider } from "./DesktopSession";
import type { AudioEvent, AudioSettings, DesktopBridge, LibraryEntry, NativeAudio, SignalPath } from "./bridge";
import { followingIndex, PlayerProvider, usePlayer } from "./player";
import { describeOutput, describeSource, signalBadge, signalReason } from "./signalPath";

const song = (name: string): LibraryEntry => ({
  relativePath: `audio/${name}.flac`, mediaType: "audio", extension: "flac", sizeBytes: 1, modifiedAt: 1, durationSeconds: 200, artworkPath: null,
});
const songs = [song("A"), song("B"), song("C")];

/** A fake engine: records commands, and lets tests emit `audio-event`s. */
function fakeAudio(settings: AudioSettings = { deviceId: null, mode: "shared", rateMismatch: "strict", exclusiveVolume: false }) {
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
function Probe() {
  api = usePlayer();
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
    expect(api.position).toBe(42.5);
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
    expect(audio.setVolume).toHaveBeenLastCalledWith(0.4);
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
    expect(audio.setSettings).toHaveBeenCalledWith({ deviceId: null, mode: "exclusive", rateMismatch: "strict", exclusiveVolume: false });
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
