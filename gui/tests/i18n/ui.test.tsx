import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { HarnessGui } from "../../src/App";
import { createMockAppClient } from "../../src/client/mockAppClient";
import type { ClientSnapshot, HarnessClientUiPort } from "../../src/client/model";

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  HTMLDialogElement.prototype.close = function () { this.open = false; };
});

async function changeLanguage(user: ReturnType<typeof userEvent.setup>, language: string, keepOpen = false) {
  await user.click(screen.getByRole("button", { name: /^(Account menu|用户菜单)$/ }));
  await user.click(screen.getByRole("button", { name: /^(Settings|设置)$/ }));
  const dialog = screen.getByRole("dialog") as HTMLDialogElement;
  await user.selectOptions(within(dialog).getByRole("combobox"), language);
  if (!keepOpen) dialog.close();
}

it("switches all active UI without losing the draft or reconnecting the client", async () => {
  const client = createMockAppClient();
  const snapshot = vi.spyOn(client, "snapshot");
  const subscribe = vi.spyOn(client, "subscribe");
  const user = userEvent.setup();
  render(<HarnessGui client={client} />);
  const input = await screen.findByPlaceholderText("Type a fixture prompt…");
  await user.type(input, "keep this draft");
  expect(screen.queryByRole("combobox", { name: "Interface language" })).not.toBeInTheDocument();
  await changeLanguage(user, "zh-CN");
  expect(await screen.findByRole("button", { name: "中断" })).toBeEnabled();
  expect(screen.getByPlaceholderText("输入测试提示词…")).toHaveValue("keep this draft");
  expect(screen.queryByRole("combobox", { name: "界面语言" })).not.toBeInTheDocument();
  expect(document.documentElement.lang).toBe("zh-CN");
  await waitFor(() => expect(localStorage.getItem("loushang.gui.language")).toBe("zh-CN"));
  expect(snapshot).toHaveBeenCalledOnce();
  expect(subscribe).toHaveBeenCalledOnce();
  await changeLanguage(user, "en-US");
  expect(screen.getByPlaceholderText("Type a fixture prompt…")).toHaveValue("keep this draft");
});

it("translates an asynchronous result in the active language without restarting the operation", async () => {
  const client = createMockAppClient();
  let finish: (() => void) | undefined;
  const interrupt = vi.spyOn(client, "interrupt").mockImplementation(async () => {
    await new Promise<void>((resolve) => { finish = resolve; });
    return { accepted: true };
  });
  const user = userEvent.setup();
  render(<HarnessGui client={client} />);
  await user.click(await screen.findByRole("button", { name: "Interrupt" }));
  await changeLanguage(user, "zh-CN");
  finish?.();
  expect(await screen.findByText("测试执行已中断。")).toBeInTheDocument();
  expect(interrupt).toHaveBeenCalledOnce();
});
it("keeps the active language usable when preference saving fails", async () => {
  const user = userEvent.setup();
  render(<HarnessGui client={createMockAppClient()} />);
  await screen.findByPlaceholderText("Type a fixture prompt…");
  const save = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("denied"); });
  try {
    await changeLanguage(user, "zh-CN", true);
    expect(await screen.findByText("当前窗口已切换语言，但未能保存语言偏好。")).toBeInTheDocument();
    expect(screen.getByText("界面语言")).toBeInTheDocument();
  } finally { save.mockRestore(); }
});

it("localizes live UI and rejected submissions while retaining raw content and the draft", async () => {
  const source = await createMockAppClient().snapshot();
  const snapshot: ClientSnapshot = {
    ...source,
    connection: "connected",
    source: { kind: "live", serviceInstanceId: "service-test", muxSpaceId: "mux-test", connectionEpoch: "1" },
    capabilities: [],
    workspaces: [],
    sessions: source.sessions.map((session) => ({ ...session, status: "idle", run: null, changeSet: null,
      execution: { id: "execution-test", status: "succeeded", revision: 1, interruptRequested: false, sourceStatus: "succeeded", finalCursor: 1, truncated: false },
    })),
  };
  const submit = vi.fn<HarnessClientUiPort["submitText"]>(async ({ submissionId }) => ({ submissionId, accepted: false, reason: "Provider connection refused" }));
  const client: HarnessClientUiPort = {
    snapshot: async () => snapshot,
    subscribe: () => () => {},
    submitText: submit,
    interrupt: async () => ({ accepted: true }),
  };
  const user = userEvent.setup();
  render(<HarnessGui client={client} />);
  const input = await screen.findByPlaceholderText("Message the live Agent…");
  const rawMessage = snapshot.sessions.find((session) => session.id === snapshot.selectedSessionId)!.messages[0].content;
  await user.type(input, "Keep my prompt 世界");
  await changeLanguage(user, "zh-CN");
  expect(screen.getByText("在线 AppHost · 受控")).toBeVisible();
  expect(screen.getByText("已确认的 AppHost 身份")).toBeVisible();
  expect(screen.getByText("执行已成功")).toBeVisible();
  expect(screen.getByText(rawMessage)).toBeVisible();
  await user.click(screen.getByRole("button", { name: "发送" }));
  expect(await screen.findByText("提交被拒绝。")).toBeInTheDocument();
  expect(screen.getByText("Provider connection refused")).toBeInTheDocument();
  expect(input).toHaveValue("Keep my prompt 世界");
  await changeLanguage(user, "en-US");
  expect(screen.getByText("Submission rejected.")).toBeInTheDocument();
  expect(screen.getByText("Provider connection refused")).toBeInTheDocument();
  expect(screen.getByText(rawMessage)).toBeVisible();
  expect(submit).toHaveBeenCalledOnce();
});
