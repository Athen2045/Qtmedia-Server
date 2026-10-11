import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { WindowControls } from "./components/WindowControls";
import type { DesktopBridge } from "./lib/bridge";

// The real overlay loads Video.js, which jsdom cannot run; App only needs to open and close it.
vi.mock("./components/VideoOverlay", () => ({
  default: ({ entry, onClose }: { entry: { relativePath: string }; onClose: () => void }) => (
    <div role="dialog" aria-label="Video player">{entry.relativePath}<button type="button" onClick={onClose}>Close video</button></div>
  ),
}));


function fakeBridge(): DesktopBridge {
  return {
    inspectLink: vi.fn().mockResolvedValue(undefined),
    startDownload: vi.fn().mockResolvedValue(undefined),
    cancelDownload: vi.fn().mockResolvedValue(undefined),
    listLibrary: vi.fn().mockResolvedValue([]),
    openMedia: vi.fn().mockResolvedValue(undefined),
    openLibrary: vi.fn().mockResolvedValue(undefined),
    readArtwork: vi.fn().mockResolvedValue(null),
    getDownloadLocation: vi.fn().mockResolvedValue({ path: "C:\\Qtmedia\\library", isDefault: true }),
    chooseDownloadLocation: vi.fn().mockResolvedValue(null),
    useDefaultDownloadLocation: vi.fn().mockResolvedValue({ path: "C:\\Qtmedia\\library", isDefault: true }),
    minimizeWindow: vi.fn().mockResolvedValue(undefined),
    toggleMaximizeWindow: vi.fn().mockResolvedValue(undefined),
    closeWindow: vi.fn().mockResolvedValue(undefined),
    subscribe: vi.fn().mockResolvedValue(() => undefined),
  };
}


describe("application shell", () => {
  it("renders five accessible destinations with Home selected", () => {
    render(<App bridge={fakeBridge()} />);

    for (const name of ["Home", "Video", "Music", "Files", "Settings"]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }
    expect(screen.getByRole("button", { name: "Home" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("heading", { name: "Qtmedia" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Media link" })).toBeInTheDocument();
  });

  it("navigates to Files and renders its teaching empty state", async () => {
    render(<App bridge={fakeBridge()} />);

    fireEvent.click(screen.getByRole("button", { name: "Files" }));

    expect(await screen.findByRole("heading", { name: "Files" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "No downloads found" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Go to Home" }));
    expect(screen.getByRole("textbox", { name: "Media link" })).toBeInTheDocument();
  });

  it("does not rescan in response to its own library listing", async () => {
    let listener: ((event: import("./lib/bridge").DesktopEvent) => void) | undefined;
    const bridge = fakeBridge();
    bridge.subscribe = vi.fn(async (next) => { listener = next; return () => undefined; });
    render(<App bridge={bridge} />);
    await act(async () => undefined);
    const before = vi.mocked(bridge.listLibrary).mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Files" }));
    await act(async () => undefined);
    await act(async () => listener?.({ event: "library_changed", entries: [] } as import("./lib/bridge").DesktopEvent));
    expect(bridge.listLibrary).toHaveBeenCalledTimes(before + 1);
    await act(async () => listener?.({ event: "library_changed" }));
    expect(bridge.listLibrary).toHaveBeenCalledTimes(before + 2);
  });

  it("opens the Video library with its built-in player and the Music library", async () => {
    render(<App bridge={fakeBridge()} />);

    fireEvent.click(screen.getByRole("button", { name: "Video" }));
    expect(await screen.findByRole("heading", { name: "Video" })).toBeInTheDocument();
    expect(screen.queryByText("Player coming soon")).not.toBeInTheDocument();
    expect(screen.queryByText("Soon")).not.toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "No videos yet" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Music" }));
    expect(await screen.findByRole("heading", { name: "Music" })).toBeInTheDocument();
    expect(screen.queryByText("Player coming soon")).not.toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "No music yet" })).toBeInTheDocument();
  });

  it("opens an active Settings page for the download location", async () => {
    render(<App bridge={fakeBridge()} />);

    fireEvent.click(screen.getByRole("button", { name: "Settings" }));

    expect(await screen.findByRole("heading", { name: "Download location" })).toBeInTheDocument();
    expect(screen.queryByText("Coming soon")).not.toBeInTheDocument();
  });

  it("keeps active download progress visible after navigating to Files", async () => {
    let listener: ((event: import("./lib/bridge").DesktopEvent) => void) | undefined;
    const bridge = fakeBridge();
    bridge.subscribe = vi.fn(async (next) => {
      listener = next;
      return () => undefined;
    });
    render(<App bridge={bridge} />);
    await act(async () => undefined);

    act(() => listener?.({
      event: "inspection_ready",
      mediaId: "media-1",
      title: "Safe sample",
      site: "YouTube",
      durationSeconds: 60,
      formats: [{ key: "video-720", kind: "video", label: "720p MP4", extension: "mp4", height: 720, bitrateKbps: null }],
    }));
    fireEvent.click(screen.getByRole("button", { name: "Download 720p MP4" }));
    act(() => {
      listener?.({ event: "download_started", jobId: "job-1" });
      listener?.({ event: "download_progress", jobId: "job-1", downloadedBytes: 50, totalBytes: 100, percent: 50 });
    });
    fireEvent.click(screen.getByRole("button", { name: "Files" }));

    expect(screen.getByRole("status", { name: "Active download" })).toHaveTextContent("Safe sample");
    expect(screen.getByRole("status", { name: "Active download" })).toHaveTextContent("50%");
  });

  it("uses custom window controls on Windows and hides them on macOS", () => {
    const bridge = fakeBridge();
    const { rerender } = render(<WindowControls bridge={bridge} platform="windows" />);
    fireEvent.click(screen.getByRole("button", { name: "Minimize" }));
    fireEvent.click(screen.getByRole("button", { name: "Maximize or restore" }));
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(bridge.minimizeWindow).toHaveBeenCalledOnce();
    expect(bridge.toggleMaximizeWindow).toHaveBeenCalledOnce();
    expect(bridge.closeWindow).toHaveBeenCalledOnce();

    rerender(<WindowControls bridge={bridge} platform="macos" />);
    expect(screen.queryByLabelText("Window controls")).not.toBeInTheDocument();
  });
});

describe("built-in video player", () => {
  it("opens a video from the Video page in the overlay and closes it again", async () => {
    const bridge = fakeBridge();
    bridge.listLibrary = vi.fn().mockResolvedValue([{ relativePath: "video/Clip.mp4", mediaType: "video", extension: "mp4", sizeBytes: 10, modifiedAt: 1, durationSeconds: null, artworkPath: null }]);
    render(<App bridge={bridge} />);

    fireEvent.click(screen.getByRole("button", { name: "Video" }));
    fireEvent.click(await screen.findByRole("button", { name: "Play Clip" }));

    expect(await screen.findByRole("dialog", { name: "Video player" })).toHaveTextContent("video/Clip.mp4");
    expect(bridge.openMedia).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Close video" }));
    expect(screen.queryByRole("dialog", { name: "Video player" })).not.toBeInTheDocument();
  });

  it("pauses native music and frees the audio device when a video opens", async () => {
    const bridge = fakeBridge();
    const audio = {
      play: vi.fn(async () => undefined), pause: vi.fn(async () => undefined), resume: vi.fn(async () => undefined),
      seek: vi.fn(async () => undefined), stop: vi.fn(async () => undefined), release: vi.fn(async () => undefined),
      setVolume: vi.fn(async () => undefined), setNext: vi.fn(async () => undefined), devices: vi.fn(async () => []),
      getSettings: vi.fn(async () => ({ deviceId: null, mode: "shared" as const, rateMismatch: "strict" as const, exclusiveVolume: false })),
      setSettings: vi.fn(async (value) => value), subscribe: vi.fn(async () => () => undefined),
    };
    bridge.audio = audio;
    bridge.listLibrary = vi.fn().mockResolvedValue([
      { relativePath: "audio/Song.flac", mediaType: "audio", extension: "flac", sizeBytes: 10, modifiedAt: 2, durationSeconds: 100, artworkPath: null },
      { relativePath: "video/Clip.mp4", mediaType: "video", extension: "mp4", sizeBytes: 10, modifiedAt: 1, durationSeconds: null, artworkPath: null },
    ]);
    render(<App bridge={bridge} />);
    fireEvent.click(screen.getByRole("button", { name: "Music" }));
    fireEvent.click((await screen.findAllByRole("button", { name: "Play Song" }))[0]);
    expect(audio.play).toHaveBeenCalledWith("audio/Song.flac", 0);

    fireEvent.click(screen.getByRole("button", { name: "Video" }));
    fireEvent.click(await screen.findByRole("button", { name: "Play Clip" }));
    expect(await screen.findByRole("dialog", { name: "Video player" })).toBeInTheDocument();
    expect(audio.release).toHaveBeenCalledOnce();
  });
});
