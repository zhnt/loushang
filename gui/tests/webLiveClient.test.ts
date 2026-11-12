import { afterEach, expect, it, vi } from "vitest";
import { createWebLiveClient } from "../src/client/webLiveClient";
import { liveSnapshot } from "./support/liveSnapshot";

vi.mock("@tauri-apps/api/core", () => ({ isTauri: () => false, invoke: vi.fn() }));
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

it("projects real protocol snapshots and sends only explicit operations", async () => {
  const fetcher = vi.fn(async (_url: string, options: RequestInit) => {
    const request = JSON.parse(String(options.body));
    return { ok: true, json: async () => ({ result: request.action === "snapshot" ? liveSnapshot()
      : { accepted: true, submissionId: request.input.submissionId, executionId: "execution-1" } }) };
  });
  vi.stubGlobal("fetch", fetcher);
  const client = createWebLiveClient("/workspace");
  expect((await client.snapshot()).sessions[0].messages[0].content).toBe("Read the current state");
  expect(await client.submitText({ sessionId: "session-1", submissionId: "submission-1", text: "Hello" }))
    .toMatchObject({ accepted: true, executionId: "execution-1" });
  expect(JSON.parse(String(fetcher.mock.calls[1][1].body))).toEqual({ operation: "live", workspace: "/workspace", action: "submit",
    input: { sessionId: "session-1", submissionId: "submission-1", text: "Hello", serviceInstanceId: "service-1" } });
});

it("surfaces failed snapshots without fallback and stops polling after unsubscribe", async () => {
  vi.useFakeTimers();
  const fetcher = vi.fn().mockRejectedValue(new Error("offline"));
  vi.stubGlobal("fetch", fetcher);
  const client = createWebLiveClient("/workspace");
  await expect(client.snapshot()).rejects.toThrow("offline");
  expect(await client.submitText({ sessionId: "session", submissionId: "submission", text: "hello" }))
    .toMatchObject({ accepted: false, reason: "submission_outcome_unknown" });
  const changed = vi.fn();
  const disconnected = vi.fn();
  const releaseConnection = client.subscribeConnection!(disconnected);
  const release = client.subscribeSnapshots!(changed);
  await vi.advanceTimersByTimeAsync(500);
  expect(disconnected).toHaveBeenCalledWith("disconnected");
  expect(changed).not.toHaveBeenCalled();
  release(); releaseConnection();
  const calls = fetcher.mock.calls.length;
  await vi.advanceTimersByTimeAsync(3000);
  expect(fetcher).toHaveBeenCalledTimes(calls);
});

it("binds operations to the original connection even after selection changes", async () => {
  const fetcher = vi.fn(async () => ({ ok: true, json: async () => ({ result: liveSnapshot() }) }));
  vi.stubGlobal("fetch", fetcher);
  const client = createWebLiveClient("/original-workspace", "original-host");
  const snapshot = await client.snapshot();
  expect(snapshot.source).toMatchObject({ connectionId: "original-host" });
  const request = JSON.parse(String((fetcher.mock.calls as unknown as [string, RequestInit][])[0][1].body));
  expect(request).toEqual({ operation: "host/request", connectionId: "original-host",
    request: { operation: "live", workspace: "/original-workspace", action: "snapshot", input: {} } });
});

it("recovers a lost submission receipt from the same AppHost without resubmitting", async () => {
  const submission = { sessionId: "session-1", submissionId: "submission-1", text: "Hello" };
  const receipt = { accepted: true, submissionId: "submission-1", executionId: "execution-1" };
  const requests: Array<Record<string, unknown>> = [];
  vi.stubGlobal("fetch", vi.fn(async (_url: string, options: RequestInit) => {
    const request = JSON.parse(String(options.body));
    requests.push(request);
    if (request.action === "submit") throw new Error("response lost");
    return { ok: true, json: async () => ({ result: request.action === "snapshot" ? liveSnapshot() : receipt }) };
  }));
  const client = createWebLiveClient("/workspace");
  await client.snapshot();
  expect(await client.submitText(submission)).toEqual(receipt);
  expect(requests.slice(1)).toEqual([
    { operation: "live", workspace: "/workspace", action: "submit",
      input: { ...submission, serviceInstanceId: "service-1" } },
    { operation: "live", workspace: "/workspace", action: "find-submission",
      input: { sessionId: "session-1", submissionId: "submission-1", serviceInstanceId: "service-1" } },
  ]);
});
