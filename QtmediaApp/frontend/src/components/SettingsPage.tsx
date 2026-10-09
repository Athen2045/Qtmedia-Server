import { useEffect, useState } from "react";

import { useDesktopSession } from "../lib/DesktopSession";
import type { DesktopBridge, LibraryLocation } from "../lib/bridge";
import { Icon } from "./Icon";

const messages: Record<string, string> = {
  storage_busy: "Wait for the current media job to finish before changing folders.",
  storage_unavailable: "That folder could not be prepared. Your current location was kept.",
  sidecar_unavailable: "The media engine could not switch folders. Your current location was kept.",
};

function codeOf(error: unknown) {
  if (typeof error === "string") return error;
  if (typeof error === "object" && error !== null && "code" in error) return String((error as { code: unknown }).code);
  return "storage_unavailable";
}

export function SettingsPage({ bridge }: { bridge: DesktopBridge }) {
  const { busy, refreshLibrary } = useDesktopSession();
  const [location, setLocation] = useState<LibraryLocation | null>(null);
  const [loading, setLoading] = useState(true);
  const [changing, setChanging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryToken, setRetryToken] = useState(0);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    setError(null);
    void bridge.getDownloadLocation().then((value) => {
      if (mounted) setLocation(value);
    }).catch(() => {
      if (mounted) setError("storage_unavailable");
    }).finally(() => {
      if (mounted) setLoading(false);
    });
    return () => { mounted = false; };
  }, [bridge, retryToken]);

  const change = async () => {
    setChanging(true);
    setError(null);
    try {
      const next = await bridge.chooseDownloadLocation();
      if (next) {
        setLocation(next);
        refreshLibrary();
      }
    } catch (caught) {
      setError(codeOf(caught));
    } finally {
      setChanging(false);
    }
  };

  const useDefault = async () => {
    setChanging(true);
    setError(null);
    try {
      setLocation(await bridge.useDefaultDownloadLocation());
      refreshLibrary();
    } catch (caught) {
      setError(codeOf(caught));
    } finally {
      setChanging(false);
    }
  };

  const disabled = busy || changing;
  return (
    <section className="settings-page page-panel" aria-labelledby="settings-title">
      <header className="page-header settings-header"><div><p className="eyebrow">Preferences</p><h1 id="settings-title">Settings</h1><p>Choose where Qtmedia keeps new downloads.</p></div></header>
      <article className="settings-card">
        <div className="settings-card__title"><div className="settings-icon"><Icon name="files" /></div><div><span className="location-badge">{location ? location.isDefault ? "Default" : "Custom" : "Unavailable"}</span><h2>Download location</h2></div></div>
        {loading ? <div className="settings-skeleton" aria-label="Loading download location" /> : <p className="location-path" title={location?.path}>{location?.path ?? "Location unavailable"}</p>}
        <p className="settings-help">Changing locations keeps existing files where they are. New downloads and Files will use the selected library.</p>
        {busy ? <p className="settings-notice">A media job is active. Location controls will unlock when it finishes.</p> : null}
        {error ? <div className="settings-error"><p className="inline-error" role="alert">{messages[error] ?? messages.storage_unavailable}</p>{!location ? <button type="button" className="secondary-button" onClick={() => setRetryToken((value) => value + 1)}>Retry</button> : null}</div> : null}
        <div className="settings-actions">
          <button type="button" className="primary-button" disabled={disabled} onClick={() => void change()}>Change folder</button>
          <button type="button" className="secondary-button" disabled={!location} onClick={() => void bridge.openLibrary()}>Open folder</button>
          <button type="button" className="text-button" disabled={disabled || location?.isDefault} onClick={() => void useDefault()}>Use default</button>
        </div>
      </article>
      <p className="privacy-settings"><strong>Private by design.</strong> Your library path stays on this device. Qtmedia does not upload your files or preferences.</p>
    </section>
  );
}
