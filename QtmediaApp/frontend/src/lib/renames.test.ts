import { beforeEach, describe, expect, it } from "vitest";

import { playlistStore } from "./playlists";
import { applyRenames, renamer } from "./renames";
import { RESUME_KEY } from "./resume";

describe("renames", () => {
  beforeEach(() => {
    localStorage.clear();
    playlistStore.reset();
  });

  it("follows renames made one after another and leaves other paths alone", () => {
    const rename = renamer([
      { from: "audio/A [media-1].mp3", to: "audio/A.mp3" },
      { from: "audio/A.mp3", to: "audio/A (2).mp3" },
    ]);
    expect(rename("audio/A [media-1].mp3")).toBe("audio/A (2).mp3");
    expect(rename("audio/B.mp3")).toBe("audio/B.mp3");
  });

  it("updates playlists and resume positions, and is safe to repeat", () => {
    const list = playlistStore.create("Mix", ["audio/A [media-1].mp3", "audio/B.mp3"]);
    const updatedAt = list.updatedAt;
    localStorage.setItem(RESUME_KEY, JSON.stringify({
      "video/Film [media-2].mp4": { t: 120, at: 5 },
      "video/Film.mp4": { t: 30, at: 1 },
      "video/Other.mp4": { t: 60, at: 2 },
    }));
    const renames = [
      { from: "audio/A [media-1].mp3", to: "audio/A.mp3" },
      { from: "video/Film [media-2].mp4", to: "video/Film.mp4" },
    ];

    applyRenames(renames);
    applyRenames(renames);

    playlistStore.reset();
    const [saved] = JSON.parse(localStorage.getItem("qtmedia.playlists.v1")!);
    expect(saved.paths).toEqual(["audio/A.mp3", "audio/B.mp3"]);
    expect(saved.updatedAt).toBe(updatedAt);
    // The newer position wins when an old and a new key meet.
    expect(JSON.parse(localStorage.getItem(RESUME_KEY)!)).toEqual({
      "video/Film.mp4": { t: 120, at: 5 },
      "video/Other.mp4": { t: 60, at: 2 },
    });
  });

  it("drops a duplicate when a renamed song was already in the playlist", () => {
    playlistStore.create("Mix", ["audio/A [media-1].mp3", "audio/A.mp3"]);
    applyRenames([{ from: "audio/A [media-1].mp3", to: "audio/A.mp3" }]);
    playlistStore.reset();
    expect(JSON.parse(localStorage.getItem("qtmedia.playlists.v1")!)[0].paths).toEqual(["audio/A.mp3"]);
  });
});
