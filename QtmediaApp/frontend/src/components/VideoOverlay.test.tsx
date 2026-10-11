import { act, fireEvent, render, screen } from "@testing-library/react";
import { forwardRef } from "react";
import { describe, expect, it, vi } from "vitest";

import type { DesktopBridge, LibraryEntry } from "../lib/bridge";
import type { ResumeStore } from "../lib/resume";
import VideoOverlay from "./VideoOverlay";

// jsdom cannot run Video.js; the overlay only relies on the native <video> it renders.
vi.mock("@videojs/react/video", () => ({
  VideoPlayer: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  VideoSkin: ({ children }: { children: React.ReactNode }) => <div data-testid="skin">{children}</div>,
  Video: forwardRef<HTMLVideoElement, React.VideoHTMLAttributes<HTMLVideoElement>>((props, ref) => <video ref={ref} data-testid="video" {...props} />),
}));
vi.mock("@videojs/react/video/skin.css", () => ({}));
vi.mock("@videojs/react", () => ({
  SeekButton: ({ seconds, children, ...props }: { seconds: number; children?: React.ReactNode } & React.ButtonHTMLAttributes<HTMLButtonElement>) => <button type="button" data-seconds={seconds} {...props}>{children}</button>,
}));

const entry: LibraryEntry = {
  relativePath: "video/Clip [media-abc].mp4",
  mediaType: "video",
  extension: "mp4",
  sizeBytes: 1024,
  modifiedAt: 1,
  durationSeconds: null,
  artworkPath: null,
};

function memoryResume(initial: Record<string, number> = {}): ResumeStore & { saved: Record<string, number> } {
  const saved = { ...initial };
  return {
    saved,
    get: (path) => saved[path] ?? null,
    save: (path, position) => { saved[path] = position; },
    clear: (path) => { delete saved[path]; },
  };
}

function bridge(overrides: Partial<DesktopBridge> = {}) {
  return {
    openMedia: vi.fn().mockResolvedValue(undefined),
    mediaUrl: (path: string) => `qtmedia://localhost/${encodeURIComponent(path)}`,
    ...overrides,
  } as unknown as DesktopBridge;
}

function video() {
  const element = screen.getByTestId("video") as HTMLVideoElement;
  let time = 0;
  Object.defineProperty(element, "currentTime", { configurable: true, get: () => time, set: (value) => { time = value; } });
  Object.defineProperty(element, "duration", { configurable: true, get: () => 600 });
  return element;
}

describe("VideoOverlay", () => {
  it("streams the entry over qtmedia:// and focuses the close button", () => {
    render(<VideoOverlay bridge={bridge()} entry={entry} onClose={vi.fn()} resume={memoryResume()} />);

    expect(screen.getByRole("dialog", { name: /^Playing Clip/ })).toBeInTheDocument();
    expect(screen.getByTestId("video")).toHaveAttribute("src", "qtmedia://localhost/video%2FClip%20%5Bmedia-abc%5D.mp4");
    expect(screen.getByRole("button", { name: "Close video" })).toHaveFocus();
  });

  it("offers 10-second skip buttons inside the player", () => {
    render(<VideoOverlay bridge={bridge()} entry={entry} onClose={vi.fn()} resume={memoryResume()} />);

    const skin = screen.getByTestId("skin");
    expect(skin).toContainElement(screen.getByRole("button", { name: "Back 10 seconds" }));
    expect(screen.getByRole("button", { name: "Back 10 seconds" })).toHaveAttribute("data-seconds", "-10");
    expect(screen.getByRole("button", { name: "Forward 10 seconds" })).toHaveAttribute("data-seconds", "10");
  });

  it("resumes at the saved position and can start over", () => {
    const resume = memoryResume({ [entry.relativePath]: 125 });
    render(<VideoOverlay bridge={bridge()} entry={entry} onClose={vi.fn()} resume={resume} />);
    const element = video();

    fireEvent.loadedMetadata(element);

    expect(element.currentTime).toBe(125);
    expect(screen.getByText(/Resumed at 2:05/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Start over" }));
    expect(element.currentTime).toBe(0);
    expect(resume.saved[entry.relativePath]).toBeUndefined();
    expect(screen.queryByText(/Resumed at/)).not.toBeInTheDocument();
  });

  it("saves the position on pause and when Esc closes it", () => {
    const resume = memoryResume();
    const onClose = vi.fn();
    render(<VideoOverlay bridge={bridge()} entry={entry} onClose={onClose} resume={resume} />);
    const element = video();

    element.currentTime = 42;
    fireEvent.pause(element);
    expect(resume.saved[entry.relativePath]).toBe(42);

    element.currentTime = 90;
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
    expect(resume.saved[entry.relativePath]).toBe(90);
  });

  it("forgets the position when the video ends", () => {
    const resume = memoryResume({ [entry.relativePath]: 125 });
    render(<VideoOverlay bridge={bridge()} entry={entry} onClose={vi.fn()} resume={resume} />);

    fireEvent.ended(video());

    expect(resume.saved[entry.relativePath]).toBeUndefined();
  });

  it("offers the system player when the webview cannot play the file", () => {
    const desktop = bridge();
    render(<VideoOverlay bridge={desktop} entry={entry} onClose={vi.fn()} resume={memoryResume()} />);

    fireEvent.error(video());

    expect(screen.getByRole("alert")).toHaveTextContent(/can't be played here/i);
    fireEvent.click(screen.getByRole("button", { name: "Open in default player" }));
    expect(desktop.openMedia).toHaveBeenCalledWith(entry.relativePath);
  });

  it("falls back to the system player when built-in playback is unavailable", () => {
    render(<VideoOverlay bridge={bridge({ mediaUrl: undefined })} entry={entry} onClose={vi.fn()} resume={memoryResume()} />);

    expect(screen.queryByTestId("video")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open in default player" })).toBeInTheDocument();
  });

  it("makes the app window follow Video.js full screen, and restores it on close", () => {
    const setFullscreen = vi.fn().mockResolvedValue(undefined);
    let fullscreenElement: Element | null = null;
    Object.defineProperty(document, "fullscreenElement", { configurable: true, get: () => fullscreenElement });
    const { unmount } = render(<VideoOverlay bridge={bridge({ setFullscreen })} entry={entry} onClose={vi.fn()} resume={memoryResume()} />);
    // Only Video.js's own control: no second full-screen button.
    expect(screen.queryByRole("button", { name: /full screen/i })).not.toBeInTheDocument();

    fullscreenElement = screen.getByTestId("skin");
    fireEvent(document, new Event("fullscreenchange"));
    expect(setFullscreen).toHaveBeenLastCalledWith(true);

    fullscreenElement = null;
    fireEvent(document, new Event("fullscreenchange"));
    expect(setFullscreen).toHaveBeenLastCalledWith(false);

    // Something else going full screen does not move the window.
    fullscreenElement = document.body;
    fireEvent(document, new Event("fullscreenchange"));
    expect(setFullscreen).toHaveBeenCalledTimes(2);

    fullscreenElement = screen.getByTestId("skin");
    fireEvent(document, new Event("fullscreenchange"));
    unmount();
    expect(setFullscreen).toHaveBeenLastCalledWith(false);
    fullscreenElement = null;
  });

  it("plays a direct file, or prepares MKV/MOV first with progress, then plays the copy", async () => {
    let emit: ((event: import("../lib/bridge").PlaybackEvent) => void) | undefined;
    const preparePlayback = vi.fn()
      .mockResolvedValueOnce({ kind: "preparing", id: "0123456789abcdef", mode: "transcode" });
    const cancelPlayback = vi.fn().mockResolvedValue(undefined);
    const subscribePlayback = vi.fn(async (listener) => { emit = listener; return () => undefined; });
    const mkv = { ...entry, relativePath: "video/Film.mkv", extension: "mkv" };
    render(<VideoOverlay bridge={bridge({ preparePlayback, cancelPlayback, subscribePlayback })} entry={mkv} onClose={vi.fn()} resume={memoryResume()} />);

    expect(await screen.findByRole("status", { name: "Preparing video" })).toHaveTextContent("Converting for playback…");
    expect(preparePlayback).toHaveBeenCalledWith("video/Film.mkv", { dolby: false });
    act(() => emit?.({ type: "progress", id: "other", percent: 90 }));
    act(() => emit?.({ type: "progress", id: "0123456789abcdef", percent: 42 }));
    expect(screen.getByRole("progressbar", { name: "Preparation progress" })).toHaveAttribute("value", "42");
    expect(screen.getByText(/42% ·/)).toBeInTheDocument();

    act(() => emit?.({ type: "ready", id: "0123456789abcdef", url: "playback/0123456789abcdef.mp4" }));
    expect(screen.getByTestId("video")).toHaveAttribute("src", "qtmedia://localhost/playback%2F0123456789abcdef.mp4");
    expect(cancelPlayback).not.toHaveBeenCalled();
  });

  it("cancels an unfinished preparation when the player closes, and reports failures", async () => {
    let emit: ((event: import("../lib/bridge").PlaybackEvent) => void) | undefined;
    const preparePlayback = vi.fn().mockResolvedValue({ kind: "preparing", id: "fedcba9876543210", mode: "remux" });
    const cancelPlayback = vi.fn().mockResolvedValue(undefined);
    const subscribePlayback = vi.fn(async (listener) => { emit = listener; return () => undefined; });
    const onClose = vi.fn();
    const mov = { ...entry, relativePath: "video/Clip.mov", extension: "mov" };
    const view = render(<VideoOverlay bridge={bridge({ preparePlayback, cancelPlayback, subscribePlayback })} entry={mov} onClose={onClose} resume={memoryResume()} />);
    expect(await screen.findByText("Preparing for playback…")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalled();
    view.unmount();
    expect(cancelPlayback).toHaveBeenCalledWith("fedcba9876543210");

    render(<VideoOverlay bridge={bridge({ preparePlayback, cancelPlayback, subscribePlayback })} entry={mov} onClose={vi.fn()} resume={memoryResume()} />);
    await screen.findByText("Preparing for playback…");
    act(() => emit?.({ type: "error", id: "fedcba9876543210", code: "playback_prepare_failed" }));
    expect(screen.getByText("This video can't be played here.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Open in default player/ })).toBeInTheDocument();
  });

  it("plays MP4 directly when the host says so, and a cached copy without waiting", async () => {
    const preparePlayback = vi.fn().mockResolvedValueOnce({ kind: "direct" });
    const { unmount } = render(<VideoOverlay bridge={bridge({ preparePlayback, subscribePlayback: vi.fn(async () => () => undefined) })} entry={entry} onClose={vi.fn()} resume={memoryResume()} />);
    expect(await screen.findByTestId("video")).toHaveAttribute("src", "qtmedia://localhost/video%2FClip%20%5Bmedia-abc%5D.mp4");
    unmount();
    preparePlayback.mockResolvedValueOnce({ kind: "ready", url: "playback/0123456789abcdef.mp4" });
    render(<VideoOverlay bridge={bridge({ preparePlayback, subscribePlayback: vi.fn(async () => () => undefined) })} entry={{ ...entry, relativePath: "video/Film.mkv" }} onClose={vi.fn()} resume={memoryResume()} />);
    expect(await screen.findByTestId("video")).toHaveAttribute("src", "qtmedia://localhost/playback%2F0123456789abcdef.mp4");
  });

  it("offers a remembered Stable volume switch that routes audio through a compressor", () => {
    const connections: string[] = [];
    const node = (name: string) => ({
      name,
      connect(target: { name: string }) { connections.push(`${name}->${target.name}`); return target; },
      disconnect() { connections.push(`${name}-x`); },
      threshold: { value: 0 }, knee: { value: 0 }, ratio: { value: 0 }, attack: { value: 0 }, release: { value: 0 }, gain: { value: 1 },
    });
    let compressors = 0;
    const created: unknown[] = [];
    class FakeAudioContext {
      state = "running";
      destination = node("speakers");
      constructor() { created.push(this); }
      createMediaElementSource(element: HTMLMediaElement) { return { ...node("video"), mediaElement: element }; }
      createDynamicsCompressor() { compressors += 1; return node(compressors === 1 ? "compressor" : "limiter"); }
      createGain() { return node("makeup"); }
      resume() { return Promise.resolve(); }
      close() { return Promise.resolve(); }
    }
    vi.stubGlobal("AudioContext", FakeAudioContext);
    const { unmount } = render(<VideoOverlay bridge={bridge()} entry={entry} onClose={vi.fn()} resume={memoryResume()} />);
    expect(screen.getByTestId("video")).toHaveAttribute("crossorigin", "anonymous");
    const toggle = screen.getByRole("button", { name: "Stable volume" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    expect(created).toHaveLength(0); // no audio graph until it is turned on

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(created).toHaveLength(1);
    expect(connections).toEqual(expect.arrayContaining(["compressor->makeup", "makeup->limiter", "video->compressor", "limiter->speakers"]));
    expect(localStorage.getItem("qtmedia.video.stableVolume")).toBe("on");

    connections.length = 0;
    fireEvent.click(toggle);
    expect(connections).toContain("video->speakers");
    expect(connections).not.toContain("video->compressor");
    expect(created).toHaveLength(1); // reconnected, not rebuilt
    unmount();

    // The choice is remembered for the next video.
    localStorage.setItem("qtmedia.video.stableVolume", "on");
    render(<VideoOverlay bridge={bridge()} entry={entry} onClose={vi.fn()} resume={memoryResume()} />);
    expect(screen.getByRole("button", { name: "Stable volume" })).toHaveAttribute("aria-pressed", "true");
    vi.unstubAllGlobals();
  });
});

