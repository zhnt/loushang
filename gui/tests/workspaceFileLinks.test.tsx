import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { MessageMarkdown } from "../src/markdown/MessageMarkdown";

const reply = [
  "参见 `README.zh-CN.md`、`gui/README.md`、`docs/zh-CN/getting-started/` 和 `examples/ai/`。",
  "[项目说明](README.zh-CN.md) [含空格](docs/Getting%20Started.md#L12) [上级](../README.md)",
  "[`external.html`](https://example.com) [本机](file:///tmp/readme.md) [命令](javascript:alert%281%29)",
  "`cat README.md` `python tools/check.py` `@scope/package` `openai/gpt-5.4` `npm run check` `v1.2.3` `node`",
  "",
  "```",
  "gui/README.md",
  "```",
].join("\n");

it("opens project references on demand and preserves Markdown link labels", () => {
  const openFile = vi.fn();
  render(<MessageMarkdown text={reply} openFile={openFile} />);
  expect(openFile).not.toHaveBeenCalled();
  for (const name of ["README.zh-CN.md", "gui/README.md", "docs/zh-CN/getting-started/", "examples/ai/", "项目说明", "含空格", "上级"]) {
    fireEvent.click(screen.getByRole("button", { name }));
  }
  expect(openFile.mock.calls.map(([reference]) => reference)).toEqual([
    { path: "README.zh-CN.md" }, { path: "gui/README.md" },
    { path: "docs/zh-CN/getting-started/" }, { path: "examples/ai/" },
    { path: "README.zh-CN.md" }, { path: "docs/Getting Started.md", line: 12 },
    { path: "../README.md" },
  ]);
  expect(screen.getByRole("link", { name: "external.html" })).toHaveAttribute("rel", "noopener noreferrer");
  expect(screen.queryByRole("link", { name: "命令" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "本机" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "项目说明" })).not.toBeInTheDocument();
  for (const name of ["cat README.md", "python tools/check.py", "@scope/package", "openai/gpt-5.4", "npm run check", "v1.2.3", "node", "external.html"]) {
    expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
  }
});

it("leaves paths as text when there is no admitted Workspace", () => {
  render(<MessageMarkdown text={reply} />);
  expect(screen.queryByRole("button", { name: "README.zh-CN.md" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "项目说明" })).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "external.html" })).toHaveAttribute("href", "https://example.com");
});
