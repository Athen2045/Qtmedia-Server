import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { cleanName, playlistStore, usePlaylists } from "./playlists";

beforeEach(() => {
  localStorage.clear();
  playlistStore.reset();
});

describe("playlists", () => {
  it("creates, renames, reorders and removes, persisting paths only", () => {
    const { result } = renderHook(() => usePlaylists());
    let id = "";
    act(() => { id = playlistStore.create("  Road   trip ", ["audio/a.mp3", "audio/b.mp3", "audio/a.mp3"]).id; });
    expect(result.current).toHaveLength(1);
    expect(result.current[0]).toMatchObject({ name: "Road trip", paths: ["audio/a.mp3", "audio/b.mp3"] });

    let added = 0;
    act(() => { added = playlistStore.addSongs(id, ["audio/b.mp3", "audio/c.mp3"]); });
    expect(added).toBe(1);
    act(() => playlistStore.moveSong(id, 2, 0));
    expect(result.current[0].paths).toEqual(["audio/c.mp3", "audio/a.mp3", "audio/b.mp3"]);
    act(() => playlistStore.removeSong(id, "audio/a.mp3"));
    act(() => playlistStore.rename(id, ""));
    expect(result.current[0]).toMatchObject({ name: "Untitled Playlist", paths: ["audio/c.mp3", "audio/b.mp3"] });

    const stored = JSON.parse(localStorage.getItem("qtmedia.playlists.v1") ?? "[]");
    expect(Object.keys(stored[0]).sort()).toEqual(["createdAt", "id", "name", "paths", "updatedAt"]);

    act(() => playlistStore.remove(id));
    expect(result.current).toEqual([]);
  });

  it("ignores corrupt storage and caps long names", () => {
    localStorage.setItem("qtmedia.playlists.v1", "{not json");
    expect(renderHook(() => usePlaylists()).result.current).toEqual([]);
    localStorage.setItem("qtmedia.playlists.v1", JSON.stringify([{ id: 1 }, { id: "x", name: "Ok", paths: ["a"], createdAt: 1, updatedAt: 1 }]));
    playlistStore.reset();
    expect(renderHook(() => usePlaylists()).result.current.map((item) => item.name)).toEqual(["Ok"]);
    expect(cleanName("x".repeat(200))).toHaveLength(80);
  });
});
