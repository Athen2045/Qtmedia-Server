import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { DesktopBridge, LibraryEntry } from "./bridge";
import { currentLibrary, fileName, loadLibrary, mediaTitle, useLibrary } from "./library";
import { playlistStore } from "./playlists";

const entry = (relativePath: string): LibraryEntry => ({
  relativePath, mediaType: "video", extension: "mp4", sizeBytes: 1, modifiedAt: 1, durationSeconds: null, artworkPath: null,
});

describe("display names", () => {
  it("hide the internal media ID but keep the extension and collision number", () => {
    expect(fileName(entry("video/Ebony PMV [media-JUSZOqTS_TXW].mp4"))).toBe("Ebony PMV.mp4");
    expect(mediaTitle(entry("video/Ebony PMV [media-JUSZOqTS_TXW].mp4"))).toBe("Ebony PMV");
    expect(fileName(entry("audio/Song [media-abc123def] (2).mp3"))).toBe("Song (2).mp3");
    expect(mediaTitle(entry("video/A [b] title [media-Q8Tc_BNmufz9].mp4"))).toBe("A [b] title");
  });

  it("leave names without an ID unchanged", () => {
    expect(fileName(entry("video/Older Clip.mp4"))).toBe("Older Clip.mp4");
    expect(mediaTitle(entry("video/Older Clip.mp4"))).toBe("Older Clip");
    expect(mediaTitle(entry("video/[media-onlyid99].mp4"))).toBe("[media-onlyid99]");
  });
});

describe("useLibrary", () => {
  it("moves playlists to renamed files before showing the library", async () => {
    localStorage.clear();
    playlistStore.reset();
    playlistStore.create("Mix", ["audio/A [media-1].mp3"]);
    const order: string[] = [];
    const bridge = {
      libraryRenames: vi.fn(async () => { order.push("renames"); return [{ from: "audio/A [media-1].mp3", to: "audio/A.mp3" }]; }),
      listLibrary: vi.fn(async () => { order.push("list"); return [entry("audio/A.mp3")]; }),
    } as unknown as DesktopBridge;

    const { result } = renderHook(() => useLibrary(bridge));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(order).toEqual(["renames", "list"]);
    playlistStore.reset();
    expect(JSON.parse(localStorage.getItem("qtmedia.playlists.v1")!)[0].paths).toEqual(["audio/A.mp3"]);
  });

  it("still lists the library when renames cannot be read", async () => {
    const bridge = {
      libraryRenames: vi.fn(async () => { throw { code: "storage_unavailable" }; }),
      listLibrary: vi.fn(async () => [entry("video/B.mp4")]),
    } as unknown as DesktopBridge;

    const { result } = renderHook(() => useLibrary(bridge));

    await waitFor(() => expect(result.current.entries).toHaveLength(1));
  });
});

describe("shared loads", () => {
  it("lets the player join the page's load instead of scanning again", async () => {
    const listLibrary = vi.fn(async () => [entry("video/A.mp4")]);
    const bridge = { listLibrary } as unknown as DesktopBridge;

    const page = loadLibrary(bridge);
    const player = currentLibrary(bridge);

    expect(await player).toEqual(await page);
    expect(listLibrary).toHaveBeenCalledTimes(1);
    await currentLibrary(bridge);
    expect(listLibrary).toHaveBeenCalledTimes(2);
  });

  it("shows the last list at once when a page opens again, unless the library changed", async () => {
    const listLibrary = vi.fn(async () => [entry("video/A.mp4")]);
    const bridge = { listLibrary } as unknown as DesktopBridge;
    const first = renderHook(() => useLibrary(bridge, 3));
    await waitFor(() => expect(first.result.current.loading).toBe(false));
    first.unmount();

    const again = renderHook(() => useLibrary(bridge, 3));
    expect(again.result.current.entries).toHaveLength(1);
    expect(again.result.current.loading).toBe(true);
    await waitFor(() => expect(again.result.current.loading).toBe(false));
    expect(listLibrary).toHaveBeenCalledTimes(2);

    const changed = renderHook(() => useLibrary(bridge, 4));
    expect(changed.result.current.entries).toHaveLength(0);
    await waitFor(() => expect(changed.result.current.entries).toHaveLength(1));
  });
});

describe("generated covers", () => {
  it("reloads the library when covers were made", async () => {
    let fire: () => void = () => undefined;
    const listLibrary = vi.fn(async () => [entry("video/Lanterns.mkv")]);
    const bridge = {
      listLibrary,
      subscribeArtwork: vi.fn(async (listener: () => void) => { fire = listener; return () => undefined; }),
    } as unknown as DesktopBridge;
    const { result } = renderHook(() => useLibrary(bridge));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(listLibrary).toHaveBeenCalledTimes(1);

    fire();

    await waitFor(() => expect(listLibrary).toHaveBeenCalledTimes(2));
  });
});
