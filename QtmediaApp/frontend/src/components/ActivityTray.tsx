import { useDesktopSession } from "../lib/DesktopSession";

export function ActivityTray() {
  const { state, cancelDownload } = useDesktopSession();
  if (!(state.status === "downloading" || state.status === "cancelling")) return null;
  const progress = state.percent === null ? "Preparing" : `${Math.round(state.percent)}%`;
  return (
    <aside className="activity-tray" role="status" aria-label="Active download">
      <div className="activity-copy">
        <span className="activity-dot" aria-hidden="true" />
        <div><strong>{state.title}</strong><span>{state.formatLabel} · {state.status === "cancelling" ? "Cancelling…" : progress}</span></div>
      </div>
      <progress value={state.percent ?? undefined} max="100" aria-label="Download progress" />
      <button type="button" className="secondary-button" disabled={state.status === "cancelling"} onClick={() => void cancelDownload()}>{state.status === "cancelling" ? "Cancelling…" : "Cancel"}</button>
    </aside>
  );
}
