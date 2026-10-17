import { act, fireEvent, render, screen } from "@testing-library/react";
import { forwardRef } from "react";
import { describe, expect, it, vi } from "vitest";

import type { DesktopBridge, LibraryEntry } from "../lib/bridge";
import type { ResumeStore } from "../lib/resume";
import VideoOverlay, { type VideoNavigation } from "./VideoOverlay";

// jsdom cannot run Video.js; the overlay only relies on the native <video> it
// renders, and the bar's Video.js parts are stood in for by plain elements.
vi.mock("@videojs/react/video", () => ({
  VideoPlayer: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  Video: forwardRef<HTMLVideoElement, React.VideoHTMLAttributes<HTMLVideoElement>>((props, ref) => <video ref={ref} data-testid="video" {...props} />),
}));
vi.mock("@videojs/react", () => {
  type Part = { children?: React.ReactNode; className?: string; render?: (props: object, state: object) => React.ReactNode };
  const part = ({ children, className }: Part) => <div className={className}>{children}</div>;
  const button = (state: object) => ({ render }: Part) => <>{render?.({ type: "button" }, state)}</>;
  const slider = { Root: part, Track: part, Fill: part, Buffer: part, Thumb: part, Preview: part, Value: () => null };
  return {
    Container: ({ children }: Part) => <div data-testid="skin">{children}</div>,
    Controls: { Root: ({ children }: Part) => <>{children}</>, Backdrop: () => null, Content: part, Group: part },
    SeekButton: ({ seconds, children, ...props }: { seconds: number; children?: React.ReactNode } & React.ButtonHTMLAttributes<HTMLButtonElement>) => <button type="button" data-seconds={seconds} {...props}>{children}</button>,
    PlayButton: button({ paused: true }),
    MuteButton: button({ muted: false }),
    FullscreenButton: button({ fullscreen: false }),
    VolumeSlider: slider,
    TimeSlider: slider,
    Time: { Group: part, Value: () => null, Separator: part },
    Hotkey: () => null,
    Gesture: () => null,
  };
});

/** Opens the bar's settings menu, and a page of it when named. */
function openSettings(page?: "Subtitles" | "Speed") {
  fireEvent.click(screen.getByRole("button", { name: "Settings" }));
  if (page) fireEvent.click(screen.getByRole("menuitem", { name: new RegExp(`^${page}`) }));
}

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
    list: () => Object.entries(saved).map(([relativePath, position]) => ({ relativePath, position, savedAt: 0 })),
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
    // One full-screen control, in the bar.
    expect(screen.getAllByRole("button", { name: /full screen/i })).toHaveLength(1);

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
    openSettings();
    const toggle = screen.getByRole("menuitemcheckbox", { name: "Stable volume" });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(created).toHaveLength(0); // no audio graph until it is turned on

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-checked", "true");
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
    openSettings();
    expect(screen.getByRole("menuitemcheckbox", { name: "Stable volume" })).toHaveAttribute("aria-checked", "true");
    vi.unstubAllGlobals();
  });

  it("keeps settings in one menu: speed, and Esc closes only the menu", () => {
    const onClose = vi.fn();
    render(<VideoOverlay bridge={bridge()} entry={entry} onClose={onClose} resume={memoryResume()} />);
    const element = video();
    // No chips in the title row any more.
    expect(screen.queryByRole("button", { name: /Stable volume|Autoplay|Add subtitles/ })).not.toBeInTheDocument();

    openSettings("Speed");
    fireEvent.click(screen.getByRole("menuitemradio", { name: "1.5×" }));
    expect(element.playbackRate).toBe(1.5);
    fireEvent(element, new Event("ratechange"));
    expect(screen.getByRole("menuitem", { name: /^Speed/ })).toHaveTextContent("1.5×");

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("lets the resume note fade away by itself", () => {
    vi.useFakeTimers();
    try {
      render(<VideoOverlay bridge={bridge()} entry={entry} onClose={vi.fn()} resume={memoryResume({ [entry.relativePath]: 125 })} />);
      fireEvent.loadedMetadata(video());
      expect(screen.getByText(/Resumed at 2:05/)).toBeInTheDocument();
      act(() => { vi.advanceTimersByTime(6000); });
      expect(screen.queryByText(/Resumed at/)).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });
});


describe("VideoOverlay next and previous", () => {
  const second: LibraryEntry = { ...entry, relativePath: "video/Second.mp4" };
  const third: LibraryEntry = { ...entry, relativePath: "video/Third.mp4" };
  const nav = (overrides: Partial<VideoNavigation> = {}): VideoNavigation => ({
    previous: entry, next: third, onPrevious: vi.fn(), onNext: vi.fn(), ...overrides,
  });

  it("shows no video navigation for a single video", () => {
    render(<VideoOverlay bridge={bridge()} entry={entry} onClose={vi.fn()} resume={memoryResume()} />);
    expect(screen.queryByRole("button", { name: "Next video" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Previous video" })).not.toBeInTheDocument();
  });

  it("names the neighbours and disables the end of the list", () => {
    render(<VideoOverlay bridge={bridge()} entry={second} navigation={nav({ next: null })} onClose={vi.fn()} resume={memoryResume()} />);
    expect(screen.getByRole("button", { name: "Previous video" })).toHaveAttribute("title", "Previous: Clip (Shift+P)");
    expect(screen.getByRole("button", { name: "Next video" })).toBeDisabled();
  });

  it("saves the position before moving on, by button and by Shift+N / Shift+P", () => {
    const resume = memoryResume();
    const navigation = nav();
    render(<VideoOverlay bridge={bridge()} entry={second} navigation={navigation} onClose={vi.fn()} resume={resume} />);
    const element = video();
    element.currentTime = 77;

    fireEvent.click(screen.getByRole("button", { name: "Next video" }));
    expect(resume.saved[second.relativePath]).toBe(77);
    expect(navigation.onNext).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(window, { key: "N", code: "KeyN", shiftKey: true });
    fireEvent.keyDown(window, { key: "P", code: "KeyP", shiftKey: true });
    fireEvent.keyDown(window, { key: "n", code: "KeyN" });
    expect(navigation.onNext).toHaveBeenCalledTimes(2);
    expect(navigation.onPrevious).toHaveBeenCalledTimes(1);
  });

  it("keeps the same player when the video changes and never saves the old position under the new path", () => {
    const resume = memoryResume({ [third.relativePath]: 30 });
    const { rerender } = render(<VideoOverlay bridge={bridge()} entry={second} navigation={nav()} onClose={vi.fn()} resume={resume} />);
    const element = video();
    element.currentTime = 200;

    rerender(<VideoOverlay bridge={bridge()} entry={third} navigation={nav({ previous: second, next: null })} onClose={vi.fn()} resume={resume} />);

    expect(screen.getByTestId("video")).toBe(element);
    expect(element).toHaveAttribute("src", "qtmedia://localhost/video%2FThird.mp4");
    expect(screen.getByRole("dialog", { name: "Playing Third" })).toBeInTheDocument();
    // The old video's pause and end arrive after the switch.
    fireEvent.pause(element);
    fireEvent.ended(element);
    expect(resume.saved[third.relativePath]).toBe(30);
    // The new video resumes from its own position.
    fireEvent.loadedMetadata(element);
    expect(element.currentTime).toBe(30);
  });

  it("answers the media keys while open and lets them go on close", () => {
    const handlers = new Map<string, (() => void) | null>();
    const session = { metadata: null, setActionHandler: (action: string, handler: (() => void) | null) => { handlers.set(action, handler); } };
    Object.defineProperty(navigator, "mediaSession", { configurable: true, value: session });
    const navigation = nav();
    const { unmount } = render(<VideoOverlay bridge={bridge()} entry={second} navigation={navigation} onClose={vi.fn()} resume={memoryResume()} />);

    handlers.get("nexttrack")?.();
    expect(navigation.onNext).toHaveBeenCalledTimes(1);
    unmount();
    expect(handlers.get("nexttrack")).toBeNull();
    Reflect.deleteProperty(navigator, "mediaSession");
  });
});

describe("VideoOverlay autoplay and volume", () => {
  const second: LibraryEntry = { ...entry, relativePath: "video/Second.mp4" };
  const third: LibraryEntry = { ...entry, relativePath: "video/Third.mp4" };
  const nav = (overrides: Partial<VideoNavigation> = {}): VideoNavigation => ({
    previous: entry, next: third, onPrevious: vi.fn(), onNext: vi.fn(), ...overrides,
  });

  it("counts down to the next video when one ends, and Escape cancels", () => {
    vi.useFakeTimers();
    try {
      const navigation = nav();
      const onClose = vi.fn();
      render(<VideoOverlay bridge={bridge()} entry={second} navigation={navigation} onClose={onClose} resume={memoryResume()} />);
      fireEvent.ended(video());
      expect(screen.getByRole("status", { name: "Up next" })).toHaveTextContent("Up next in 5Third");

      fireEvent.keyDown(window, { key: "Escape" });
      expect(screen.queryByRole("status", { name: "Up next" })).not.toBeInTheDocument();
      expect(onClose).not.toHaveBeenCalled();

      fireEvent.ended(video());
      for (let second = 0; second < 4; second += 1) act(() => { vi.advanceTimersByTime(1000); });
      expect(screen.getByRole("status", { name: "Up next" })).toHaveTextContent("Up next in 1");
      expect(navigation.onNext).not.toHaveBeenCalled();
      act(() => { vi.advanceTimersByTime(1000); });
      expect(navigation.onNext).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("can turn autoplay off, and remembers it", () => {
    const navigation = nav();
    const view = render(<VideoOverlay bridge={bridge()} entry={second} navigation={navigation} onClose={vi.fn()} resume={memoryResume()} />);
    openSettings();
    fireEvent.click(screen.getByRole("menuitemcheckbox", { name: "Autoplay next" }));
    expect(screen.getByRole("menuitemcheckbox", { name: "Autoplay next" })).toHaveAttribute("aria-checked", "false");
    fireEvent.ended(video());
    expect(screen.queryByRole("status", { name: "Up next" })).not.toBeInTheDocument();
    view.unmount();

    render(<VideoOverlay bridge={bridge()} entry={second} navigation={navigation} onClose={vi.fn()} resume={memoryResume()} />);
    openSettings();
    expect(screen.getByRole("menuitemcheckbox", { name: "Autoplay next" })).toHaveAttribute("aria-checked", "false");
  });

  it("has no autoplay at the end of the list", () => {
    render(<VideoOverlay bridge={bridge()} entry={third} navigation={nav({ next: null })} onClose={vi.fn()} resume={memoryResume()} />);
    fireEvent.ended(video());
    expect(screen.queryByRole("status", { name: "Up next" })).not.toBeInTheDocument();
  });

  it("keeps the volume and mute across videos", () => {
    const view = render(<VideoOverlay bridge={bridge()} entry={entry} onClose={vi.fn()} resume={memoryResume()} />);
    const first = screen.getByTestId("video") as HTMLVideoElement;
    first.volume = 0.35;
    first.muted = true;
    fireEvent(first, new Event("volumechange"));
    view.unmount();

    render(<VideoOverlay bridge={bridge()} entry={second} onClose={vi.fn()} resume={memoryResume()} />);
    const next = screen.getByTestId("video") as HTMLVideoElement;
    expect(next.volume).toBeCloseTo(0.35);
    expect(next.muted).toBe(true);
  });
});

describe("VideoOverlay subtitles", () => {
  const subtitles = {
    tracks: [
      { id: "file:Clip.en.srt", label: null, language: "en", url: "subtitles/0123456789abcdef.vtt" },
      { id: "stream:3", label: "Commentary", language: "fre", url: "subtitles/fedcba9876543210.vtt" },
    ],
    unsupported: 0,
  };

  /** jsdom has no TextTrack support: give the video a small fake list. */
  function fakeTextTracks(element: HTMLVideoElement) {
    const target = new EventTarget();
    const tracks = [...element.querySelectorAll("track")].map((node) => ({ id: node.id, kind: node.getAttribute("kind"), mode: "disabled" }));
    const list = Object.assign(target, tracks, { length: tracks.length, [Symbol.iterator]: () => tracks[Symbol.iterator]() });
    Object.defineProperty(element, "textTracks", { configurable: true, value: list });
    return { list, tracks };
  }

  it("adds a track per subtitle, served over qtmedia://, named by language", async () => {
    render(<VideoOverlay bridge={bridge({ readSubtitles: vi.fn(async () => subtitles) })} entry={entry} onClose={vi.fn()} resume={memoryResume()} />);
    await act(async () => undefined);
    const tracks = [...screen.getByTestId("video").querySelectorAll("track")];
    expect(tracks.map((node) => [node.getAttribute("label"), node.getAttribute("srclang"), node.getAttribute("src")])).toEqual([
      ["English", "en", "qtmedia://localhost/subtitles%2F0123456789abcdef.vtt"],
      ["French · Commentary", "fr", "qtmedia://localhost/subtitles%2Ffedcba9876543210.vtt"],
    ]);
  });

  it("shows the remembered language and remembers a new pick", async () => {
    localStorage.setItem("qtmedia.video.subtitles", JSON.stringify({ enabled: true, language: "fr" }));
    // Render once to get the <track>s, then give the element a text track list.
    const readSubtitles = vi.fn(async () => subtitles);
    const view = render(<VideoOverlay bridge={bridge({ readSubtitles })} entry={entry} onClose={vi.fn()} resume={memoryResume()} />);
    await act(async () => undefined);
    const element = screen.getByTestId("video") as HTMLVideoElement;
    const { list, tracks } = fakeTextTracks(element);
    // A new video makes the overlay apply the choice to the (fake) list.
    view.rerender(<VideoOverlay bridge={bridge({ readSubtitles })} entry={{ ...entry, relativePath: "video/Other.mp4" }} onClose={vi.fn()} resume={memoryResume()} />);
    await act(async () => undefined);
    expect(tracks.map((item) => item.mode)).toEqual(["disabled", "showing"]);

    // The webview switching a second track on by itself is undone.
    tracks[0].mode = "showing";
    list.dispatchEvent(new Event("change"));
    expect(tracks.map((item) => item.mode)).toEqual(["disabled", "showing"]);

    // The viewer turns subtitles off with the player's CC button.
    tracks[1].mode = "disabled";
    list.dispatchEvent(new Event("change"));
    expect(JSON.parse(localStorage.getItem("qtmedia.video.subtitles")!)).toEqual({ enabled: false });
  });

  it("explains picture subtitles and adds subtitle files", async () => {
    const addSubtitles = vi.fn(async () => 1);
    const readSubtitles = vi.fn(async () => ({ tracks: [], unsupported: 1 }));
    render(<VideoOverlay bridge={bridge({ readSubtitles, addSubtitles })} entry={entry} onClose={vi.fn()} resume={memoryResume()} />);
    await act(async () => undefined);
    openSettings("Subtitles");
    expect(screen.getByRole("note")).toHaveTextContent("subtitles are pictures");

    fireEvent.click(screen.getByRole("menuitem", { name: /Add subtitle file/ }));
    await act(async () => undefined);
    expect(addSubtitles).toHaveBeenCalledWith(entry.relativePath);
    expect(screen.getByRole("status")).toHaveTextContent("Subtitles added.");
    expect(readSubtitles).toHaveBeenCalledTimes(2);
    expect(JSON.parse(localStorage.getItem("qtmedia.video.subtitles")!)).toEqual({ enabled: true });
  });

  it("switches subtitles with the CC button and the settings menu", async () => {
    localStorage.setItem("qtmedia.video.subtitles", JSON.stringify({ enabled: false }));
    const readSubtitles = vi.fn(async () => subtitles);
    const view = render(<VideoOverlay bridge={bridge({ readSubtitles })} entry={entry} onClose={vi.fn()} resume={memoryResume()} />);
    await act(async () => undefined);
    const { list, tracks } = fakeTextTracks(screen.getByTestId("video") as HTMLVideoElement);
    view.rerender(<VideoOverlay bridge={bridge({ readSubtitles })} entry={{ ...entry, relativePath: "video/Other.mp4" }} onClose={vi.fn()} resume={memoryResume()} />);
    await act(async () => undefined);
    const cc = screen.getByRole("button", { name: "Subtitles" });
    expect(cc).toHaveAttribute("aria-pressed", "false");

    // CC turns the first track on, and off again.
    fireEvent.click(cc);
    act(() => { list.dispatchEvent(new Event("change")); });
    expect(tracks.map((item) => item.mode)).toEqual(["showing", "disabled"]);
    expect(cc).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(cc);
    act(() => { list.dispatchEvent(new Event("change")); });
    expect(tracks.map((item) => item.mode)).toEqual(["disabled", "disabled"]);

    // The Subtitles page picks a specific track.
    openSettings("Subtitles");
    expect(screen.getByRole("menuitemradio", { name: "Off" })).toHaveAttribute("aria-checked", "true");
    fireEvent.click(screen.getByRole("menuitemradio", { name: "French · Commentary" }));
    act(() => { list.dispatchEvent(new Event("change")); });
    expect(tracks.map((item) => item.mode)).toEqual(["disabled", "showing"]);
    expect(screen.getByRole("menuitemradio", { name: "French · Commentary" })).toHaveAttribute("aria-checked", "true");
  });
});
