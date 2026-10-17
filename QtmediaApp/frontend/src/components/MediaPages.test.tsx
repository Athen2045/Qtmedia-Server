import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DesktopBridge, LibraryEntry } from "../lib/bridge";
import { dominantColor, hashColor, readable } from "../lib/coverColor";
import { PlayerProvider, usePlayer, usePlayerPosition } from "../lib/player";
import { playlistStore } from "../lib/playlists";
import { MusicPage, VideoPage } from "./MediaPages";
import { NowPlaying, PlayerBar } from "./Player";

const entry = (relativePath: string, modifiedAt: number, durationSeconds: number | null = 61): LibraryEntry => ({
  relativePath,
  mediaType: relativePath.startsWith("audio/") ? "audio" : "video",
  extension: relativePath.split(".").at(-1) ?? "",
  sizeBytes: 2 * 1024 * 1024,
  modifiedAt,
  durationSeconds,
  artworkPath: null,
});

function bridgeWith(entries: LibraryEntry[] | Error, playable = true): DesktopBridge {
  return {
    inspectLink: vi.fn(), startDownload: vi.fn(), cancelDownload: vi.fn(),
    listLibrary: entries instanceof Error ? vi.fn().mockRejectedValue(entries) : vi.fn().mockResolvedValue(entries),
    openMedia: vi.fn().mockResolvedValue(undefined), openLibrary: vi.fn(), readArtwork: vi.fn().mockResolvedValue(null),
    getDownloadLocation: vi.fn(), chooseDownloadLocation: vi.fn(), useDefaultDownloadLocation: vi.fn(),
    minimizeWindow: vi.fn(), toggleMaximizeWindow: vi.fn(), closeWindow: vi.fn(),
    subscribe: vi.fn().mockResolvedValue(() => undefined),
    ...(playable ? { mediaUrl: (path: string) => `qtmedia://localhost/${encodeURIComponent(path)}` } : {}),
  };
}

const library = [
  entry("video/Older Clip.mp4", 10),
  entry("audio/Song A.mp3", 30),
  entry("video/Newest Clip.mp4", 40, 3725),
  entry("audio/Song B.mp3", 20),
  entry("audio/Song C.mp3", 5),
];

beforeEach(() => {
  localStorage.clear();
  playlistStore.reset();
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
});
afterEach(() => vi.restoreAllMocks());

describe("Video page", () => {
  it("shows how much of each started video was watched, each video once", async () => {
    localStorage.setItem("qtmedia.resume.v1", JSON.stringify({
      "video/Newest Clip.mp4": { t: 1862.5, at: 5 },
      "video/Deleted.mp4": { t: 40, at: 12 },
    }));
    render(<VideoPage bridge={bridgeWith(library)} onPlayVideo={vi.fn()} />);

    const grid = await screen.findByRole("list", { name: "All videos" });
    expect(within(grid).getAllByRole("button", { name: /^Play / })).toHaveLength(2);
    expect(screen.getAllByRole("button", { name: "Play Newest Clip" })).toHaveLength(1);
    // Newest Clip lasts 3725 s: 1862.5 s is half way; Older Clip was never started.
    expect(within(grid).getAllByRole("progressbar")).toHaveLength(1);
    expect(within(grid).getByRole("progressbar", { name: "Watched 50%" })).toBeInTheDocument();
  });

  it("lists only videos, newest first, and plays through the system player", async () => {
    const bridge = bridgeWith(library);
    render(<VideoPage bridge={bridge} />);

    const buttons = await screen.findAllByRole("button", { name: /^Play / });
    expect(buttons.map((button) => button.getAttribute("aria-label"))).toEqual(["Play Newest Clip", "Play Older Clip"]);
    expect(screen.getByText("1:02:05")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Play Older Clip" }));
    expect(bridge.openMedia).toHaveBeenCalledWith("video/Older Clip.mp4");
  });

  it("opens videos in the built-in player when one is provided", async () => {
    const bridge = bridgeWith(library);
    const onPlayVideo = vi.fn();
    render(<VideoPage bridge={bridge} onPlayVideo={onPlayVideo} />);

    fireEvent.click(await screen.findByRole("button", { name: "Play Older Clip" }));

    expect(onPlayVideo).toHaveBeenCalledWith(expect.objectContaining({ relativePath: "video/Older Clip.mp4" }), expect.any(Array));
    // Next/previous follow the grid: the list is the videos in the order shown.
    const [, list] = onPlayVideo.mock.calls[0] as [LibraryEntry, LibraryEntry[]];
    expect(list.map((item) => item.relativePath)).toEqual([...screen.getAllByRole("button", { name: /^Play / })].map((button) => `video/${button.getAttribute("aria-label")!.slice(5)}.mp4`));
    expect(bridge.openMedia).not.toHaveBeenCalled();
    expect(screen.queryByText("Player coming soon")).not.toBeInTheDocument();
  });

  it("offers a retry when the library cannot be read", async () => {
    const bridge = bridgeWith(new Error("unreadable"));
    render(<VideoPage bridge={bridge} />);
    fireEvent.click(await screen.findByRole("button", { name: "Retry" }));
    await waitFor(() => expect(bridge.listLibrary).toHaveBeenCalledTimes(2));
  });
});

function MusicHarness({ bridge }: { bridge: DesktopBridge }) {
  return <PlayerProvider bridge={bridge}><MusicPage bridge={bridge} /><PlayerBar bridge={bridge} /><NowPlaying bridge={bridge} /></PlayerProvider>;
}

describe("Music page and player", () => {
  it("plays a song from the library through the confined media URL", async () => {
    const bridge = bridgeWith(library);
    render(<MusicHarness bridge={bridge} />);

    const songs = await screen.findByRole("list", { name: "Songs" });
    expect(within(songs).getAllByRole("listitem").map((row) => row.textContent)).toEqual([
      expect.stringContaining("Song A"), expect.stringContaining("Song B"), expect.stringContaining("Song C"),
    ]);
    expect(screen.getByText("Nothing playing")).toBeInTheDocument();

    fireEvent.click(within(songs).getByRole("button", { name: "Play Song B" }));
    const bar = screen.getByRole("contentinfo", { name: "Music player" });
    expect(within(bar).getByText("Song B")).toBeInTheDocument();
    expect(within(bar).getByRole("button", { name: "Pause" })).toBeEnabled();
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalled();

    fireEvent.click(within(bar).getByRole("button", { name: "Next" }));
    expect(within(bar).getByText("Song C")).toBeInTheDocument();
  });

  it("opens Now Playing with up next, tinted from the cover, and closes on Escape", async () => {
    const bridge = bridgeWith(library);
    render(<MusicHarness bridge={bridge} />);
    const songs = await screen.findByRole("list", { name: "Songs" });
    fireEvent.click(within(songs).getByRole("button", { name: "Play Song A" }));
    fireEvent.click(screen.getAllByRole("button", { name: "Open Now Playing" })[0]);

    const dialog = screen.getByRole("dialog", { name: "Now playing: Song A" });
    expect(dialog.style.getPropertyValue("--np-tint")).toMatch(/^rgba\(/);
    // No lyrics for this song (network is disabled in tests), so Up Next shows.
    const queue = await within(dialog).findByRole("region", { name: "Up next" });
    expect(within(queue).getAllByRole("button").map((button) => button.textContent)).toEqual([
      expect.stringContaining("Song A"), expect.stringContaining("Song B"), expect.stringContaining("Song C"),
    ]);
    fireEvent.click(within(queue).getByRole("button", { name: /Song C/ }));
    expect(screen.getByRole("dialog", { name: "Now playing: Song C" })).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens on synced lyrics when the song has a .lrc file, and toggles to Up Next", async () => {
    const bridge = bridgeWith(library);
    const lrc = ["[00:00.00] Hello there", "[00:30.00] Later line"].join(String.fromCharCode(10));
    bridge.readLyrics = vi.fn(async (path: string) => (path === "audio/Song A.mp3" ? lrc : null));
    render(<MusicHarness bridge={bridge} />);
    const songs = await screen.findByRole("list", { name: "Songs" });
    fireEvent.click(within(songs).getByRole("button", { name: "Play Song A" }));
    fireEvent.click(screen.getAllByRole("button", { name: "Open Now Playing" })[0]);

    const dialog = screen.getByRole("dialog", { name: "Now playing: Song A" });
    expect(await within(dialog).findByRole("button", { name: "Hello there" })).toHaveAttribute("aria-current", "true");
    expect(within(dialog).queryByText(/Lyrics from/)).not.toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Show Up Next" }));
    expect(within(dialog).getByRole("region", { name: "Up next" })).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Show lyrics" }));
    expect(within(dialog).getByRole("button", { name: "Hello there" })).toBeInTheDocument();
  });

  it("shows the song's title, then artist, then album from its tags", async () => {
    const bridge = bridgeWith(library);
    bridge.readTrackInfo = vi.fn(async () => ({ title: "Forgotten Love", artist: "AURORA", album: "Infections of a Different Kind", durationSeconds: 200 }));
    render(<MusicHarness bridge={bridge} />);
    const songs = await screen.findByRole("list", { name: "Songs" });
    fireEvent.click(within(songs).getByRole("button", { name: "Play Song A" }));
    fireEvent.click(screen.getAllByRole("button", { name: "Open Now Playing" })[0]);

    const dialog = await screen.findByRole("dialog", { name: "Now playing: Forgotten Love by AURORA" });
    expect(within(dialog).getByRole("heading", { name: "Forgotten Love" })).toBeInTheDocument();
    expect(within(dialog).getByText("AURORA")).toHaveClass("np-artist");
    expect(within(dialog).getByText("Infections of a Different Kind")).toHaveClass("np-album");
  });

  it("reorders Up Next from the keyboard and by dragging", async () => {
    const bridge = bridgeWith(library);
    render(<MusicHarness bridge={bridge} />);
    const songs = await screen.findByRole("list", { name: "Songs" });
    fireEvent.click(within(songs).getByRole("button", { name: "Play Song A" }));
    fireEvent.click(screen.getAllByRole("button", { name: "Open Now Playing" })[0]);
    const queue = await screen.findByRole("region", { name: "Up next" });
    const names = () => within(queue).getAllByRole("button").map((button) => button.querySelector("strong")?.textContent);

    fireEvent.keyDown(within(queue).getByRole("button", { name: /Song C/ }), { key: "ArrowUp", altKey: true });
    expect(names()).toEqual(["Song A", "Song C", "Song B"]);
    expect(within(queue).getByRole("button", { name: /Song C/ })).toHaveFocus();
    // The playing song stays pinned at the top.
    fireEvent.keyDown(within(queue).getByRole("button", { name: /Song C/ }), { key: "ArrowUp", altKey: true });
    expect(names()).toEqual(["Song A", "Song C", "Song B"]);

    // Drag Song B up one row (rows are 60px apart in this fake layout).
    const rows = [...queue.querySelectorAll("li")];
    rows.forEach((row, index) => {
      row.getBoundingClientRect = () => ({ top: index * 60, height: 56, bottom: index * 60 + 56, left: 0, right: 300, width: 300, x: 0, y: index * 60, toJSON: () => ({}) });
    });
    const songB = rows[2];
    fireEvent.pointerDown(songB, { button: 0, clientY: 130 });
    fireEvent.pointerMove(window, { clientY: 100 });
    fireEvent.pointerMove(window, { clientY: 72 });
    expect(songB).toHaveClass("is-dragging");
    fireEvent.pointerUp(window, { clientY: 72 });
    fireEvent.click(within(songB).getByRole("button"));
    expect(names()).toEqual(["Song A", "Song B", "Song C"]);
    // Dropping did not also play the dragged song.
    expect(screen.getByRole("dialog", { name: "Now playing: Song A" })).toBeInTheDocument();
  });

  it("cross-fades the backdrop into the next song's cover", async () => {
    const withArt = [entry("audio/One.mp3", 2), entry("audio/Two.mp3", 1)].map((item, index) => ({ ...item, artworkPath: `art/${index}.jpg` }));
    const bridge = bridgeWith(withArt);
    bridge.readArtwork = vi.fn((path: string) => Promise.resolve(`data:image/png;base64,${path === "art/0.jpg" ? "AAAA" : "BBBB"}`));
    const { container } = render(<MusicHarness bridge={bridge} />);
    const songs = await screen.findByRole("list", { name: "Songs" });
    fireEvent.click(within(songs).getByRole("button", { name: "Play One" }));
    fireEvent.click(screen.getAllByRole("button", { name: "Open Now Playing" })[0]);
    await vi.waitFor(() => expect(container.querySelectorAll(".np-backdrop")).toHaveLength(1));

    fireEvent.click(screen.getAllByRole("button", { name: "Next" })[0]);
    await vi.waitFor(() => expect(container.querySelectorAll(".np-backdrop")).toHaveLength(2));
    const [under, over] = container.querySelectorAll<HTMLElement>(".np-backdrop");
    expect(under.style.backgroundImage).toContain("AAAA");
    expect(over.style.backgroundImage).toContain("BBBB");
    // The old layer is dropped once the new one has faded in.
    await vi.waitFor(() => expect(container.querySelectorAll(".np-backdrop")).toHaveLength(1), { timeout: 2500 });
    expect(container.querySelector<HTMLElement>(".np-backdrop")!.style.backgroundImage).toContain("BBBB");
  });

  it("creates a playlist, adds songs from the library, and plays it in order", async () => {
    const bridge = bridgeWith(library);
    render(<MusicHarness bridge={bridge} />);
    const songs = await screen.findByRole("list", { name: "Songs" });

    fireEvent.click(screen.getAllByRole("button", { name: "New Playlist" })[0]);
    const sheet = screen.getByRole("dialog", { name: "New Playlist" });
    fireEvent.change(within(sheet).getByRole("textbox", { name: "Playlist name" }), { target: { value: "Evening" } });
    fireEvent.click(within(sheet).getByRole("checkbox", { name: /Song C/ }));
    fireEvent.click(within(sheet).getByRole("button", { name: "Create with 1 song" }));

    // The new playlist opens.
    expect(screen.getByRole("heading", { name: "Evening" })).toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: "Playlist songs" })).getAllByRole("listitem")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Music" }));

    // Add another song from its row menu.
    fireEvent.click(within(screen.getByRole("list", { name: "Songs" })).getByRole("button", { name: "More options for Song A" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Evening" }));
    expect(screen.getByText("Added to “Evening”")).toBeInTheDocument();
    expect(songs).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: "Open playlist Evening" }));
    const list = screen.getByRole("list", { name: "Playlist songs" });
    expect(within(list).getAllByRole("listitem").map((row) => row.textContent)).toEqual([expect.stringContaining("Song C"), expect.stringContaining("Song A")]);
    expect(screen.getByText("2 songs · 2 min")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Play playlist" }));
    const bar = screen.getByRole("contentinfo", { name: "Music player" });
    expect(within(bar).getByText("Song C")).toBeInTheDocument();
    fireEvent.click(within(bar).getByRole("button", { name: "Next" }));
    expect(within(bar).getByText("Song A")).toBeInTheDocument();

    fireEvent.click(within(list).getByRole("button", { name: "Remove Song C from playlist" }));
    expect(within(list).getAllByRole("listitem")).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "Delete playlist" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete Playlist" }));
    expect(screen.queryByRole("button", { name: "Open playlist Evening" })).not.toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Songs" })).toBeInTheDocument();
  });

  it("adds songs to an existing playlist without duplicates and renames it", async () => {
    playlistStore.create("Focus", ["audio/Song B.mp3"]);
    const bridge = bridgeWith(library);
    render(<MusicHarness bridge={bridge} />);
    fireEvent.click(await screen.findByRole("button", { name: "Open playlist Focus" }));
    fireEvent.click(screen.getByRole("button", { name: "Add Songs" }));
    const sheet = screen.getByRole("dialog", { name: "Add Songs to “Focus”" });
    expect(within(sheet).getByRole("checkbox", { name: /Song B/ })).toBeDisabled();
    fireEvent.change(within(sheet).getByRole("textbox", { name: "Search songs" }), { target: { value: "song a" } });
    fireEvent.click(within(sheet).getByRole("checkbox", { name: /Song A/ }));
    fireEvent.click(within(sheet).getByRole("button", { name: "Add 1 song" }));
    expect(within(screen.getByRole("list", { name: "Playlist songs" })).getAllByRole("listitem")).toHaveLength(2);

    fireEvent.click(screen.getByRole("button", { name: "Rename playlist" }));
    const field = screen.getByRole("textbox", { name: "Playlist name" });
    fireEvent.change(field, { target: { value: "Deep Focus" } });
    fireEvent.keyDown(field, { key: "Enter" });
    expect(screen.getByRole("heading", { name: "Deep Focus" })).toBeInTheDocument();
  });

  it("falls back to the system player when in-app playback is unavailable", async () => {
    const bridge = bridgeWith(library, false);
    render(<MusicHarness bridge={bridge} />);
    const songs = await screen.findByRole("list", { name: "Songs" });
    fireEvent.click(within(songs).getByRole("button", { name: "Play Song A" }));
    expect(bridge.openMedia).toHaveBeenCalledWith("audio/Song A.mp3");
  });
});

describe("song menu queue actions", () => {
  it("queues a song from its row menu and says so", async () => {
    render(<MusicHarness bridge={bridgeWith(library)} />);
    const songs = await screen.findByRole("list", { name: "Songs" });
    fireEvent.click(within(songs).getByRole("button", { name: "Play Song B" }));

    fireEvent.click(within(songs).getByRole("button", { name: "More options for Song C" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Play Next" }));
    expect(screen.getByText("“Song C” plays next")).toBeInTheDocument();

    fireEvent.click(within(songs).getByRole("button", { name: "More options for Song A" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Add to Queue" }));
    expect(screen.getByText("Added “Song A” to the queue")).toBeInTheDocument();
  });
});

describe("player queue rules", () => {
  let api: ReturnType<typeof usePlayer>;
  let position = 0;
  function Probe() {
    api = usePlayer();
    position = usePlayerPosition();
    return null;
  }
  const songs = [entry("audio/1.mp3", 3), entry("audio/2.mp3", 2), entry("audio/3.mp3", 1)];

  it("hands the media keys to an open video and takes them back after", () => {
    const handlers = new Map<string, (() => void) | null>();
    Object.defineProperty(navigator, "mediaSession", { configurable: true, value: { metadata: null, setActionHandler: (action: string, handler: (() => void) | null) => { handlers.set(action, handler); } } });
    vi.stubGlobal("MediaMetadata", class { constructor(public init: unknown) {} });
    render(<PlayerProvider bridge={bridgeWith(songs)}><Probe /></PlayerProvider>);
    act(() => api.playQueue(songs, 0));
    act(() => api.setVideoActive(true));
    // The video registers its own keys; music must not overwrite them.
    const videoNext = vi.fn();
    handlers.set("nexttrack", videoNext);
    act(() => api.next());
    expect(handlers.get("nexttrack")).toBe(videoNext);

    act(() => api.setVideoActive(false));
    act(() => handlers.get("nexttrack")?.());
    expect(api.current?.relativePath).toBe("audio/3.mp3");
    vi.unstubAllGlobals();
    Reflect.deleteProperty(navigator, "mediaSession");
  });

  it("stops at the end unless repeat all wraps, and repeat one cycles modes", () => {
    render(<PlayerProvider bridge={bridgeWith(songs)}><Probe /></PlayerProvider>);
    act(() => api.playQueue(songs, 2));
    expect(api.current?.relativePath).toBe("audio/3.mp3");
    act(() => api.next());
    expect(api.playing).toBe(false);
    expect(api.current?.relativePath).toBe("audio/3.mp3");

    act(() => api.cycleRepeat());
    expect(api.repeat).toBe("all");
    act(() => api.next());
    expect(api.current?.relativePath).toBe("audio/1.mp3");
    act(() => api.cycleRepeat());
    expect(api.repeat).toBe("one");
  });

  it("restarts the track when past three seconds, otherwise goes back", () => {
    render(<PlayerProvider bridge={bridgeWith(songs)}><Probe /></PlayerProvider>);
    act(() => api.playQueue(songs, 1));
    act(() => api.seek(10));
    // jsdom does not advance currentTime on its own; seek sets it directly.
    act(() => api.prev());
    expect(api.current?.relativePath).toBe("audio/2.mp3");
    expect(position).toBe(0);
    act(() => api.prev());
    expect(api.current?.relativePath).toBe("audio/1.mp3");
  });

  it("moves queue items while the playing song keeps playing", () => {
    render(<PlayerProvider bridge={bridgeWith(songs)}><Probe /></PlayerProvider>);
    act(() => api.playQueue(songs, 0));
    act(() => api.moveInQueue(2, 1));
    expect(api.queue.map((item) => item.relativePath)).toEqual(["audio/1.mp3", "audio/3.mp3", "audio/2.mp3"]);
    expect(api.current?.relativePath).toBe("audio/1.mp3");
    act(() => api.moveInQueue(0, 2));
    expect(api.index).toBe(2);
    expect(api.current?.relativePath).toBe("audio/1.mp3");
    act(() => api.next());
    expect(api.playing).toBe(false);
  });

  it("keeps the current song first when shuffling and restores order after", () => {
    render(<PlayerProvider bridge={bridgeWith(songs)}><Probe /></PlayerProvider>);
    act(() => api.playQueue(songs, 1));
    act(() => api.toggleShuffle());
    expect(api.queue[0].relativePath).toBe("audio/2.mp3");
    expect(new Set(api.queue.map((item) => item.relativePath)).size).toBe(3);
    act(() => api.toggleShuffle());
    expect(api.queue.map((item) => item.relativePath)).toEqual(["audio/1.mp3", "audio/2.mp3", "audio/3.mp3"]);
    expect(api.current?.relativePath).toBe("audio/2.mp3");
  });
});

describe("cover colour", () => {
  it("weights vivid pixels over grey and ignores transparent ones", () => {
    const pixels = new Uint8ClampedArray([
      200, 40, 40, 255, // vivid red
      120, 120, 120, 255, // grey
      0, 0, 255, 0, // transparent, ignored
    ]);
    const color = dominantColor(pixels)!;
    expect(color.r).toBeGreaterThan(color.g + 40);
    expect(color.b).toBeLessThan(100);
    expect(dominantColor(new Uint8ClampedArray([0, 0, 0, 0]))).toBeNull();
  });

  it("derives stable fallbacks and lifts dark colours for contrast", () => {
    expect(hashColor("Song A")).toEqual(hashColor("Song A"));
    expect(hashColor("Song A")).not.toEqual(hashColor("Song B"));
    const lifted = readable({ r: 20, g: 10, b: 5 }, 150);
    expect(Math.max(lifted.r, lifted.g, lifted.b)).toBe(150);
  });
});
