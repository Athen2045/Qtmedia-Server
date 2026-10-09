import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DesktopSessionProvider } from "../lib/DesktopSession";
import type { DesktopBridge, DesktopEvent } from "../lib/bridge";
import { SettingsPage } from "./SettingsPage";

function settingsHarness(location = { path: "C:\\Users\\Test\\AppData\\Qtmedia\\library", isDefault: true }) {
  let listener: ((event: DesktopEvent) => void) | undefined;
  const bridge: DesktopBridge = {
    inspectLink: vi.fn().mockResolvedValue(undefined),
    startDownload: vi.fn().mockResolvedValue(undefined),
    cancelDownload: vi.fn().mockResolvedValue(undefined),
    listLibrary: vi.fn().mockResolvedValue([]),
    openMedia: vi.fn().mockResolvedValue(undefined),
    openLibrary: vi.fn().mockResolvedValue(undefined),
    readArtwork: vi.fn().mockResolvedValue(null),
    getDownloadLocation: vi.fn().mockResolvedValue(location),
    chooseDownloadLocation: vi.fn().mockResolvedValue(null),
    useDefaultDownloadLocation: vi.fn().mockResolvedValue(location),
    minimizeWindow: vi.fn().mockResolvedValue(undefined),
    toggleMaximizeWindow: vi.fn().mockResolvedValue(undefined),
    closeWindow: vi.fn().mockResolvedValue(undefined),
    subscribe: vi.fn(async (next) => { listener = next; return () => undefined; }),
  };
  return {
    bridge,
    emit: (event: DesktopEvent) => listener?.(event),
    render: () => render(<DesktopSessionProvider bridge={bridge}><SettingsPage bridge={bridge} /></DesktopSessionProvider>),
  };
}

describe("Settings download location", () => {
  it("shows the default path and applies a custom location without moving old files", async () => {
    const harness = settingsHarness();
    harness.bridge.chooseDownloadLocation = vi.fn().mockResolvedValue({ path: "D:\\Media\\Qtmedia\\library", isDefault: false });
    harness.render();

    expect(await screen.findByText("C:\\Users\\Test\\AppData\\Qtmedia\\library")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Change folder" }));

    expect(await screen.findByText("D:\\Media\\Qtmedia\\library")).toBeInTheDocument();
    expect(screen.getByText("Custom")).toBeInTheDocument();
    expect(screen.getByText(/keeps existing files where they are/i)).toBeInTheDocument();
  });

  it("keeps the current path when the native picker is cancelled", async () => {
    const harness = settingsHarness();
    harness.render();
    expect(await screen.findByText("C:\\Users\\Test\\AppData\\Qtmedia\\library")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Change folder" }));
    await act(async () => undefined);
    expect(screen.getByText("C:\\Users\\Test\\AppData\\Qtmedia\\library")).toBeInTheDocument();
  });

  it("locks location changes while media work is active", async () => {
    const harness = settingsHarness();
    harness.render();
    await screen.findByText("C:\\Users\\Test\\AppData\\Qtmedia\\library");
    act(() => harness.emit({ event: "inspection_started" }));
    expect(screen.getByRole("button", { name: "Change folder" })).toBeDisabled();
    expect(screen.getByText(/media job is active/i)).toBeInTheDocument();
  });

  it("offers Retry when the saved location cannot be read", async () => {
    const harness = settingsHarness();
    harness.bridge.getDownloadLocation = vi.fn()
      .mockRejectedValueOnce("storage_unavailable")
      .mockResolvedValueOnce({ path: "C:\\Recovered\\Qtmedia\\library", isDefault: true });
    harness.render();

    expect(await screen.findByRole("alert")).toHaveTextContent(/could not be prepared/i);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("C:\\Recovered\\Qtmedia\\library")).toBeInTheDocument();
  });
});
