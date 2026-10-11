import { describe, expect, it } from "vitest";

import type { LibraryEntry } from "./bridge";
import { fileName, mediaTitle } from "./library";

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
