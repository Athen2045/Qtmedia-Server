import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Sidebar } from "./Shell";

describe("Sidebar", () => {
  it("is icon-only with tooltips and never expands", () => {
    const onNavigate = vi.fn();
    render(<Sidebar active="home" onNavigate={onNavigate} />);
    const nav = screen.getByRole("navigation", { name: "Main navigation" });

    for (const name of ["Home", "Video", "Music", "Files", "Settings"]) {
      // The visible tooltip is decorative; the accessible name carries the label.
      const button = screen.getByRole("button", { name });
      expect(button.querySelector(".nav-tip")).toHaveTextContent(name);
      expect(button.querySelector(".nav-tip")).toHaveAttribute("aria-hidden", "true");
    }
    expect(screen.getByRole("button", { name: "Home" })).toHaveAttribute("aria-current", "page");

    fireEvent.mouseEnter(nav);
    fireEvent.click(screen.getByRole("button", { name: "Files" }));
    expect(onNavigate).toHaveBeenCalledWith("files");
    expect(nav.className).toBe("sidebar");
  });
});
