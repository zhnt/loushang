import { act, fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { MessageMarkdown } from "../src/markdown/MessageMarkdown";

it("opens workspace file references through the scoped desktop action", async () => {
  const open = vi.fn(async () => undefined);
  render(<MessageMarkdown
    text={'生成了 `index.html`。 [说明](docs/readme.md) [`external.html`](https://example.com) [越界](../secret.txt)'}
    openFile={open}
  />);
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "index.html" }));
    fireEvent.click(screen.getByRole("button", { name: "docs/readme.md" }));
  });
  expect(open.mock.calls).toEqual([["index.html"], ["docs/readme.md"]]);
  expect(screen.getByRole("link", { name: "external.html" })).toHaveAttribute("href", "https://example.com");
  expect(screen.queryByRole("button", { name: "external.html" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "越界" })).not.toBeInTheDocument();
});
