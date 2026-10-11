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

describe("Settings network", () => {
  it("applies secure DNS and a proxy, then shows the saved values", async () => {
    const harness = settingsHarness();
    harness.bridge.getNetworkSettings = vi.fn().mockResolvedValue({ doh: "off", proxy: null, cookies: "off" });
    harness.bridge.setNetworkSettings = vi.fn().mockResolvedValue({ doh: "cloudflare", proxy: "socks5h://127.0.0.1:1080", cookies: "off" });
    harness.render();

    const dns = await screen.findByRole("combobox", { name: "Secure DNS" });
    const apply = screen.getByRole("button", { name: "Apply network settings" });
    expect(apply).toBeDisabled();

    fireEvent.change(dns, { target: { value: "cloudflare" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Proxy" }), { target: { value: " socks5h://127.0.0.1:1080 " } });
    fireEvent.click(apply);

    expect(harness.bridge.setNetworkSettings).toHaveBeenCalledWith("cloudflare", "socks5h://127.0.0.1:1080", "off");
    expect(await screen.findByText(/network settings applied/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Apply network settings" })).toBeDisabled();
  });

  it("explains a rejected proxy and keeps what the user typed", async () => {
    const harness = settingsHarness();
    harness.bridge.getNetworkSettings = vi.fn().mockResolvedValue({ doh: "off", proxy: null, cookies: "off" });
    harness.bridge.setNetworkSettings = vi.fn().mockRejectedValue("invalid_proxy");
    harness.render();

    const proxy = await screen.findByRole("textbox", { name: "Proxy" });
    fireEvent.change(proxy, { target: { value: "proxy.example:8080" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply network settings" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/socks5h:\/\/host:port/);
    expect(proxy).toHaveValue("proxy.example:8080");
  });

  it("locks network changes while a media job is active", async () => {
    const harness = settingsHarness();
    harness.bridge.getNetworkSettings = vi.fn().mockResolvedValue({ doh: "google", proxy: null, cookies: "off" });
    harness.bridge.setNetworkSettings = vi.fn();
    harness.render();

    await act(async () => harness.emit({ event: "inspection_started" }));

    expect(await screen.findByRole("combobox", { name: "Secure DNS" })).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "Proxy" })).toBeDisabled();
    expect(screen.getByRole("combobox", { name: "Browser cookies" })).toBeDisabled();
  });

  it("turns on Firefox cookies and keeps the other network settings", async () => {
    const harness = settingsHarness();
    harness.bridge.getNetworkSettings = vi.fn().mockResolvedValue({ doh: "quad9", proxy: null, cookies: "off" });
    harness.bridge.setNetworkSettings = vi.fn().mockResolvedValue({ doh: "quad9", proxy: null, cookies: "firefox" });
    harness.render();

    const cookies = await screen.findByRole("combobox", { name: "Browser cookies" });
    await screen.findByDisplayValue("Quad9 (9.9.9.9)");
    fireEvent.change(cookies, { target: { value: "firefox" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply network settings" }));

    expect(harness.bridge.setNetworkSettings).toHaveBeenCalledWith("quad9", null, "firefox");
    expect(await screen.findByText(/network settings applied/i)).toBeInTheDocument();
    expect(cookies).toHaveValue("firefox");
  });

  it("is hidden when the bridge cannot change network settings", async () => {
    settingsHarness().render();

    expect(await screen.findByRole("heading", { name: "Download location" })).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Secure DNS" })).not.toBeInTheDocument();
  });
});

describe("Settings yt-dlp updates", () => {
  it("shows the bundled version and updates on the chosen channel", async () => {
    const harness = settingsHarness();
    harness.bridge.getYtdlpStatus = vi.fn().mockResolvedValue({ version: "2026.08.19", source: "bundled", channel: null });
    harness.bridge.updateYtdlp = vi.fn().mockResolvedValue({ version: "2026.09.27.232945", source: "updated", channel: "nightly", status: "updated" });
    harness.render();

    expect(await screen.findByText("Version 2026.08.19")).toBeInTheDocument();
    expect(screen.getByText("Bundled")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Update channel"), { target: { value: "nightly" } });
    fireEvent.click(screen.getByRole("button", { name: "Check for yt-dlp update" }));

    expect(await screen.findByText(/Updated to 2026\.09\.27\.232945/)).toBeInTheDocument();
    expect(harness.bridge.updateYtdlp).toHaveBeenCalledWith("nightly");
    expect(screen.getByText("Updated · Nightly")).toBeInTheDocument();
  });

  it("says when yt-dlp is already current", async () => {
    const harness = settingsHarness();
    harness.bridge.getYtdlpStatus = vi.fn().mockResolvedValue({ version: "2026.08.19", source: "bundled", channel: null });
    harness.bridge.updateYtdlp = vi.fn().mockResolvedValue({ version: "2026.08.19", source: "bundled", channel: null, status: "current" });
    harness.render();
    await screen.findByText("Version 2026.08.19");
    fireEvent.click(screen.getByRole("button", { name: "Check for yt-dlp update" }));
    expect(await screen.findByText("Already up to date (2026.08.19).")).toBeInTheDocument();
    expect(harness.bridge.updateYtdlp).toHaveBeenCalledWith("stable");
  });

  it("explains a failed signature check and keeps the version", async () => {
    const harness = settingsHarness();
    harness.bridge.getYtdlpStatus = vi.fn().mockResolvedValue({ version: "2026.08.19", source: "bundled", channel: null });
    harness.bridge.updateYtdlp = vi.fn().mockRejectedValue({ code: "update_verification_failed" });
    harness.render();
    await screen.findByText("Version 2026.08.19");
    fireEvent.click(screen.getByRole("button", { name: "Check for yt-dlp update" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/signature check/);
    expect(screen.getByText("Version 2026.08.19")).toBeInTheDocument();
  });

  it("locks updates while media work is active", async () => {
    const harness = settingsHarness();
    harness.bridge.getYtdlpStatus = vi.fn().mockResolvedValue({ version: "2026.08.19", source: "bundled", channel: null });
    harness.bridge.updateYtdlp = vi.fn();
    harness.render();
    await screen.findByText("Version 2026.08.19");
    act(() => harness.emit({ event: "inspection_started" }));
    expect(screen.getByRole("button", { name: "Check for yt-dlp update" })).toBeDisabled();
  });
});
