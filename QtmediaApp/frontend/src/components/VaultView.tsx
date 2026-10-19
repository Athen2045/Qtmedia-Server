import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { DesktopBridge, LibraryEntry, VaultItem } from "../lib/bridge";
import { formatBytes, formatDuration, mediaTitle } from "../lib/library";
import { createResumeStore } from "../lib/resume";
import { Icon } from "./Icon";

type Vault = NonNullable<DesktopBridge["vault"]>;

const messages: Record<string, string> = {
  vault_wrong_password: "That password isn't right.",
  vault_weak_password: "Use at least 8 characters.",
  vault_locked: "The Private folder locked. Unlock it to continue.",
  vault_exists: "A Private folder already exists for this library.",
  vault_corrupt: "The Private folder's files are damaged.",
  playback_unsupported: "This video can't be made playable, so it wasn't moved.",
  storage_busy: "Wait for the library change to finish.",
  not_found: "That video is no longer there.",
};
const message = (error: unknown) => messages[(error as { code?: string })?.code ?? String(error)] ?? messages[String(error)] ?? "Something went wrong. Try again.";

/** The playable entry for a vault item (streams from `vault/<id>.<ext>`). */
export function vaultEntry(item: VaultItem): LibraryEntry {
  return {
    relativePath: `vault/${item.id}.${item.extension}`,
    mediaType: "video",
    extension: item.extension,
    sizeBytes: item.sizeBytes,
    modifiedAt: item.addedAt,
    durationSeconds: item.durationSeconds,
    artworkPath: null,
    title: item.title,
  };
}

function PasswordForm({ mode, onSubmit }: { mode: "create" | "unlock"; onSubmit: (password: string) => Promise<void> }) {
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const creating = mode === "create";
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (creating && password.length < 8) return setError(messages.vault_weak_password);
    if (creating && password !== confirm) return setError("The passwords don't match.");
    setBusy(true);
    setError(null);
    try {
      await onSubmit(password);
    } catch (caught) {
      setError(message(caught));
      setBusy(false);
    }
  };
  return (
    <form className="vault-gate" onSubmit={(event) => void submit(event)} aria-label={creating ? "Create Private folder" : "Unlock Private folder"}>
      <span className="vault-gate__icon" aria-hidden="true"><Icon name="lock" /></span>
      <h2>{creating ? "Create your Private folder" : "Private folder is locked"}</h2>
      <p>{creating
        ? "Videos you move here are encrypted on this device and only play after you enter this password."
        : "Enter your password to see and play your private videos."}</p>
      <label className="field sheet-field"><span className="sr-only">Password</span><input type="password" autoFocus autoComplete={creating ? "new-password" : "current-password"} placeholder="Password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>
      {creating ? <label className="field sheet-field"><span className="sr-only">Confirm password</span><input type="password" autoComplete="new-password" placeholder="Confirm password" value={confirm} onChange={(event) => setConfirm(event.target.value)} /></label> : null}
      {creating ? <p className="vault-gate__warning">There is no way to reset it: if you forget this password, the videos in this folder can't be recovered.</p> : null}
      {error ? <p className="inline-error" role="alert">{error}</p> : null}
      <button type="submit" className="btn btn-accent" disabled={busy || !password}>{busy ? (creating ? "Creating…" : "Unlocking…") : creating ? "Create folder" : "Unlock"}</button>
    </form>
  );
}

function VaultCard({ vault, item, onPlay, onRestore, onDelete }: { vault: Vault; item: VaultItem; onPlay: () => void; onRestore: () => void; onDelete: () => void }) {
  const [cover, setCover] = useState<string | null>(null);
  useEffect(() => {
    if (!item.hasCover) return;
    let active = true;
    void vault.cover(item.id).then((value) => { if (active) setCover(value); }).catch(() => undefined);
    return () => { active = false; };
  }, [vault, item.id, item.hasCover]);
  return (
    <li className="video-card">
      <button type="button" className="video-thumb" aria-label={`Play ${item.title}`} onClick={onPlay}>
        {cover ? <img className="artwork video-art" src={cover} alt="" /> : <span className="artwork artwork--empty video-art"><Icon name="lock" /></span>}
        {item.durationSeconds !== null ? <span className="video-duration">{formatDuration(item.durationSeconds)}</span> : null}
        <span className="play-overlay" aria-hidden="true"><span className="play-disc"><Icon name="play" /></span></span>
      </button>
      <div className="vault-card__meta">
        <div className="media-meta"><strong title={item.title}>{item.title}</strong><span>{formatBytes(item.sizeBytes)}{item.converted ? " · converted to play" : ""}</span></div>
        <button type="button" className="btn btn-plain btn-icon" aria-label={`Move ${item.title} back to the library`} title="Move back to the library" onClick={onRestore}><Icon name="open" /></button>
        <button type="button" className="btn btn-plain btn-icon" aria-label={`Delete ${item.title} for good`} title="Delete for good" onClick={onDelete}><Icon name="trash" /></button>
      </div>
    </li>
  );
}

/** Choose library videos to move into the Private folder. */
function AddSheet({ videos, onCancel, onMove }: { videos: LibraryEntry[]; onCancel: () => void; onMove: (paths: string[]) => void }) {
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const toggle = (path: string) => setChosen((current) => {
    const next = new Set(current);
    if (next.has(path)) next.delete(path); else next.add(path);
    return next;
  });
  return (
    <div className="sheet-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onCancel(); }}>
      <div className="sheet sheet--wide" role="dialog" aria-modal="true" aria-label="Move videos to the Private folder">
        <h2>Move videos to the Private folder</h2>
        <p>Each video is encrypted here, then removed from your library for good (not to the Recycle Bin).</p>
        {videos.length ? (
          <div className="pick-list" role="group" aria-label="Library videos">
            {videos.map((entry) => (
              <label key={entry.relativePath} className="pick-row">
                <input type="checkbox" checked={chosen.has(entry.relativePath)} onChange={() => toggle(entry.relativePath)} />
                <span className="pick-title">{mediaTitle(entry)}</span>
                <span className="pick-meta">{formatBytes(entry.sizeBytes)}</span>
              </label>
            ))}
          </div>
        ) : <p className="pick-empty">There are no videos in your library to move.</p>}
        <div className="sheet-actions">
          <button type="button" className="btn btn-default" onClick={onCancel}>Cancel</button>
          <button type="button" className="btn btn-accent" disabled={!chosen.size} onClick={() => onMove([...chosen])}>{chosen.size ? `Move ${chosen.size} ${chosen.size === 1 ? "video" : "videos"}` : "Move"}</button>
        </div>
      </div>
    </div>
  );
}

function ChangePasswordSheet({ vault, onClose }: { vault: Vault; onClose: (changed: boolean) => void }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (next.length < 8) return setError(messages.vault_weak_password);
    if (next !== confirm) return setError("The new passwords don't match.");
    setBusy(true);
    setError(null);
    try {
      await vault.changePassword(current, next);
      onClose(true);
    } catch (caught) {
      setError(message(caught));
      setBusy(false);
    }
  };
  return (
    <div className="sheet-backdrop" role="presentation">
      <form className="sheet sheet--wide" role="dialog" aria-modal="true" aria-label="Change password" onSubmit={(event) => void submit(event)}>
        <h2>Change password</h2>
        <label className="field sheet-field"><span className="sr-only">Current password</span><input type="password" autoFocus autoComplete="current-password" placeholder="Current password" value={current} onChange={(event) => setCurrent(event.target.value)} /></label>
        <label className="field sheet-field"><span className="sr-only">New password</span><input type="password" autoComplete="new-password" placeholder="New password" value={next} onChange={(event) => setNext(event.target.value)} /></label>
        <label className="field sheet-field"><span className="sr-only">Confirm new password</span><input type="password" autoComplete="new-password" placeholder="Confirm new password" value={confirm} onChange={(event) => setConfirm(event.target.value)} /></label>
        {error ? <p className="inline-error" role="alert">{error}</p> : null}
        <div className="sheet-actions">
          <button type="button" className="btn btn-default" onClick={() => onClose(false)}>Cancel</button>
          <button type="submit" className="btn btn-accent" disabled={busy || !current || !next}>Change</button>
        </div>
      </form>
    </div>
  );
}

type Progress = { path: string; title: string; percent: number; stage: string };

/**
 * The Private folder: create or unlock it, then play, add, restore or delete
 * its encrypted videos. Locks itself (from Rust) after 10 minutes idle.
 */
export function VaultView({ bridge, libraryVideos, onBack, onPlayVideo, onLibraryChanged }: {
  bridge: DesktopBridge;
  libraryVideos: LibraryEntry[];
  onBack: () => void;
  onPlayVideo?: (entry: LibraryEntry, list: LibraryEntry[]) => void;
  onLibraryChanged: () => void;
}) {
  const vault = bridge.vault!;
  const [status, setStatus] = useState<{ exists: boolean; unlocked: boolean } | null>(null);
  const [items, setItems] = useState<VaultItem[]>([]);
  const [sheet, setSheet] = useState<"add" | "password" | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<VaultItem | null>(null);
  const [progress, setProgress] = useState<Progress[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const titles = useMemo(() => new Map(libraryVideos.map((entry) => [entry.relativePath, mediaTitle(entry)])), [libraryVideos]);
  // The event listener is registered once: re-subscribing on every library
  // reload (which each finished move causes) left gaps where events of the
  // next video were missed. It reads the latest values through refs.
  const titlesRef = useRef(titles);
  titlesRef.current = titles;
  const onLibraryChangedRef = useRef(onLibraryChanged);
  onLibraryChangedRef.current = onLibraryChanged;

  const refresh = useCallback(async () => {
    try {
      const next = await vault.status();
      setStatus(next);
      setItems(next.unlocked ? await vault.items() : []);
    } catch (caught) {
      if ((caught as { code?: string })?.code === "vault_locked" || caught === "vault_locked") setStatus((current) => current && { ...current, unlocked: false });
      else setNotice(message(caught));
    }
  }, [vault]);

  useEffect(() => { void refresh(); }, [refresh]);

  useEffect(() => {
    let stop: (() => void) | null = null;
    let active = true;
    void vault.subscribe((event) => {
      if (event.type === "progress") {
        setProgress((current) => current.map((row) => (row.path === event.path ? { ...row, percent: event.percent, stage: event.stage } : row)));
      } else if (event.type === "added") {
        createResumeStore().clear(event.path);
        setProgress((current) => current.filter((row) => row.path !== event.path));
        setItems((current) => [event.item, ...current.filter((item) => item.id !== event.item.id)]);
        if (event.originalKept) {
          setNotice(`"${event.item.title}" is in the Private folder, but another program is using the original, so it is still in your library. Close that program and delete it from Files.`);
        }
        onLibraryChangedRef.current();
      } else if (event.type === "failed") {
        setProgress((current) => current.filter((row) => row.path !== event.path));
        setNotice(`${titlesRef.current.get(event.path) ?? "A video"}: ${message(event.code)}`);
      } else if (event.type === "locked") {
        setItems([]);
        setSheet(null);
        setStatus((current) => current && { ...current, unlocked: false });
      }
    }).then((unlisten) => { if (active) stop = unlisten; else unlisten(); }).catch(() => undefined);
    return () => { active = false; stop?.(); };
  }, [vault]);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), notice.length > 80 ? 9000 : 4000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const lock = async () => {
    await vault.lock().catch(() => undefined);
    setItems([]);
    setStatus((current) => current && { ...current, unlocked: false });
  };

  const move = async (paths: string[]) => {
    setSheet(null);
    setProgress((current) => [...current, ...paths.map((path) => ({ path, title: titles.get(path) ?? path, percent: 0, stage: "waiting" }))]);
    try {
      await vault.add(paths);
    } catch (caught) {
      setProgress((current) => current.filter((row) => !paths.includes(row.path)));
      setNotice(message(caught));
    }
  };

  const restore = async (item: VaultItem) => {
    try {
      await vault.restore(item.id);
      setItems((current) => current.filter((entry) => entry.id !== item.id));
      setNotice(`"${item.title}" is back in your library.`);
      onLibraryChanged();
    } catch (caught) {
      setNotice(message(caught));
    }
  };

  const remove = async (item: VaultItem) => {
    setConfirmDelete(null);
    try {
      await vault.remove(item.id);
      createResumeStore().clear(vaultEntry(item).relativePath);
      setItems((current) => current.filter((entry) => entry.id !== item.id));
    } catch (caught) {
      setNotice(message(caught));
    }
  };

  const entries = items.map(vaultEntry);
  const moving = new Set(progress.map((row) => row.path));

  return (
    <div className="vault-view" aria-label="Private folder">
      <div className="vault-head">
        <button type="button" className="btn btn-plain playlist-back" onClick={onBack}><Icon name="back" />Videos</button>
        <h2 className="vault-head__title"><Icon name="lock" />Private</h2>
        {status?.unlocked ? (
          <div className="vault-head__actions">
            <button type="button" className="btn btn-default" onClick={() => setSheet("add")}><Icon name="plus" />Add videos</button>
            <button type="button" className="btn btn-plain" onClick={() => setSheet("password")}>Change password</button>
            <button type="button" className="btn btn-default" onClick={() => void lock()}><Icon name="lock" />Lock</button>
          </div>
        ) : null}
      </div>

      {status === null ? <div className="grid-skeleton grid-skeleton--video" aria-label="Loading Private folder"><span /><span /></div>
        : !status.exists ? <PasswordForm mode="create" onSubmit={async (password) => { setStatus(await vault.create(password)); setItems([]); }} />
        : !status.unlocked ? <PasswordForm mode="unlock" onSubmit={async (password) => { await vault.unlock(password); await refresh(); }} />
        : (
          <>
            {progress.length ? (
              <ul className="vault-progress" aria-label="Moving videos">
                {progress.map((row) => (
                  <li key={row.path}>
                    <span>{row.title}</span>
                    <progress className="meter" max={100} value={row.stage === "encrypting" ? row.percent : undefined} aria-label={`${row.title}: ${row.stage}`} />
                    <span className="vault-progress__stage">{row.stage === "encrypting" ? `Encrypting · ${row.percent}%` : row.stage === "preparing" ? "Making playable…" : "Waiting"}</span>
                  </li>
                ))}
              </ul>
            ) : null}
            {items.length ? (
              <ul className="video-grid" aria-label="Private videos">
                {items.map((item, index) => (
                  <VaultCard
                    key={item.id}
                    vault={vault}
                    item={item}
                    onPlay={() => onPlayVideo?.(entries[index], entries)}
                    onRestore={() => void restore(item)}
                    onDelete={() => setConfirmDelete(item)}
                  />
                ))}
              </ul>
            ) : !progress.length ? (
              <div className="empty-state" role="status">
                <h2>Nothing here yet</h2>
                <p>Move videos from your library into this folder to encrypt them.</p>
                <button type="button" className="btn btn-accent" onClick={() => setSheet("add")}><Icon name="plus" />Add videos</button>
              </div>
            ) : null}
          </>
        )}

      {sheet === "add" ? <AddSheet videos={libraryVideos.filter((entry) => !moving.has(entry.relativePath))} onCancel={() => setSheet(null)} onMove={(paths) => void move(paths)} /> : null}
      {sheet === "password" ? <ChangePasswordSheet vault={vault} onClose={(changed) => { setSheet(null); if (changed) setNotice("Password changed."); }} /> : null}
      {confirmDelete ? (
        <div className="sheet-backdrop" role="presentation">
          <div className="sheet" role="alertdialog" aria-modal="true" aria-label="Delete for good">
            <span className="sheet-icon" aria-hidden="true"><Icon name="trash" /></span>
            <h2>Delete "{confirmDelete.title}" for good?</h2>
            <p>It is removed from the Private folder and can't be recovered.</p>
            <div className="sheet-actions">
              <button type="button" className="btn btn-default" onClick={() => setConfirmDelete(null)}>Cancel</button>
              <button type="button" className="btn btn-danger" onClick={() => void remove(confirmDelete)}>Delete</button>
            </div>
          </div>
        </div>
      ) : null}
      {notice ? <div className="toast" role="status">{notice}</div> : null}
    </div>
  );
}
