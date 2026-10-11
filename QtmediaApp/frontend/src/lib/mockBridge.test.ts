import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DesktopEvent } from "./bridge";
import { createMockBridge, mockOptionsFromLocation } from "./mockBridge";

async function record(library: "empty" | "error" | "full" = "full") {
  const bridge = createMockBridge({ library });
  const events: DesktopEvent[] = [];
  await bridge.subscribe((event) => events.push(event));
  return { bridge, events };
}

describe("mock bridge", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("inspects, downloads, and adds the result to the library", async () => {
    const { bridge, events } = await record("empty");
    await bridge.inspectLink("https://example.test/watch");
    await vi.runAllTimersAsync();
    const ready = events.find((event) => event.event === "inspection_ready");
    expect(ready).toMatchObject({ site: "YouTube" });
    if (ready?.event !== "inspection_ready") throw new Error("not ready");
    expect(ready.formats.map((format) => format.label)).toContain("1080p MP4");

    await bridge.startDownload(ready.mediaId, "mock-720");
    await vi.runAllTimersAsync();
    const names = events.map((event) => event.event);
    expect(names).toContain("download_started");
    expect(names).toContain("download_progress");
    expect(names.at(-1)).toBe("download_completed");
    const listing = bridge.listLibrary();
    await vi.runAllTimersAsync();
    expect(await listing).toHaveLength(1);
  });

  it.each([
    ["not a link", "invalid_url"],
    ["https://example.test/unsupported", "unsupported_source"],
    ["https://example.test/offline", "provider_unavailable"],
    ["https://example.test/noformats", "no_formats"],
  ])("reports %s as %s", async (url, code) => {
    const { bridge, events } = await record();
    await bridge.inspectLink(url);
    await vi.runAllTimersAsync();
    expect(events.at(-1)).toEqual({ event: "error", code });
  });

  it("fails a download midway and supports cancellation", async () => {
    const { bridge, events } = await record();
    await bridge.inspectLink("https://example.test/fail");
    await vi.runAllTimersAsync();
    const ready = events.find((event) => event.event === "inspection_ready");
    if (ready?.event !== "inspection_ready") throw new Error("not ready");
    await bridge.startDownload(ready.mediaId, "mock-mp3");
    await vi.runAllTimersAsync();
    expect(events.at(-1)).toMatchObject({ event: "error", code: "download_failed" });

    await bridge.inspectLink("https://example.test/video");
    await vi.runAllTimersAsync();
    const second = events.filter((event) => event.event === "inspection_ready").at(-1);
    if (second?.event !== "inspection_ready") throw new Error("not ready");
    await bridge.startDownload(second.mediaId, "mock-1080");
    await vi.advanceTimersByTimeAsync(1000);
    const started = events.filter((event) => event.event === "download_started").at(-1);
    if (started?.event !== "download_started") throw new Error("not started");
    await bridge.cancelDownload(started.jobId);
    await vi.runAllTimersAsync();
    expect(events.slice(-2).map((event) => event.event)).toEqual(["cancellation_requested", "download_cancelled"]);
  });

  it("serves library modes and rejects listing in error mode", async () => {
    const full = createMockBridge({ library: "full" });
    const listing = full.listLibrary();
    await vi.runAllTimersAsync();
    expect((await listing).length).toBeGreaterThan(0);

    const broken = createMockBridge({ library: "error" });
    const failing = broken.listLibrary();
    const assertion = expect(failing).rejects.toEqual({ code: "storage_unavailable" });
    await vi.runAllTimersAsync();
    await assertion;
    expect(mockOptionsFromLocation("?library=empty")).toEqual({ library: "empty" });
    expect(mockOptionsFromLocation("?library=bogus")).toEqual({ library: "full" });
  });
});
