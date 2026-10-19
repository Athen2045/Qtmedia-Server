import { act, fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { DesktopBridge, LibraryEntry, VaultEvent, VaultItem } from "../lib/bridge";
import { mediaTitle } from "../lib/library";
import { usePlayableSource } from "../lib/playableSource";
import { RESUME_KEY } from "../lib/resume";
import { vaultEntry, VaultView } from "./VaultView";

const video = (name: string): LibraryEntry => ({
  relativePath: `video/${name}.mp4`, mediaType: "video", extension: "mp4", sizeBytes: 1_048_576, modifiedAt: 1, durationSeconds: 60, artworkPath: null,
});
const item = (id: string, title: string): VaultItem => ({
  id: id.padEnd(32, "0"), title, originalName: `${title}.mp4`, extension: "mp4", sizeBytes: 2_097_152, durationSeconds: 90, addedAt: 5, hasCover: false, converted: false,
});

function fakeVault({ exists = true, unlocked = false, items = [] as VaultItem[] } = {}) {
  let listener: (event: VaultEvent) => void = () => undefined;
  const state = { exists, unlocked, items: [...items] };
  const vault = {
    status: vi.fn(async () => ({ exists: state.exists, unlocked: state.unlocked })),
    create: vi.fn(async () => { state.exists = true; state.unlocked = true; return { exists: true, unlocked: true }; }),
    unlock: vi.fn(async (password: string) => {
      if (password !== "correct horse") throw { code: "vault_wrong_password" };
      state.unlocked = true;
      return { exists: true, unlocked: true };
    }),
    lock: vi.fn(async () => { state.unlocked = false; }),
    changePassword: vi.fn(async () => undefined),
    items: vi.fn(async () => state.items),
    cover: vi.fn(async () => null),
    add: vi.fn(async () => undefined),
    restore: vi.fn(async () => "video/Holiday.mp4"),
    remove: vi.fn(async () => undefined),
    subscribe: vi.fn(async (next: (event: VaultEvent) => void) => { listener = next; return () => undefined; }),
  };
  const emit = (event: VaultEvent) => act(() => listener(event));
  return { vault, emit, state };
}

function renderVault(vault: ReturnType<typeof fakeVault>["vault"], extra: Partial<Parameters<typeof VaultView>[0]> = {}) {
  const bridge = { vault, mediaUrl: (path: string) => `qtmedia://localhost/${encodeURIComponent(path)}` } as unknown as DesktopBridge;
  const props = { onBack: vi.fn(), onPlayVideo: vi.fn(), onLibraryChanged: vi.fn(), libraryVideos: [video("Holiday"), video("Party")], ...extra };
  render(<VaultView bridge={bridge} {...props} />);
  return props;
}

describe("Private folder", () => {
  it("is created with a confirmed password of at least 8 characters", async () => {
    const { vault } = fakeVault({ exists: false });
    renderVault(vault);
    const form = await screen.findByRole("form", { name: "Create Private folder" });
    expect(form).toHaveTextContent("can't be recovered");
    const [password, confirm] = within(form).getAllByPlaceholderText(/password/i);

    fireEvent.change(password, { target: { value: "short" } });
    fireEvent.change(confirm, { target: { value: "short" } });
    fireEvent.click(within(form).getByRole("button", { name: "Create folder" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("at least 8");

    fireEvent.change(password, { target: { value: "correct horse" } });
    fireEvent.change(confirm, { target: { value: "correct horses" } });
    fireEvent.click(within(form).getByRole("button", { name: "Create folder" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("don't match");
    expect(vault.create).not.toHaveBeenCalled();

    fireEvent.change(confirm, { target: { value: "correct horse" } });
    fireEvent.click(within(form).getByRole("button", { name: "Create folder" }));
    expect(await screen.findByText("Nothing here yet")).toBeInTheDocument();
    expect(vault.create).toHaveBeenCalledWith("correct horse");
  });

  it("unlocks with the right password and plays private videos by their real title", async () => {
    const { vault } = fakeVault({ items: [item("ab", "Holiday 2024")] });
    const props = renderVault(vault);
    const form = await screen.findByRole("form", { name: "Unlock Private folder" });
    const password = within(form).getByPlaceholderText("Password");

    fireEvent.change(password, { target: { value: "wrong one" } });
    fireEvent.click(within(form).getByRole("button", { name: "Unlock" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("isn't right");

    fireEvent.change(password, { target: { value: "correct horse" } });
    fireEvent.click(within(form).getByRole("button", { name: "Unlock" }));
    fireEvent.click(await screen.findByRole("button", { name: "Play Holiday 2024" }));

    const [entry, list] = (props.onPlayVideo as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(entry.relativePath).toBe(`vault/${"ab".padEnd(32, "0")}.mp4`);
    expect(mediaTitle(entry)).toBe("Holiday 2024");
    expect(list).toHaveLength(1);
  });

  it("moves chosen library videos in, with progress, and forgets their resume position", async () => {
    localStorage.setItem(RESUME_KEY, JSON.stringify({ "video/Holiday.mp4": { t: 30, at: 1 } }));
    const { vault, emit } = fakeVault({ unlocked: true });
    const props = renderVault(vault);
    fireEvent.click((await screen.findAllByRole("button", { name: "Add videos" }))[0]);
    const sheet = screen.getByRole("dialog", { name: "Move videos to the Private folder" });
    expect(sheet).toHaveTextContent("removed from your library for good");
    fireEvent.click(within(sheet).getByRole("checkbox", { name: /Holiday/ }));
    fireEvent.click(within(sheet).getByRole("button", { name: "Move 1 video" }));
    expect(vault.add).toHaveBeenCalledWith(["video/Holiday.mp4"]);

    emit({ type: "progress", path: "video/Holiday.mp4", percent: 40, stage: "encrypting" });
    expect(screen.getByRole("list", { name: "Moving videos" })).toHaveTextContent("Encrypting · 40%");
    emit({ type: "added", path: "video/Holiday.mp4", item: item("cd", "Holiday") });

    expect(screen.queryByRole("list", { name: "Moving videos" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Play Holiday" })).toBeInTheDocument();
    expect(props.onLibraryChanged).toHaveBeenCalled();
    expect(JSON.parse(localStorage.getItem(RESUME_KEY)!)).toEqual({});
  });

  it("restores, deletes after confirming, locks on request and when Rust locks it", async () => {
    const { vault, emit } = fakeVault({ unlocked: true, items: [item("ab", "Holiday"), item("ef", "Party")] });
    renderVault(vault);
    fireEvent.click(await screen.findByRole("button", { name: "Move Holiday back to the library" }));
    await waitFor(() => expect(vault.restore).toHaveBeenCalledWith("ab".padEnd(32, "0")));
    expect(await screen.findByText(/back in your library/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Delete Party for good" }));
    const confirm = screen.getByRole("alertdialog", { name: "Delete for good" });
    fireEvent.click(within(confirm).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(vault.remove).toHaveBeenCalledWith("ef".padEnd(32, "0")));

    emit({ type: "locked", reason: "idle" });
    expect(screen.getByRole("form", { name: "Unlock Private folder" })).toBeInTheDocument();
  });
});

describe("private video playback", () => {
  it("streams vault paths directly, without preparing", () => {
    const preparePlayback = vi.fn();
    const bridge = { mediaUrl: (path: string) => `qtmedia://localhost/${encodeURIComponent(path)}`, preparePlayback } as unknown as DesktopBridge;
    const entry = vaultEntry(item("ab", "Holiday"));
    const { result } = renderHook(() => usePlayableSource(bridge, entry.relativePath));
    expect(result.current).toEqual({ kind: "ready", src: `qtmedia://localhost/${encodeURIComponent(entry.relativePath)}` });
    expect(preparePlayback).not.toHaveBeenCalled();
  });
});

describe("Private folder events", () => {
  it("keeps one listener while the library reloads, so no move is missed", async () => {
    const { vault, emit } = fakeVault({ unlocked: true });
    const bridge = { vault, mediaUrl: (path: string) => path } as unknown as DesktopBridge;
    const view = render(<VaultView bridge={bridge} libraryVideos={[video("A"), video("B")]} onBack={vi.fn()} onLibraryChanged={vi.fn()} />);
    await screen.findByText("Nothing here yet");
    // Each finished move reloads the library: new arrays and callbacks.
    const onLibraryChanged = vi.fn();
    view.rerender(<VaultView bridge={bridge} libraryVideos={[video("B")]} onBack={vi.fn()} onLibraryChanged={onLibraryChanged} />);
    view.rerender(<VaultView bridge={bridge} libraryVideos={[video("B")]} onBack={vi.fn()} onLibraryChanged={onLibraryChanged} />);
    expect(vault.subscribe).toHaveBeenCalledTimes(1);

    emit({ type: "added", path: "video/B.mp4", item: item("bb", "B") });
    expect(screen.getByRole("button", { name: "Play B" })).toBeInTheDocument();
    expect(onLibraryChanged).toHaveBeenCalledTimes(1);
  });

  it("says when the original could not be removed", async () => {
    const { vault, emit } = fakeVault({ unlocked: true });
    renderVault(vault);
    await screen.findByText("Nothing here yet");
    emit({ type: "added", path: "video/Holiday.mp4", item: item("cd", "Holiday"), originalKept: true });
    expect(screen.getByRole("status")).toHaveTextContent("another program is using the original");
  });
});
