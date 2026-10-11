import { useDesktopSession } from "../lib/DesktopSession";
import { describeProgress } from "../lib/progress";
import { Icon, type IconName } from "./Icon";
import { QMark } from "./QMark";

export type Route = "home" | "video" | "music" | "files" | "settings";

type Item = { route: Route; label: string; icon: IconName; soon?: boolean };

const primary: Item[] = [
  { route: "home", label: "Home", icon: "home" },
  { route: "video", label: "Video", icon: "video" },
  { route: "music", label: "Music", icon: "music" },
  { route: "files", label: "Files", icon: "files" },
];

/** Floating icon-only sidebar. It never expands; each icon has a small delayed tooltip and an accessible name. */
export function Sidebar({ active, onNavigate }: { active: Route; onNavigate: (route: Route) => void }) {
  const button = ({ route, label, icon, soon }: Item) => (
    <button
      key={route}
      type="button"
      className="nav"
      aria-label={soon ? `${label} (coming soon)` : label}
      aria-current={active === route ? "page" : undefined}
      onClick={() => onNavigate(route)}
    >
      <Icon name={icon} />
      {soon ? <span className="nav-soon" aria-hidden="true" /> : null}
      <span className="nav-tip" aria-hidden="true">{soon ? `${label} · Soon` : label}</span>
    </button>
  );
  return (
    <nav className="sidebar" aria-label="Main navigation">
      <div className="side-brand" aria-hidden="true" data-tauri-drag-region><QMark size={32} /></div>
      <div className="side-nav">{primary.map(button)}</div>
      <div className="side-nav side-nav--end">{button({ route: "settings", label: "Settings", icon: "settings" })}</div>
    </nav>
  );
}

/** Unified toolbar: page title on the left, page tools on the right. */
export function Toolbar({ title, badge, children, onShowDownload }: { title: string; badge?: string; children?: React.ReactNode; onShowDownload?: () => void }) {
  return (
    <header className="toolbar" data-tauri-drag-region>
      <h1>{title}</h1>
      {badge ? <span className="badge">{badge}</span> : null}
      <span className="grow" data-tauri-drag-region />
      {onShowDownload ? <DownloadIndicator onShow={onShowDownload} /> : null}
      {children}
    </header>
  );
}

/** Small progress ring shown in toolbars while a download runs elsewhere. */
export function DownloadIndicator({ onShow }: { onShow: () => void }) {
  const { state } = useDesktopSession();
  if (!(state.status === "downloading" || state.status === "cancelling")) return null;
  const text = describeProgress(state);
  const percent = text.percent === null ? null : Math.round(text.percent);
  const circumference = 2 * Math.PI * 7;
  return (
    <button type="button" className="dl-indicator" role="status" aria-label="Active download" title={`${state.title}: ${text.label}`} onClick={onShow}>
      <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true" className={percent === null ? "dl-ring--spin" : undefined}>
        <circle cx="9" cy="9" r="7" fill="none" stroke="rgba(255,255,255,.14)" strokeWidth="2.2" />
        <circle cx="9" cy="9" r="7" fill="none" stroke="var(--accent)" strokeWidth="2.2" strokeLinecap="round" strokeDasharray={circumference} strokeDashoffset={circumference * (1 - (percent ?? 25) / 100)} transform="rotate(-90 9 9)" />
      </svg>
      <span className="sr-only">{state.title}</span>
      <span>{text.short}</span>
    </button>
  );
}
