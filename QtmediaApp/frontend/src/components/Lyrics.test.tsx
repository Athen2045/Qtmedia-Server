import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { parseLrc, type LyricsState } from "../lib/lyrics";
import { LyricsPanel } from "./Lyrics";

const synced: LyricsState = {
  status: "ready",
  lyrics: { kind: "synced", source: "lrclib", lines: parseLrc("[00:01.00]First\n[00:04.00]Second\n[00:08.00]\n[00:09.00]Third") },
};

describe("LyricsPanel", () => {
  it("highlights the line being sung, dims others by distance, and seeks on click", () => {
    const onSeek = vi.fn();
    const { rerender } = render(<LyricsPanel state={synced} position={4.5} playing={false} onSeek={onSeek} trackKey="a" />);
    const second = screen.getByRole("button", { name: "Second" });
    expect(second).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("button", { name: "First" }).style.getPropertyValue("--d")).toBe("1");
    expect(screen.getByRole("button", { name: "Third" }).style.getPropertyValue("--d")).toBe("2");
    expect(screen.getByLabelText("Instrumental")).toBeInTheDocument();
    expect(screen.getByText("Lyrics from LRCLIB")).toBeInTheDocument();

    rerender(<LyricsPanel state={synced} position={9.2} playing={false} onSeek={onSeek} trackKey="a" />);
    expect(screen.getByRole("button", { name: "Third" })).toHaveAttribute("aria-current", "true");

    fireEvent.click(screen.getByRole("button", { name: "First" }));
    expect(onSeek).toHaveBeenCalledWith(1);
  });

  it("lets the listener nudge timing", () => {
    render(<LyricsPanel state={synced} position={3.6} playing={false} onSeek={() => undefined} trackKey="a" />);
    expect(screen.getByRole("button", { name: "First" })).toHaveAttribute("aria-current", "true");
    fireEvent.click(screen.getByRole("button", { name: "Show lyrics earlier" }));
    expect(screen.getByText("+0.5s")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Second" })).toHaveAttribute("aria-current", "true");
  });

  it("shows plain, loading and missing states", () => {
    const { rerender } = render(<LyricsPanel state={{ status: "loading" }} position={0} playing={false} onSeek={() => undefined} trackKey="a" />);
    expect(screen.getByRole("status", { name: "Looking for lyrics" })).toBeInTheDocument();
    rerender(<LyricsPanel state={{ status: "ready", lyrics: { kind: "plain", source: "local", text: "Line one\nLine two" } }} position={0} playing={false} onSeek={() => undefined} trackKey="a" />);
    expect(screen.getByText(/Line one/)).toBeInTheDocument();
    expect(screen.getByText(/not time-synced/i)).toBeInTheDocument();
    rerender(<LyricsPanel state={{ status: "none" }} position={0} playing={false} onSeek={() => undefined} trackKey="a" />);
    expect(screen.getByText("No lyrics found for this song.")).toBeInTheDocument();
  });
});
