import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { WindowControls } from "./components/WindowControls";
import type { DesktopBridge } from "./lib/bridge";


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
    expect(screen.getByRole("heading", { name: "QT MEDIA" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Media link" })).toBeInTheDocument();
  });

  it("navigates to Files and renders its teaching empty state", async () => {
    render(<App bridge={fakeBridge()} />);

    fireEvent.click(screen.getByRole("button", { name: "Files" }));

    expect(await screen.findByRole("heading", { name: "Your library" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "No downloads found" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Go to Home" }));
    expect(screen.getByRole("textbox", { name: "Media link" })).toBeInTheDocument();
  });

  it("does not rescan in response to its own library listing", async () => {
    let listener: ((event: import("./lib/bridge").DesktopEvent) => void) | undefined;
    const bridge = fakeBridge();
    bridge.subscribe = vi.fn(async (next) => { listener = next; return () => undefined; });
    render(<App bridge={bridge} />);
    fireEvent.click(screen.getByRole("button", { name: "Files" }));
    await act(async () => undefined);
    await act(async () => listener?.({ event: "library_changed", entries: [] } as import("./lib/bridge").DesktopEvent));
    expect(bridge.listLibrary).toHaveBeenCalledTimes(1);
    await act(async () => listener?.({ event: "library_changed" }));
    expect(bridge.listLibrary).toHaveBeenCalledTimes(2);
  });

  it("renders honest coming-soon states", () => {
    render(<App bridge={fakeBridge()} />);

    fireEvent.click(screen.getByRole("button", { name: "Video" }));

    expect(screen.getByRole("heading", { name: "Video player" })).toBeInTheDocument();
    expect(screen.getByText("Coming next")).toBeInTheDocument();
  });

  it("opens an active Settings page for the download location", async () => {
    render(<App bridge={fakeBridge()} />);

    fireEvent.click(screen.getByRole("button", { name: "Settings" }));

    expect(await screen.findByRole("heading", { name: "Download location" })).toBeInTheDocument();
    expect(screen.queryByText("Coming next")).not.toBeInTheDocument();
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
