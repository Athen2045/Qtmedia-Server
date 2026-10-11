import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { HomePage } from "./HomePage";
import { DesktopSessionProvider } from "../lib/DesktopSession";
import type { DesktopBridge, DesktopEvent } from "../lib/bridge";


function bridgeHarness() {
  let listener: ((event: DesktopEvent) => void) | undefined;
  const bridge: DesktopBridge = {
    inspectLink: vi.fn().mockResolvedValue(undefined),
    startDownload: vi.fn().mockResolvedValue(undefined),
    cancelDownload: vi.fn().mockResolvedValue(undefined),
    listLibrary: vi.fn().mockResolvedValue([]),
    openMedia: vi.fn().mockResolvedValue(undefined),
    openLibrary: vi.fn().mockResolvedValue(undefined),
    readArtwork: vi.fn().mockResolvedValue(null),
    getDownloadLocation: vi.fn().mockResolvedValue({ path: "C:\\Qtmedia\\library", isDefault: true }),
    chooseDownloadLocation: vi.fn().mockResolvedValue(null),
    useDefaultDownloadLocation: vi.fn().mockResolvedValue({ path: "C:\\Qtmedia\\library", isDefault: true }),
    minimizeWindow: vi.fn().mockResolvedValue(undefined),
    toggleMaximizeWindow: vi.fn().mockResolvedValue(undefined),
    closeWindow: vi.fn().mockResolvedValue(undefined),
    subscribe: vi.fn(async (next) => {
      listener = next;
      return () => undefined;
    }),
  };
  return {
    bridge,
    emit: (event: DesktopEvent) => listener?.(event),
  };
}

function renderHome(bridge: DesktopBridge) {
  return render(<DesktopSessionProvider bridge={bridge}><HomePage onOpenFiles={() => undefined} /></DesktopSessionProvider>);
}


describe("Home direct-link flow", () => {
  it("opens a top-down inspection panel while the link is being inspected", () => {
    const harness = bridgeHarness();
    renderHome(harness.bridge);
    const input = screen.getByRole("textbox", { name: "Media link" });
    fireEvent.change(input, { target: { value: "https://www.xvideos.com/video.abc/title" } });
    fireEvent.submit(input.closest("form")!);

    const panel = screen.getByTestId("home-result-panel");
    expect(panel).toHaveAttribute("data-reveal", "top-down");
    expect(panel).toHaveAttribute("data-state", "inspecting");
    expect(panel).toHaveClass("home-result-panel--open", "home-result-panel--inspecting");
    expect(screen.getByRole("status", { name: "Inspecting link" })).toBeInTheDocument();
  });

  it("submits a link and clears the raw value when inspection is ready", async () => {
    const harness = bridgeHarness();
    renderHome(harness.bridge);
    const input = screen.getByRole("textbox", { name: "Media link" });
    fireEvent.change(input, {
      target: { value: "https://www.xvideos.com/video.abc/title" },
    });
    fireEvent.submit(input.closest("form")!);

    expect(harness.bridge.inspectLink).toHaveBeenCalledOnce();
    await act(async () => {
      harness.emit({
        event: "inspection_ready",
        mediaId: "media-1",
        title: "Safe title",
        site: "XVideos",
        durationSeconds: 60,
        formats: [{ key: "format-video-1080", kind: "video", label: "1080p MP4", extension: "mp4", height: 1080, bitrateKbps: null }],
      });
    });

    expect(screen.queryByDisplayValue("https://www.xvideos.com/video.abc/title")).not.toBeInTheDocument();
    expect(screen.getByText("Safe title")).toBeInTheDocument();
    expect(screen.getByTestId("home-result-panel")).toHaveClass("home-result-panel--open", "home-result-panel--ready");
    expect(screen.getByRole("group", { name: "Video" })).toBeInTheDocument();
    expect(screen.getByText("Full HD")).toBeInTheDocument();
    // Video mode (the default) starts the highest format without a click.
    expect(harness.bridge.startDownload).toHaveBeenCalledWith("media-1", "format-video-1080");
    expect(screen.getByText("Starting download…")).toBeInTheDocument();
  });

  it("reads the clipboard only after the Paste button is activated", async () => {
    const harness = bridgeHarness();
    const readText = vi.fn().mockResolvedValue("https://xhamster.com/videos/example");
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { readText },
    });
    renderHome(harness.bridge);

    expect(readText).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Paste from clipboard" }));

    expect(readText).toHaveBeenCalledOnce();
    expect(await screen.findByDisplayValue("https://xhamster.com/videos/example")).toBeInTheDocument();
  });

  it("downloads the clicked format, reports real progress, and cancels by opaque job id", async () => {
    const harness = bridgeHarness();
    renderHome(harness.bridge);
    await act(async () => {
      harness.emit({
        event: "inspection_ready",
        mediaId: "media-2",
        title: "Two formats",
        site: "YouPorn",
        durationSeconds: null,
        formats: [
          { key: "format-video-720", kind: "video", label: "720p MP4", extension: "mp4", height: 720, bitrateKbps: null },
          { key: "format-audio", kind: "audio", label: "MP3 · 192 kbps", extension: "mp3", height: null, bitrateKbps: 192 },
        ],
      });
    });
    fireEvent.click(screen.getByRole("button", { name: "Download MP3 · 192 kbps" }));
    expect(harness.bridge.startDownload).toHaveBeenCalledWith("media-2", "format-audio");

    await act(async () => {
      harness.emit({ event: "download_started", jobId: "job-opaque" });
      harness.emit({ event: "download_progress", jobId: "job-opaque", downloadedBytes: 5, totalBytes: 10, percent: 50 });
    });
    expect(screen.getByText(/50%/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(harness.bridge.cancelDownload).toHaveBeenCalledWith("job-opaque");
    expect(screen.getByText("Cancelling…")).toBeInTheDocument();

    await act(async () => {
      harness.emit({ event: "cancellation_requested", jobId: "job-opaque" });
    });
    expect(screen.getByText("Cancelling…")).toBeInTheDocument();

    await act(async () => {
      harness.emit({ event: "download_cancelled", jobId: "job-opaque" });
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Download cancelled.");
  });

  it("downloads FLAC automatically in Music mode and the highest video in Video mode", async () => {
    const formats = [
      { key: "v720", kind: "video" as const, label: "720p MP4", extension: "mp4", height: 720, bitrateKbps: null },
      { key: "v1080", kind: "video" as const, label: "1080p MP4", extension: "mp4", height: 1080, bitrateKbps: null },
      { key: "mp3", kind: "audio" as const, label: "MP3 · 192 kbps", extension: "mp3", height: null, bitrateKbps: 192 },
      { key: "flac", kind: "audio" as const, label: "FLAC · from Opus 160 kbps", extension: "flac", height: null, bitrateKbps: null },
    ];
    const harness = bridgeHarness();
    renderHome(harness.bridge);

    expect(screen.getByRole("button", { name: "Video mode" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Music mode" }));
    expect(screen.getByRole("button", { name: "Music mode" })).toHaveAttribute("aria-pressed", "true");

    fireEvent.change(screen.getByLabelText("Media link"), { target: { value: "https://music.youtube.com/watch?v=r7Rn4ryE_w8" } });
    fireEvent.click(screen.getByRole("button", { name: "Find formats" }));
    await act(async () => {
      harness.emit({ event: "inspection_ready", mediaId: "media-m", title: "Song", site: "YouTube", durationSeconds: 162, formats });
    });
    expect(harness.bridge.startDownload).toHaveBeenLastCalledWith("media-m", "flac");

    await act(async () => {
      harness.emit({ event: "download_started", jobId: "job-1" });
      harness.emit({ event: "download_completed", jobId: "job-1", entry: { relativePath: "audio/Song.flac", mediaType: "audio", extension: "flac", sizeBytes: 1, modifiedAt: 1, durationSeconds: null, artworkPath: null } });
    });
    fireEvent.click(screen.getByRole("button", { name: "New link" }));
    fireEvent.click(screen.getByRole("button", { name: "Video mode" }));
    fireEvent.change(screen.getByLabelText("Media link"), { target: { value: "https://youtu.be/ApXoWvfEYVU" } });
    fireEvent.click(screen.getByRole("button", { name: "Find formats" }));
    await act(async () => {
      harness.emit({ event: "inspection_ready", mediaId: "media-v", title: "Clip", site: "YouTube", durationSeconds: 162, formats });
    });
    expect(harness.bridge.startDownload).toHaveBeenLastCalledWith("media-v", "v1080");
  });

  it("explains when a link has no audio for Music mode", async () => {
    const harness = bridgeHarness();
    renderHome(harness.bridge);
    fireEvent.click(screen.getByRole("button", { name: "Music mode" }));
    fireEvent.change(screen.getByLabelText("Media link"), { target: { value: "https://youtu.be/ApXoWvfEYVU" } });
    fireEvent.click(screen.getByRole("button", { name: "Find formats" }));
    await act(async () => {
      harness.emit({ event: "inspection_ready", mediaId: "media-x", title: "Silent", site: "YouTube", durationSeconds: null, formats: [{ key: "v", kind: "video", label: "720p MP4", extension: "mp4", height: 720, bitrateKbps: null }] });
    });
    expect(screen.getByRole("alert")).toHaveTextContent(/no audio/i);
    expect(harness.bridge.startDownload).not.toHaveBeenCalled();
  });

  it("reports each stream and the merge step instead of a restarting bar", async () => {
    const harness = bridgeHarness();
    renderHome(harness.bridge);
    await act(async () => {
      harness.emit({
        event: "inspection_ready", mediaId: "media-3", title: "Merged", site: "YouTube", durationSeconds: null,
        formats: [{ key: "format-1080", kind: "video", label: "1080p MP4", extension: "mp4", height: 1080, bitrateKbps: null }],
      });
    });
    fireEvent.click(screen.getByRole("button", { name: "Download 1080p MP4" }));
    await act(async () => {
      harness.emit({ event: "download_started", jobId: "job-m" });
      harness.emit({ event: "download_progress", jobId: "job-m", downloadedBytes: 80, totalBytes: 100, percent: 80, stage: "downloading", stream: "video", part: 1, parts: 2 });
    });
    expect(screen.getByText("Downloading video (1 of 2)")).toBeInTheDocument();
    expect(screen.getByText("80%")).toBeInTheDocument();

    await act(async () => {
      harness.emit({ event: "download_progress", jobId: "job-m", downloadedBytes: 0, totalBytes: null, percent: null, stage: "merging", stream: null, part: 1, parts: 1 });
    });
    expect(screen.getByText("Merging video and audio")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Download progress" })).not.toHaveAttribute("value");
    expect(screen.queryByText("80%")).not.toBeInTheDocument();
  });

  it("renders a generic message for unknown sidecar error codes", async () => {
    const harness = bridgeHarness();
    renderHome(harness.bridge);
    await act(async () => {
      harness.emit({ event: "error", code: "provider_secret_detail" });
    });
    expect(screen.getByRole("alert")).toHaveTextContent("The request could not be completed.");
    expect(screen.queryByText("provider_secret_detail")).not.toBeInTheDocument();
  });

  it("renders provider availability separately from a missing local engine", async () => {
    const harness = bridgeHarness();
    renderHome(harness.bridge);
    await act(async () => {
      harness.emit({ event: "error", code: "provider_unavailable" });
    });
    expect(screen.getByRole("alert")).toHaveTextContent("The source could not be reached right now.");
    expect(screen.queryByText("The local media engine is unavailable.")).not.toBeInTheDocument();
  });

  it("tells the user to update yt-dlp when a site changed", async () => {
    const harness = bridgeHarness();
    renderHome(harness.bridge);
    await act(async () => {
      harness.emit({ event: "error", code: "source_changed" });
    });
    expect(screen.getByRole("alert")).toHaveTextContent(/yt-dlp needs an update/);
  });

  it("explains an anti-bot block instead of calling the source unreachable", async () => {
    const harness = bridgeHarness();
    renderHome(harness.bridge);
    await act(async () => {
      harness.emit({ event: "error", code: "source_blocked" });
    });
    expect(screen.getByRole("alert")).toHaveTextContent(/anti-bot check/);
    expect(screen.getByRole("alert")).toHaveTextContent(/VPN/);
    expect(screen.getByRole("alert")).toHaveTextContent(/Browser cookies/);
  });

  it("explains when Firefox cookies cannot be read", async () => {
    const harness = bridgeHarness();
    renderHome(harness.bridge);
    await act(async () => {
      harness.emit({ event: "error", code: "cookies_unavailable" });
    });
    expect(screen.getByRole("alert")).toHaveTextContent(/Firefox/);
  });
});
