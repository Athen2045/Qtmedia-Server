import { describe, expect, it } from "vitest";

import type { FormatOption } from "./bridge";
import { pickFormat, readSearchMode, writeSearchMode } from "./modes";

const formats: FormatOption[] = [
  { key: "v1080", kind: "video", label: "1080p MP4", extension: "mp4", height: 1080, bitrateKbps: null },
  { key: "v720", kind: "video", label: "720p MP4", extension: "mp4", height: 720, bitrateKbps: null },
  { key: "mp3", kind: "audio", label: "MP3 · 192 kbps", extension: "mp3", height: null, bitrateKbps: 192 },
  { key: "flac", kind: "audio", label: "FLAC · from Opus 160 kbps", extension: "flac", height: null, bitrateKbps: null },
];

describe("pickFormat", () => {
  it("chooses the highest video height in Video mode", () => {
    expect(pickFormat([...formats].reverse(), "video")).toBe("v1080");
  });

  it("chooses FLAC in Music mode", () => {
    expect(pickFormat(formats, "music")).toBe("flac");
  });

  it("reports when the link has nothing for the mode", () => {
    expect(pickFormat(formats.filter((format) => format.kind === "audio"), "video")).toBeNull();
    expect(pickFormat(formats.filter((format) => format.kind === "video"), "music")).toBeNull();
  });
});

describe("search mode memory", () => {
  it("remembers the last mode and defaults to video", () => {
    const data = new Map<string, string>();
    const storage = { getItem: (key: string) => data.get(key) ?? null, setItem: (key: string, value: string) => void data.set(key, value) };

    expect(readSearchMode(storage)).toBe("video");
    writeSearchMode("music", storage);
    expect(readSearchMode(storage)).toBe("music");
    data.set("qtmedia.searchMode", "garbage");
    expect(readSearchMode(storage)).toBe("video");
    expect(readSearchMode(null)).toBe("video");
  });
});
