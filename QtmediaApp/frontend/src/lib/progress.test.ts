import { describe, expect, it } from "vitest";

import { describeProgress, type ProgressInput } from "./progress";

const base: ProgressInput = {
  status: "downloading", formatLabel: "1080p MP4", stage: "downloading", stream: null, part: 1, parts: 1, percent: null,
};

describe("describeProgress", () => {
  it("names the format and percentage for a single stream", () => {
    expect(describeProgress({ ...base, percent: 45.4 })).toEqual({ label: "Downloading 1080p MP4", value: "45%", short: "45%", percent: 45.4 });
  });

  it("names each stream of a merged download instead of restarting silently", () => {
    expect(describeProgress({ ...base, stream: "video", part: 1, parts: 2, percent: 80 }).label).toBe("Downloading video (1 of 2)");
    expect(describeProgress({ ...base, stream: "audio", part: 2, parts: 2, percent: 10 })).toMatchObject({ label: "Downloading audio (2 of 2)", value: "10%" });
  });

  it("shows postprocessing stages without a fabricated percentage", () => {
    expect(describeProgress({ ...base, stage: "merging", percent: 100 })).toEqual({ label: "Merging video and audio", value: "", short: "Merging…", percent: null });
    expect(describeProgress({ ...base, formatLabel: "MP3 · 192 kbps", stage: "converting" })).toMatchObject({ label: "Converting to MP3", short: "Converting…", percent: null });
    expect(describeProgress({ ...base, formatLabel: "FLAC · from Opus 142 kbps", stage: "converting" }).label).toBe("Converting to FLAC");
    expect(describeProgress({ ...base, stage: "processing" })).toMatchObject({ label: "Finishing up", percent: null });
    expect(describeProgress({ ...base, stage: "saving" })).toMatchObject({ label: "Saving to your library", short: "Saving…", percent: null });
  });

  it("says it is starting before the source reports a size", () => {
    expect(describeProgress(base)).toEqual({ label: "Downloading 1080p MP4", value: "Starting", short: "Starting", percent: null });
  });

  it("puts cancellation ahead of any stage", () => {
    expect(describeProgress({ ...base, status: "cancelling", stage: "merging", percent: 50 })).toEqual({ label: "Cancelling download", value: "", short: "Cancelling…", percent: null });
  });
});
