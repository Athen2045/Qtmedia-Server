import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Icon } from "./Icon";

describe("Material icons", () => {
  it.each([
    ["search", "M784-120 532-372"],
    ["home", "M240-200h120v-240"],
    ["settings", "m370-80-16-128"],
    ["clipboard", "M360-240q-33 0"],
    ["music", "M127-167q-47-47"],
    ["video", "m460-380 280-180"],
    ["files", "M160-160q-33 0"],
  ])("renders the supplied %s path", (name, path) => {
    const { container } = render(<Icon name={name as Parameters<typeof Icon>[0]["name"]} />);
    expect(container.querySelector("path")).toHaveAttribute("d", expect.stringContaining(path));
  });
});
