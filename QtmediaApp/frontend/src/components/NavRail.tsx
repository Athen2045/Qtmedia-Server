import { Icon } from "./Icon";

export type Route = "home" | "video" | "music" | "files" | "settings";

const primary: Array<{ route: Route; label: string; icon: "home" | "video" | "music" | "files" }> = [
  { route: "home", label: "Home", icon: "home" },
  { route: "video", label: "Video", icon: "video" },
  { route: "music", label: "Music", icon: "music" },
  { route: "files", label: "Files", icon: "files" },
];

export function NavRail({ active, onNavigate }: { active: Route; onNavigate: (route: Route) => void }) {
  const button = (route: Route, label: string, icon: "home" | "video" | "music" | "files" | "settings") => (
    <button
      key={route}
      type="button"
      className="nav-button"
      aria-label={label}
      aria-current={active === route ? "page" : undefined}
      title={label}
      onClick={() => onNavigate(route)}
    >
      <Icon name={icon} />
      <span className="nav-tooltip">{label}</span>
    </button>
  );

  return (
    <nav className="nav-rail" aria-label="Main navigation">
      <div className="rail-brand" aria-hidden="true">Q</div>
      <div className="nav-primary">{primary.map((item) => button(item.route, item.label, item.icon))}</div>
      <div className="nav-secondary">{button("settings", "Settings", "settings")}</div>
    </nav>
  );
}
