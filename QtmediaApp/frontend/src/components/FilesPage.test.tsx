import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FilesPage } from "./FilesPage";
import type { DesktopBridge, LibraryEntry } from "../lib/bridge";


function bridgeWith(entries: LibraryEntry[]): DesktopBridge {
  return {
    inspectLink: vi.fn().mockResolvedValue(undefined),
    startDownload: vi.fn().mockResolvedValue(undefined),
    cancelDownload: vi.fn().mockResolvedValue(undefined),
    listLibrary: vi.fn().mockResolvedValue(entries),
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


describe("Files library", () => {
  it("filters local entries and opens only their relative path", async () => {
    const entries: LibraryEntry[] = [
      {
        relativePath: "audio/song.mp3",
        mediaType: "audio",
        extension: "mp3",
        sizeBytes: 2048,
        modifiedAt: 10,
        durationSeconds: null,
        artworkPath: null,
      },
      {
        relativePath: "video/clip.mp4",
        mediaType: "video",
        extension: "mp4",
        sizeBytes: 4096,
        modifiedAt: 20,
        durationSeconds: null,
        artworkPath: null,
      },
    ];
    const bridge = bridgeWith(entries);
    render(<FilesPage bridge={bridge} />);

    expect(await screen.findByText("clip.mp4")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Audio" }));
    expect(screen.getByText("song.mp3")).toBeInTheDocument();
    expect(screen.queryByText("clip.mp4")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open song.mp3" }));
    expect(bridge.openMedia).toHaveBeenCalledWith("audio/song.mp3");
  });

  it("searches, sorts by local name, and opens the library folder", async () => {
    const bridge = bridgeWith([
      { relativePath: "audio/zebra.mp3", mediaType: "audio", extension: "mp3", sizeBytes: 50, modifiedAt: 1, durationSeconds: null, artworkPath: null },
      { relativePath: "video/alpha.mp4", mediaType: "video", extension: "mp4", sizeBytes: 100, modifiedAt: 2, durationSeconds: null, artworkPath: null },
    ]);
    render(<FilesPage bridge={bridge} />);
    expect(await screen.findByText("zebra.mp3")).toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox", { name: "Sort library" }), { target: { value: "name" } });
    expect(screen.getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      expect.stringContaining("alpha.mp4"),
      expect.stringContaining("zebra.mp3"),
    ]);
    fireEvent.change(screen.getByRole("textbox", { name: "Search downloaded files" }), { target: { value: "zeb" } });
    expect(screen.getByText("zebra.mp3")).toBeInTheDocument();
    expect(screen.queryByText("alpha.mp4")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open library folder" }));
    expect(bridge.openLibrary).toHaveBeenCalledOnce();
  });

  it("loads indexed artwork through the confined desktop bridge", async () => {
    const bridge = bridgeWith([
      { relativePath: "audio/song.mp3", mediaType: "audio", extension: "mp3", sizeBytes: 50, modifiedAt: 1, durationSeconds: 120, artworkPath: "artwork/song.jpg" },
    ]);
    bridge.readArtwork = vi.fn().mockResolvedValue("data:image/jpeg;base64,aW1hZ2U=");
    render(<FilesPage bridge={bridge} />);
    expect(await screen.findByRole("img", { name: "Artwork for song.mp3" })).toHaveAttribute("src", "data:image/jpeg;base64,aW1hZ2U=");
    expect(bridge.readArtwork).toHaveBeenCalledWith("artwork/song.jpg");
  });

  it("distinguishes no search matches from an empty library and clears filters", async () => {
    const bridge = bridgeWith([
      { relativePath: "video/clip.mp4", mediaType: "video", extension: "mp4", sizeBytes: 100, modifiedAt: 2, durationSeconds: null, artworkPath: null },
    ]);
    render(<FilesPage bridge={bridge} />);
    await screen.findByText("clip.mp4");
    fireEvent.change(screen.getByRole("textbox", { name: "Search downloaded files" }), { target: { value: "missing" } });

    expect(screen.getByRole("heading", { name: "No files match." })).toBeInTheDocument();
    expect(screen.queryByText("No downloads found")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(screen.getByText("clip.mp4")).toBeInTheDocument();
  });

  it("shows a retry action after a library read failure", async () => {
    const bridge = bridgeWith([]);
    bridge.listLibrary = vi.fn()
      .mockRejectedValueOnce("storage_unavailable")
      .mockResolvedValueOnce([{ relativePath: "audio/recovered.mp3", mediaType: "audio", extension: "mp3", sizeBytes: 100, modifiedAt: 2, durationSeconds: null, artworkPath: null }]);
    render(<FilesPage bridge={bridge} />);

    expect(await screen.findByRole("heading", { name: "Library unavailable." })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("recovered.mp3")).toBeInTheDocument();
  });

  it("reloads the selected library when the session revision changes", async () => {
    const bridge = bridgeWith([]);
    bridge.listLibrary = vi.fn()
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([{ relativePath: "video/new.mp4", mediaType: "video", extension: "mp4", sizeBytes: 100, modifiedAt: 2, durationSeconds: null, artworkPath: null }]);
    const view = render(<FilesPage bridge={bridge} refreshToken={0} />);
    await screen.findByText("No downloads found");
    view.rerender(<FilesPage bridge={bridge} refreshToken={1} />);
    expect(await screen.findByText("new.mp4")).toBeInTheDocument();
  });
});
