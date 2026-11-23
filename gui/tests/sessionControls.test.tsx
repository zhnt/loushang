import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

import { HarnessGui } from "../src/App";
import { createMockAppClient } from "./support/mockAppClient";
import type { ClientSnapshot, HarnessClientUiPort } from "../src/client/model";
import { SessionControls } from "../src/SessionControls";
import type { SessionCommandData, SessionOperationPort } from "../src/client/sessionOperations";

const scope = { sessionId: "session-a", serviceInstanceId: "host", connectionEpoch: "1" };
const info: SessionCommandData = { status: "ok", session: {
  session_id: scope.sessionId, session_name: "Canonical name", active_tool_count: 1, is_compacting: false,
  context: { accuracy: "estimated", tokens: 512, context_window: 4096 },
} };

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () { this.open = true; };
});

test("projects allowed and active tools and waits for authoritative readback", async () => {
  let active = true;
  const request = vi.fn<SessionOperationPort>(async (_, operation) => {
    if (operation.action === "tools") return { data: { status: "ok", available_tools: [
      { name: "read", description: "Read project files", allowed: true, active },
      { name: "prohibited", allowed: false, active: false },
    ] } };
    if (operation.action === "setTool") {
      active = operation.active;
      return { executionId: "exec-tool" };
    }
    if (operation.action === "lookup") return {
      state: { executionId: "exec-tool", status: "succeeded", interruptRequested: false, outcome: { errorCode: null } },
    };
    throw new Error("unexpected operation");
  });
  const fixture = createMockAppClient();
  const sample = await fixture.snapshot();
  const snapshot: ClientSnapshot = {
    ...sample, connection: "connected", capabilities: [],
    source: { kind: "live", serviceInstanceId: scope.serviceInstanceId, connectionEpoch: scope.connectionEpoch, muxSpaceId: "tools" },
    sessions: sample.sessions.map((session) => ({
      ...session, status: "idle",
      execution: {
        id: "previous", status: "succeeded", revision: 2, interruptRequested: false,
        sourceStatus: "succeeded", finalCursor: 1, truncated: false,
      },
    })),
  };
  const client: HarnessClientUiPort = {
    snapshot: async () => snapshot, subscribe: () => () => {},
    interrupt: fixture.interrupt, submitText: fixture.submitText,
    sessionOperation: request,
  };
  render(<HarnessGui client={client} />);
  fireEvent.click(await screen.findByRole("button", { name: "Session actions" }));
  expect(screen.getByRole("group", { name: "Tools" })).toBeVisible();
  fireEvent.click(screen.getByRole("menuitem", { name: "Manage tools" }));

  const allowed = await screen.findByRole("checkbox", { name: /read/i });
  expect(allowed).toBeEnabled();
  expect(allowed).toBeChecked();
  expect(screen.getByRole("checkbox", { name: /prohibited/i })).toBeDisabled();
  fireEvent.click(allowed);
  await waitFor(() => expect(screen.getByRole("checkbox", { name: /read/i })).not.toBeChecked());
  expect(request.mock.calls.map(([, action]) => action.action)).toEqual(["tools", "setTool", "lookup", "tools"]);
});

test("recovers compaction by the original ID after switching attachment and session", async () => {
  const pending = new Map();
  const request = vi.fn<SessionOperationPort>(async (address, operation) => {
    if (operation.action === "info") return {
      data: { ...info, session: { ...info.session!, session_id: address.sessionId } },
    };
    if (operation.action === "compact") throw new Error("connection lost after acceptance");
    if (operation.action === "lookup" && address.connectionEpoch === "2") return {
      state: { executionId: "compact-1", status: "succeeded", interruptRequested: false, outcome: { errorCode: null } },
    };
    return null;
  });
  const shared = { page: "info" as const, request, pending, canMutate: true, onClose: vi.fn() };
  const view = render(<SessionControls key="a-1" {...shared} scope={scope} pendingKey="host-a" />);
  expect(await screen.findByText("Canonical name")).toBeVisible();
  expect(screen.getByText("≈512 / 4,096")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Compact context" }));
  await screen.findByRole("button", { name: "Check result" });
  expect(screen.getByRole("button", { name: "Compact context" })).toBeDisabled();

  view.rerender(<SessionControls key="b-1" {...shared} scope={{ ...scope, sessionId: "session-b" }} pendingKey="host-b" />);
  expect(await screen.findByText("session-b")).toBeVisible();
  expect(screen.getByRole("button", { name: "Compact context" })).toBeEnabled();

  view.rerender(<SessionControls key="a-2" {...shared} scope={{ ...scope, connectionEpoch: "2" }} pendingKey="host-a" />);
  expect(await screen.findByText("Session operation completed.")).toBeVisible();
  const [submit] = request.mock.calls.filter(([, operation]) => operation.action === "compact");
  expect(request.mock.calls.filter(([, operation]) => operation.action === "compact")).toHaveLength(1);
  expect(request).toHaveBeenCalledWith({ ...scope, connectionEpoch: "2" }, {
    action: "lookup", submissionId: expect.any(String),
  });
  expect(request.mock.calls.filter(([, operation]) => operation.action === "lookup").map(([address, operation]) => [
    address.sessionId, "submissionId" in operation && operation.submissionId,
  ])).toEqual([["session-a", "submissionId" in submit[1] && submit[1].submissionId],
    ["session-a", "submissionId" in submit[1] && submit[1].submissionId]]);
  expect(pending.size).toBe(0);
});
