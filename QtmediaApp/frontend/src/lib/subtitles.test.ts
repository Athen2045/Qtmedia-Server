import { beforeEach, describe, expect, it } from "vitest";

import { languageTag, pickTrack, readSubtitleChoice, trackLabel, trackLabels, writeSubtitleChoice, type SubtitleTrack } from "./subtitles";

const track = (id: string, language: string | null, label: string | null = null): SubtitleTrack => ({ id, language, label, url: `subtitles/${id}.vtt` });

describe("subtitles", () => {
  beforeEach(() => localStorage.clear());

  it("turns file and stream language codes into browser tags", () => {
    expect(languageTag("eng")).toBe("en");
    expect(languageTag("fre")).toBe("fr");
    expect(languageTag("pt-BR")).toBe("pt-BR");
    expect(languageTag("EN")).toBe("en");
    expect(languageTag(null)).toBe("");
  });

  it("names tracks by language and label", () => {
    expect(trackLabel(track("a", "eng"), 0)).toBe("English");
    expect(trackLabel(track("b", "en", "forced"), 1)).toBe("English · forced");
    expect(trackLabel(track("c", null, "Director"), 2)).toBe("Director");
    expect(trackLabel(track("d", null), 0)).toBe("Subtitles");
    expect(trackLabel(track("e", null), 3)).toBe("Subtitles 4");
  });

  it("numbers repeated names", () => {
    expect(trackLabels([track("a", "eng"), track("b", "en"), track("c", "fre")])).toEqual(["English", "English (2)", "French"]);
  });

  it("picks the remembered language, then label, then the first track", () => {
    const tracks = [track("a", "fre"), track("b", "eng", "SDH"), track("c", "en"), track("d", null, "Director")];
    expect(pickTrack(tracks, { enabled: false, language: "en" })).toBeNull();
    expect(pickTrack(tracks, { enabled: true, language: "eng" })?.id).toBe("b");
    expect(pickTrack(tracks, { enabled: true, language: "en", label: "SDH" })?.id).toBe("b");
    expect(pickTrack(tracks, { enabled: true, label: "Director" })?.id).toBe("d");
    expect(pickTrack(tracks, { enabled: true, language: "ja" })?.id).toBe("a");
    expect(pickTrack([], { enabled: true })).toBeNull();
  });

  it("remembers the choice and tolerates bad storage", () => {
    expect(readSubtitleChoice()).toEqual({ enabled: false });
    writeSubtitleChoice({ enabled: true, language: "en" });
    expect(readSubtitleChoice()).toEqual({ enabled: true, language: "en" });
    localStorage.setItem("qtmedia.video.subtitles", "{bad");
    expect(readSubtitleChoice()).toEqual({ enabled: false });
  });
});
