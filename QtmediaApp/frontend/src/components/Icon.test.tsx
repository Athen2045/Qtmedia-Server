import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Icon, type IconName } from "./Icon";
import { QMark } from "./QMark";

describe("Qtmedia icons", () => {
  it.each<IconName>(["home", "video", "music", "files", "settings", "play", "pause", "shuffle", "repeat"])("renders %s as a decorative 24px line icon", (name) => {
    const { container } = render(<Icon name={name} />);
    const svg = container.querySelector("svg")!;
    expect(svg).toHaveAttribute("viewBox", "0 0 24 24");
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(svg.querySelector("path, rect, circle")).not.toBeNull();
  });

  it("renders the Q monogram with unique gradient ids per instance", () => {
    const { container } = render(<><QMark size={32} /><QMark size={32} tile={false} /></>);
    const ids = [...container.querySelectorAll("linearGradient")].map((node) => node.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(container.querySelectorAll("svg")).toHaveLength(2);
  });
});
