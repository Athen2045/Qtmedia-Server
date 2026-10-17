import { afterEach, describe, expect, it, vi } from "vitest";

import { installResizeHint } from "./resizeHint";

afterEach(() => vi.useRealTimers());

describe("resize hint", () => {
  it("marks the document while resizing and clears it once settled", () => {
    vi.useFakeTimers();
    const remove = installResizeHint();
    const root = document.documentElement;
    window.dispatchEvent(new Event("resize"));
    expect(root).toHaveClass("is-resizing");
    vi.advanceTimersByTime(100);
    window.dispatchEvent(new Event("resize"));
    vi.advanceTimersByTime(150);
    expect(root).toHaveClass("is-resizing");
    vi.advanceTimersByTime(40);
    expect(root).not.toHaveClass("is-resizing");
    remove();
    window.dispatchEvent(new Event("resize"));
    expect(root).not.toHaveClass("is-resizing");
  });
});
