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

    expect(input).toHaveValue("");
    expect(screen.getByText("Safe title")).toBeInTheDocument();
    expect(screen.getByTestId("home-result-panel")).toHaveClass("home-result-panel--open", "home-result-panel--ready");
    expect(screen.getByRole("group", { name: "Video" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download 1080p MP4" })).toBeInTheDocument();
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

  it("selects audio, reports real progress, and cancels by opaque job id", async () => {
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
    fireEvent.click(screen.getByRole("radio", { name: /MP3.*192 kbps/ }));
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
});
