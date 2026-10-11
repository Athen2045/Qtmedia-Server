import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FilesPage } from "./FilesPage";
import type { DesktopBridge, LibraryEntry } from "../lib/bridge";
import { PlayerProvider, usePlayer } from "../lib/player";


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
    fireEvent.click(screen.getByRole("button", { name: "Music" }));
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

    fireEvent.click(screen.getByRole("button", { name: "Sort by Name" }));
    expect(screen.getAllByRole("option").map((item) => item.textContent)).toEqual([
      expect.stringContaining("alpha.mp4"),
      expect.stringContaining("zebra.mp3"),
    ]);
    fireEvent.change(screen.getByRole("textbox", { name: "Search downloaded files" }), { target: { value: "zeb" } });
    expect(screen.getByText("zebra.mp3")).toBeInTheDocument();
    expect(screen.queryByText("alpha.mp4")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open Folder" }));
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

describe("Files selection and delete", () => {
  const library: LibraryEntry[] = [
    { relativePath: "audio/a.mp3", mediaType: "audio", extension: "mp3", sizeBytes: 1024 * 1024, modifiedAt: 30, durationSeconds: null, artworkPath: null },
    { relativePath: "audio/b.mp3", mediaType: "audio", extension: "mp3", sizeBytes: 1024 * 1024, modifiedAt: 20, durationSeconds: null, artworkPath: null },
    { relativePath: "video/c.mp4", mediaType: "video", extension: "mp4", sizeBytes: 2 * 1024 * 1024, modifiedAt: 10, durationSeconds: null, artworkPath: null },
  ];

  function deletable(removed?: string[], failed = 0) {
    const bridge = bridgeWith(library);
    bridge.deleteMedia = vi.fn(async (paths: string[]) => ({ removed: removed ?? paths, failed }));
    return bridge;
  }

  it("selects all visible files and moves them to the Recycle Bin after confirmation", async () => {
    const bridge = deletable();
    render(<FilesPage bridge={bridge} />);
    await screen.findByText("a.mp3");

    fireEvent.click(screen.getByRole("checkbox", { name: "Select all" }));
    expect(screen.getAllByRole("option").every((row) => row.getAttribute("aria-selected") === "true")).toBe(true);
    expect(screen.getByText("3 selected")).toBeInTheDocument();
    expect(screen.getByText(/3 of 3 items selected · 4\.0 MB/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    const sheet = screen.getByRole("alertdialog", { name: "Move 3 items to the Recycle Bin?" });
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
    expect(bridge.deleteMedia).not.toHaveBeenCalled();

    fireEvent.click(within(sheet).getByRole("button", { name: "Move to Recycle Bin" }));
    await waitFor(() => expect(bridge.deleteMedia).toHaveBeenCalledWith(["audio/a.mp3", "audio/b.mp3", "video/c.mp4"]));
    await waitFor(() => expect(bridge.listLibrary).toHaveBeenCalledTimes(2));
  });

  it("supports Ctrl-click, Shift-click ranges, keyboard shortcuts and cancelling", async () => {
    const bridge = deletable();
    render(<FilesPage bridge={bridge} />);
    await screen.findByText("a.mp3");
    const [first, second, third] = screen.getAllByRole("option");

    fireEvent.click(first);
    fireEvent.click(third, { shiftKey: true });
    expect([first, second, third].map((row) => row.getAttribute("aria-selected"))).toEqual(["true", "true", "true"]);
    fireEvent.click(second, { ctrlKey: true });
    expect(second).toHaveAttribute("aria-selected", "false");
    expect(screen.getByRole("checkbox", { name: "Select all" })).toHaveProperty("indeterminate", true);

    fireEvent.keyDown(first, { key: "Escape" });
    expect(screen.queryByText(/selected/)).not.toBeInTheDocument();
    fireEvent.keyDown(first, { key: "a", ctrlKey: true });
    expect(screen.getByText("3 selected")).toBeInTheDocument();

    fireEvent.keyDown(first, { key: "Delete" });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(bridge.deleteMedia).not.toHaveBeenCalled();
  });

  it("names a single file and reports items that could not be removed", async () => {
    const bridge = deletable([], 1);
    render(<FilesPage bridge={bridge} />);
    fireEvent.click(await screen.findByRole("checkbox", { name: "Select b.mp3" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    fireEvent.click(screen.getByRole("button", { name: "Move to Recycle Bin" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("1 item couldn’t be moved to the Recycle Bin.");
    expect(bridge.deleteMedia).toHaveBeenCalledWith(["audio/b.mp3"]);
  });

  it("hides Delete when the bridge cannot remove files", async () => {
    render(<FilesPage bridge={bridgeWith(library)} />);
    fireEvent.click(await screen.findByRole("checkbox", { name: "Select a.mp3" }));
    expect(screen.getByText("1 selected")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
  });

  it("stops playback when the playing song is deleted", async () => {
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
    const bridge = deletable();
    bridge.mediaUrl = (path: string) => `qtmedia://localhost/${encodeURIComponent(path)}`;
    let api: ReturnType<typeof usePlayer> | undefined;
    function Probe() { api = usePlayer(); return null; }
    render(<PlayerProvider bridge={bridge}><Probe /><FilesPage bridge={bridge} /></PlayerProvider>);
    fireEvent.click(await screen.findByRole("button", { name: "Play a.mp3" }));
    expect(api?.current?.relativePath).toBe("audio/a.mp3");

    fireEvent.click(screen.getByRole("checkbox", { name: "Select a.mp3" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    fireEvent.click(screen.getByRole("button", { name: "Move to Recycle Bin" }));
    await waitFor(() => expect(api?.current).toBeNull());
    vi.restoreAllMocks();
  });

  it("imports picked music and videos, reports skipped files, and refreshes", async () => {
    const bridge = bridgeWith([]);
    bridge.importMedia = vi.fn()
      .mockResolvedValueOnce({ imported: ["video/Film.mkv", "audio/Song.flac"], skipped: 1 })
      .mockResolvedValueOnce(null);
    render(<FilesPage bridge={bridge} />);
    await waitFor(() => expect(bridge.listLibrary).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "Import" }));
    expect(await screen.findByText(/Imported 2 files\. 1 file skipped/)).toBeInTheDocument();
    await waitFor(() => expect(bridge.listLibrary).toHaveBeenCalledTimes(2));

    // Cancelling the picker changes nothing.
    fireEvent.click(screen.getByRole("button", { name: "Import" }));
    await waitFor(() => expect(bridge.importMedia).toHaveBeenCalledTimes(2));
    expect(bridge.listLibrary).toHaveBeenCalledTimes(2);
  });

  it("hides Import where the host can't pick files", async () => {
    render(<FilesPage bridge={bridgeWith([])} />);
    await screen.findByRole("button", { name: /Open Folder/ });
    expect(screen.queryByRole("button", { name: "Import" })).not.toBeInTheDocument();
  });
});
