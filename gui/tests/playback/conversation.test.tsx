import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { HarnessGui } from "../../src/App";
import { createMockAppClient } from "../support/mockAppClient";
import type { ClientSnapshot, FixturePlaybackPort, HarnessClientUiPort, SessionModels, ThinkingLevel } from "../../src/client/model";

const liveModel = {
  id: "test:primary:model",
  provider: "test",
  endpointId: "primary",
  modelId: "model",
  label: "Test model",
  supportsThinking: false,
};

function withSnapshot(client: FixturePlaybackPort, snapshot: ClientSnapshot): FixturePlaybackPort {
  return {
    snapshot: async () => snapshot,
    subscribe: (listener) => client.subscribe(listener),
    submitText: (input) => client.submitText(input),
    interrupt: (id) => client.interrupt(id),
    advanceFixture: () => client.advanceFixture(),
    remainingFixtureSteps: () => client.remainingFixtureSteps(),
  };
}

describe("GUI-B1 Workspace / Task / Review fixture", () => {
  it("keeps the composer bound to the selected conversation during a Mux switch", async () => {
    const fixture = await createMockAppClient().snapshot();
    const [a, b] = fixture.sessions;
    const snapshot = (session: typeof a, muxSpaceId: string): ClientSnapshot => ({
      ...fixture, sessions: [session], selectedSessionId: session.id, connection: "connected",
      source: { kind: "live", connectionId: "local", muxSpaceId, serviceInstanceId: "host", connectionEpoch: "1" },
    });
    const submitText = vi.fn<HarnessClientUiPort["submitText"]>(async ({ submissionId }) => ({ submissionId, accepted: false }));
    const client = (getSnapshot: HarnessClientUiPort["snapshot"]): HarnessClientUiPort => ({
      snapshot: getSnapshot, submitText, subscribe: () => () => {}, interrupt: async () => ({ accepted: false }),
      sessionModels: async () => ({ currentId: liveModel.id, models: [liveModel] }),
    });
    let resolveB!: (value: ClientSnapshot) => void;
    const bSnapshot = new Promise<ClientSnapshot>((resolve) => { resolveB = resolve; });
    const clientA = client(async () => snapshot(a, "a"));
    const clientB = client(() => bSnapshot);
    const { rerender } = render(<HarnessGui client={clientA} />);
    fireEvent.change(await screen.findByRole("textbox"), { target: { value: "A draft" } });

    rerender(<HarnessGui client={clientB} />);
    const staleComposer = screen.getByRole("textbox");
    expect(staleComposer).toBeDisabled();
    fireEvent.keyDown(staleComposer, { key: "Enter" });
    expect(submitText).not.toHaveBeenCalled();
    await act(async () => { resolveB(snapshot(b, "b")); });
    expect(screen.getByRole("textbox")).toHaveValue("");
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "B message" } });
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
    await waitFor(() => expect(submitText).toHaveBeenCalledWith(expect.objectContaining({ sessionId: b.id, text: "B message" })));

    rerender(<HarnessGui client={clientA} />);
    await waitFor(() => expect(screen.getByRole("textbox")).toHaveValue("A draft"));
  });

  it("renders assistant Markdown while keeping user text and untrusted markup inert", async () => {
    const fixture = createMockAppClient();
    const snapshot = await fixture.snapshot();
    const selected = snapshot.sessions.find((session) => session.id === snapshot.selectedSessionId)!;
    const userText = "**Keep my exact input**";
    const markdown = [
      "### Report",
      "",
      "**Strong** text with `inline code`.",
      "",
      "- first item",
      "",
      "| A | B |",
      "| --- | --- |",
      "| x | y |",
      "",
      "```text",
      "code sample",
      "```",
      "",
      "```python",
      "def example():",
      "    return '<script>inert</script>'",
      "```",
      "",
      "[Website](https://example.com/) [Script](javascript:alert(1))",
      "",
      "![image description](https://example.com/pixel.png)",
      "",
      "<iframe src='https://example.com/'></iframe>",
    ].join("\n");
    render(<HarnessGui client={withSnapshot(fixture, {
      ...snapshot,
      sessions: snapshot.sessions.map((session) => session.id === selected.id ? {
        ...session,
        messages: [
          { id: "user-md", role: "user", content: userText, phase: "complete" },
          { id: "assistant-md", role: "assistant", content: markdown, phase: "streaming" },
        ],
      } : session),
    })} />);
    const reply = await screen.findByRole("article", { name: "assistant message" });
    expect(within(reply).getByRole("heading", { name: "Report", level: 3 })).toBeVisible();
    expect(within(reply).getByText("Strong").tagName).toBe("STRONG");
    expect(within(reply).getByText("inline code").tagName).toBe("CODE");
    expect(within(reply).getByRole("listitem")).toHaveTextContent("first item");
    expect(within(reply).getByRole("table")).toBeVisible();
    expect(reply.querySelector("pre code")).toHaveTextContent("code sample");
    expect(within(reply).getByText("python")).toBeVisible();
    expect(reply.querySelector(".language-python .hljs-keyword")).toHaveTextContent("def");
    expect(reply.querySelector(".language-python")?.textContent).toContain("\n    return '<script>inert</script>'");
    expect(within(reply).getByRole("link", { name: "Website" })).toHaveAttribute("href", "https://example.com/");
    expect(within(reply).queryByRole("link", { name: "Script" })).toBeNull();
    expect(reply.querySelector("iframe, img, script")).toBeNull();
    expect(within(screen.getByRole("article", { name: "user message" })).getByText(userText)).toBeVisible();
  });

  it("lets the user retry a failed execution that published no transcript records", async () => {
    const seed = await createMockAppClient().snapshot();
    const initial: ClientSnapshot = {
      ...seed,
      source: { kind: "live", muxSpaceId: "retry-mux", serviceInstanceId: "retry-host", connectionEpoch: "1" },
      connection: "connected",
      sessions: seed.sessions.map((session) => ({ ...session, status: "idle", execution: null })),
    };
    let publish: (snapshot: ClientSnapshot) => void = () => {};
    const submit = vi.fn(async ({ submissionId }: { submissionId: string }) => ({
      submissionId, accepted: true, executionId: "execution-retry",
    }));
    const user = userEvent.setup();
    render(<HarnessGui client={{
      snapshot: async () => initial,
      subscribe: () => () => undefined,
      subscribeSnapshots: (listener) => { publish = listener; return () => undefined; },
      submitText: submit,
      interrupt: async () => ({ accepted: false }),
      sessionModels: async () => ({ currentId: liveModel.id, models: [liveModel] }),
    }} />);
    const input = await screen.findByRole("textbox", { name: "Message for GUI development" });
    await user.type(input, "Keep this message");
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    expect(input).toHaveValue("Keep this message");
    act(() => publish({
      ...initial,
      sessions: initial.sessions.map((session) => session.id === initial.selectedSessionId ? {
        ...session,
        status: "failed",
        execution: {
          id: "execution-retry", status: "failed", revision: 2, errorCode: "execution_start_failed",
          sourceStatus: null, finalCursor: null, interruptRequested: false, truncated: false,
        },
      } : session),
    }));
    expect(await screen.findByText(/^Execution failed$/i)).toBeVisible();
    expect(input).toHaveValue("Keep this message");
    await user.click(screen.getByText(/^Execution failed$/i));
    expect(screen.getByText("execution_start_failed")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(submit).toHaveBeenCalledTimes(2);
  });

  it("follows the live transcript until the reader scrolls back", async () => {
    const fixture = await createMockAppClient().snapshot();
    const initial: ClientSnapshot = {
      ...fixture,
      connection: "connected",
      source: { kind: "live", muxSpaceId: "scroll-mux", serviceInstanceId: "scroll-host", connectionEpoch: "1" },
      sessions: fixture.sessions.map((session) => ({
        ...session,
        context: { ...session.context, source: "live" },
      })),
    };
    let publish: (snapshot: ClientSnapshot) => void = () => {};
    render(<HarnessGui client={{
      snapshot: async () => initial,
      subscribe: () => () => undefined,
      subscribeSnapshots: (listener) => { publish = listener; return () => undefined; },
      submitText: async ({ submissionId }) => ({ submissionId, accepted: false }),
      interrupt: async () => ({ accepted: false }),
    }} />);
    const transcript = await screen.findByLabelText("Session transcript");
    let height = 900;
    Object.defineProperties(transcript, { scrollHeight: { get: () => height }, clientHeight: { value: 400 } });
    act(() => publish({ ...initial, sessions: initial.sessions.map((session) => ({ ...session })) }));
    expect(transcript.scrollTop).toBe(900);
    fireEvent.scroll(transcript, { target: { scrollTop: 120 } });
    height = 1100;
    act(() => publish({ ...initial, sessions: initial.sessions.map((session) => ({ ...session })) }));
    expect(transcript.scrollTop).toBe(120);
    fireEvent.scroll(transcript, { target: { scrollTop: 700 } });
    height = 1300;
    act(() => publish({ ...initial, sessions: initial.sessions.map((session) => ({ ...session })) }));
    expect(transcript.scrollTop).toBe(1300);
  });

  it("restores independent transcript positions when switching Sessions", async () => {
    const user = userEvent.setup();
    const client = createMockAppClient();
    render(<HarnessGui client={client} />);
    await screen.findByRole("heading", { name: "GUI development" });
    const transcript = () => screen.getByLabelText("Session transcript");
    fireEvent.scroll(transcript(), { target: { scrollTop: 180 } });
    await user.click(screen.getByRole("button", { name: "Operational ontology · Idle" }));
    expect(transcript().scrollTop).toBe(0);
    fireEvent.scroll(transcript(), { target: { scrollTop: 45 } });
    await user.click(screen.getByRole("button", { name: "GUI development · Running" }));
    expect(transcript().scrollTop).toBe(180);
    await act(async () => { await client.advanceFixture(); });
    expect(transcript().scrollTop).toBe(180);
    await user.click(screen.getByRole("button", { name: "Operational ontology · Idle" }));
    expect(transcript().scrollTop).toBe(45);
  });

  it.each(["missing", "unavailable", "incompatible"])("downgrades %s capabilities and removes previously visible projections", async (mode) => {
    const user = userEvent.setup();
    const client = createMockAppClient();
    const snapshot = await client.snapshot();
    const view = render(<HarnessGui client={client} />);
    await screen.findByRole("heading", { name: "GUI development" });
    await user.click(within(screen.getByLabelText("Fixture changes")).getByRole("button", { name: /gui-interface-specification\.md/ }));
    expect(screen.getByLabelText("Quick look gui-interface-specification.md")).toBeVisible();
    view.rerender(<HarnessGui client={withSnapshot(client, {
      ...snapshot,
      capabilities: mode === "missing" ? [] : snapshot.capabilities.map((capability) => ({
        ...capability,
        availability: mode === "unavailable" ? "unavailable" : capability.availability,
        version: mode === "incompatible" ? "fixture/v999" : capability.version,
      })),
    })} />);
    await screen.findAllByText("Workspace details unavailable");
    expect(screen.queryByLabelText("Fixture changes")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Quick look gui-interface-specification.md")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Step 1 / 4" })).not.toBeInTheDocument();
    expect(screen.queryByText("git · main")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Open Work Dock" }));
    const dock = screen.getByLabelText("Work Dock");
    for (const label of ["Tasks", "Subagents", "Review"]) {
      await user.click(within(dock).getByRole("button", { name: label }));
      expect(within(dock).getByText(new RegExp(`${label} capability`))).toBeVisible();
    }
    view.rerender(<HarnessGui client={withSnapshot(client, snapshot)} />);
    expect(await screen.findByLabelText("Fixture changes")).toBeVisible();
    expect(screen.getByLabelText("Read-only review")).toBeVisible();
  });

  it("sends, streams, interrupts and starts another fixture Run", async () => {
    const user = userEvent.setup();
    const client = createMockAppClient();
    render(<HarnessGui client={client} />);
    await screen.findByRole("heading", { name: "GUI development" });
    await user.click(screen.getByRole("button", { name: "Operational ontology · Idle" }));
    const input = screen.getByRole("textbox", { name: "Message for Operational ontology" });
    await user.type(input, "Test streaming");
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(input).toHaveValue("");
    expect(screen.queryByRole("button", { name: "Send" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Interrupt" })).toBeEnabled();
    // The global fixture queue also contains events for the inactive GUI Session.
    for (let steps = 0; steps < 30 && !screen.queryByText(/The GUI keeps a separate client scope/); steps++) {
      await act(async () => { await client.advanceFixture(); });
    }
    expect(screen.getByText(/The GUI keeps a separate client scope/)).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Interrupt" }));
    expect(screen.getByRole("button", { name: "Operational ontology · Interrupted" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Interrupt" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    await user.type(input, "Complete another Run");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await act(async () => {
      for (let steps = 0; steps < 30 && client.remainingFixtureSteps() > 0; steps++) await client.advanceFixture();
    });
    expect(screen.getByRole("button", { name: "Operational ontology · Idle" })).toBeVisible();
    expect(screen.getByText(/and projects shared service facts through its UI port/)).toBeVisible();
  });

  it("uses the header chip while waiting for the AppHost snapshot", async () => {
    let failSnapshot: () => void = () => {};
    const snapshot = new Promise<ClientSnapshot>((_resolve, reject) => {
      failSnapshot = () => reject(new Error("AppHost unavailable"));
    });
    const client = createMockAppClient();
    render(<HarnessGui client={{
      snapshot: () => snapshot,
      subscribe: (listener) => client.subscribe(listener),
      submitText: (input) => client.submitText(input),
      interrupt: (id) => client.interrupt(id),
    }} />);
    expect(screen.getByRole("status")).toHaveTextContent("Connecting");
    expect(screen.queryByText("No Session is available.")).not.toBeInTheDocument();
    expect(screen.queryByText("Connecting to AppHost…")).not.toBeInTheDocument();
    await act(async () => failSnapshot());
    expect(screen.getByText("Resync required")).toBeVisible();
    expect(screen.getByText("Synchronization interrupted. Resynchronize to continue.")).toBeVisible();
  });

  it("keeps drafts editable but blocks commands while disconnected", async () => {
    const user = userEvent.setup();
    const client = createMockAppClient();
    const snapshot = await client.snapshot();
    render(<HarnessGui client={{
      snapshot: async () => ({ ...snapshot, connection: "disconnected" }),
      subscribe: (listener) => client.subscribe(listener),
      submitText: (input) => client.submitText(input),
      interrupt: (id) => client.interrupt(id),
      advanceFixture: () => client.advanceFixture(),
      remainingFixtureSteps: () => client.remainingFixtureSteps(),
    }} />);
    await screen.findByRole("heading", { name: "GUI development" });
    expect(screen.getByRole("button", { name: "Interrupt" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "GUI development · Running" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "GUI development · Stale · was Running" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Operational ontology · Stale · was Idle" }));
    const input = screen.getByRole("textbox", { name: "Message for Operational ontology" });
    await user.type(input, "Keep this draft");
    await user.keyboard("{Enter}");
    expect(input).toHaveValue("Keep this draft");
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    expect(screen.queryByText("Keep this draft", { selector: "article p" })).not.toBeInTheDocument();
    await user.click(screen.getByText(/Fixture playback ·/));
    expect(screen.getByRole("button", { name: "Advance fixture" })).toBeDisabled();
  });

  it("requires a model for live submission and preserves the draft while selecting it", async () => {
    const user = userEvent.setup();
    const fixture = createMockAppClient();
    const snapshot = await fixture.snapshot();
    const submitText = vi.fn(async (input: { submissionId: string }) => ({
      submissionId: input.submissionId,
      accepted: true,
    }));
    let confirmModel!: (models: SessionModels) => void;
    render(<HarnessGui client={{
      snapshot: async () => ({
        ...snapshot,
        connection: "connected",
        source: { kind: "live", serviceInstanceId: "service-live", muxSpaceId: "mux-live", connectionEpoch: "1" },
        capabilities: snapshot.capabilities.map((capability) => ({
          ...capability,
          availability: "unavailable",
          version: null,
        })),
        sessions: snapshot.sessions.map((session) => ({
          ...session,
          context: { ...session.context, source: "live" },
          changeSet: null,
          documents: [],
          run: null,
          status: "idle" as const,
          execution: null,
        })),
      }),
      subscribe: () => () => undefined,
      submitText,
      interrupt: async () => ({ accepted: false }),
      sessionModels: async () => ({ currentId: null, models: [liveModel] }),
      selectModel: () => new Promise((resolve) => { confirmModel = resolve; }),
    }} />);
    await screen.findByText("Live AppHost · controlled");
    expect(screen.queryByLabelText("Fixture playback controls")).not.toBeInTheDocument();
    const input = screen.getByRole("textbox", { name: "Message for GUI development" });
    expect(input).toBeEnabled();
    expect(screen.getByRole("button", { name: "Account menu" })).toBeVisible();
    await user.type(input, "Talk to the real Agent");
    const send = screen.getByRole("button", { name: "Send" });
    expect(send).toBeDisabled();
    await user.click(send);
    input.focus();
    await user.keyboard("{Enter}");
    expect(submitText).not.toHaveBeenCalled();
    expect(input).toHaveValue("Talk to the real Agent");

    const picker = screen.getByRole("button", { name: "Session model" });
    expect(picker).toHaveTextContent("Select a model");
    await user.click(picker);
    await user.click(screen.getByRole("menuitemradio", { name: /test · model/ }));
    expect(send).toBeDisabled();
    await act(async () => confirmModel({ currentId: liveModel.id, models: [liveModel] }));
    expect(send).toBeEnabled();
    expect(input).toHaveValue("Talk to the real Agent");
    input.focus();
    fireEvent.keyDown(input, { key: "Enter", isComposing: true });
    expect(submitText).not.toHaveBeenCalled();
    (input as HTMLTextAreaElement).setSelectionRange(8, 17);
    await user.keyboard("{Control>}{Enter}{/Control}");
    expect(input).toHaveValue("Talk to \nAgent");
    expect(submitText).not.toHaveBeenCalled();
    await user.keyboard("{Enter}");
    expect(submitText).toHaveBeenCalledWith(expect.objectContaining({
      sessionId: "session-gui",
      text: "Talk to \nAgent",
    }));
    expect(input).toHaveValue("");
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: /Step 1/ })).not.toBeInTheDocument();
  });

  it("lists and changes the live Session model without reconnecting", async () => {
    const user = userEvent.setup();
    const fixture = createMockAppClient();
    const snapshot = await fixture.snapshot();
    const models = {
      currentId: "provider-a:endpoint-a:shared-model",
      models: [
        { id: "provider-a:endpoint-a:shared-model", provider: "provider-a", endpointId: "endpoint-a", modelId: "shared-model", label: "Provider A", supportsThinking: true },
        { id: "provider-b:endpoint-b:shared-model", provider: "provider-b", endpointId: "endpoint-b", modelId: "shared-model", label: "Provider B", supportsThinking: true },
      ],
    } as const;
    const selectModel = vi.fn(async (_sessionId: string, modelId: string, level?: ThinkingLevel): Promise<SessionModels> => ({
      ...models,
      currentId: modelId,
      thinking: { currentLevel: level ?? "medium", availableLevels: ["off", "low", "medium", "high"] },
    }));
    render(<HarnessGui client={{
      snapshot: async () => ({
        ...snapshot,
        connection: "connected",
        source: { kind: "live", serviceInstanceId: "service-live", muxSpaceId: "mux-live", connectionEpoch: "1" },
        sessions: snapshot.sessions.map((session) => ({ ...session, status: "idle" as const })),
      }),
      subscribe: () => () => undefined,
      submitText: async (input) => ({ submissionId: input.submissionId, accepted: true }),
      interrupt: async () => ({ accepted: false }),
      sessionModels: async () => models,
      selectModel,
    }} />);

    const selector = await screen.findByRole("button", { name: "Session model" });
    await waitFor(() => expect(selector).toBeEnabled());
    expect(selector).toHaveTextContent("provider-a · shared-model");
    selector.focus();
    await user.keyboard("{ArrowDown}");
    const first = screen.getByRole("menuitemradio", { name: /provider-a · shared-model/ });
    const second = screen.getByRole("menuitemradio", { name: /provider-b · shared-model/ });
    expect(first).toHaveFocus();
    expect(first).toBeChecked();
    await user.keyboard("{ArrowDown}");
    expect(second).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(selector).toHaveFocus();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    await user.click(selector);
    await user.click(screen.getByRole("menuitemradio", { name: /provider-b · shared-model/ }));
    expect(selectModel).toHaveBeenCalledWith("session-gui", "provider-b:endpoint-b:shared-model");
    const effort = await screen.findByRole("menu", { name: "Reasoning effort" });
    expect(within(effort).getByRole("menuitemradio", { name: "Medium" })).toBeChecked();
    expect(within(effort).getByRole("menuitemradio", { name: "Default" })).toBeVisible();
    await user.click(within(effort).getByRole("menuitemradio", { name: "High" }));
    expect(selectModel).toHaveBeenLastCalledWith("session-gui", "provider-b:endpoint-b:shared-model", "high");
    expect(selector).toHaveTextContent("provider-b · shared-model");
    expect(selector).toHaveTextContent("High");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    await user.click(selector);
    await user.click(screen.getByRole("menuitemradio", { name: /provider-b · shared-model/ }));
    await user.click(screen.getByRole("menuitemradio", { name: "Default" }));
    expect(selectModel).toHaveBeenLastCalledWith("session-gui", "provider-b:endpoint-b:shared-model", "off");
    expect(selector).toHaveTextContent("Default");
  });

  it.each(["empty", "failed"])("blocks sending while the model query is pending or %s", async (result) => {
    const snapshot = await createMockAppClient().snapshot();
    const restored: ClientSnapshot = {
      ...snapshot,
      connection: "connected",
      source: { kind: "live", serviceInstanceId: "service-restored", muxSpaceId: "mux-restored", connectionEpoch: "1" },
      sessions: snapshot.sessions.map((session) => ({ ...session, status: "idle", execution: null })),
    };
    let publish: (snapshot: ClientSnapshot) => void = () => {};
    const choice = { id: "test:primary:confirmed-model", provider: "test", endpointId: "primary", modelId: "confirmed-model", label: "Confirmed model", supportsThinking: false };
    let finishQuery!: (models: SessionModels) => void;
    let failQuery!: (error: Error) => void;
    const sessionModels = vi.fn(() => new Promise<SessionModels>((resolve, reject) => {
      finishQuery = resolve;
      failQuery = reject;
    }));
    const submitText = vi.fn();
    render(<HarnessGui client={{
      snapshot: async () => restored,
      subscribe: () => () => undefined,
      subscribeSnapshots: (listener) => { publish = listener; return () => undefined; },
      submitText,
      interrupt: async () => ({ accepted: false }),
      sessionModels,
    }} />);
    expect(await screen.findByText("Loading models…")).toBeInTheDocument();
    await waitFor(() => expect(sessionModels).toHaveBeenCalledOnce());
    const input = screen.getByRole("textbox", { name: "Message for GUI development" });
    fireEvent.change(input, { target: { value: "Continue this session" } });
    const send = screen.getByRole("button", { name: "Send" });
    expect(send).toBeDisabled();
    act(() => {
      if (result === "empty") finishQuery({ currentId: null, models: [] });
      else failQuery(new Error("Model request failed"));
    });
    expect(await screen.findByText(result === "empty" ? "No models available" : "Model catalog unavailable")).toBeInTheDocument();
    expect(send).toBeDisabled();
    fireEvent.keyDown(input, { key: "Enter" });
    expect(submitText).not.toHaveBeenCalled();
    expect(input).toHaveValue("Continue this session");
    sessionModels.mockResolvedValue({ currentId: choice.id, models: [choice] });
    act(() => publish({
      ...restored,
      sessions: restored.sessions.map((session) => session.id === restored.selectedSessionId ? {
        ...session,
        cursor: "10",
        execution: { id: "restored-turn", status: "succeeded", revision: 1, interruptRequested: false, sourceStatus: "succeeded", finalCursor: 10, truncated: false },
      } : session),
    }));
    expect(await screen.findByText("test · confirmed-model")).toBeInTheDocument();
    expect(send).toBeEnabled();
  });

  it("shows accepted AppHost context without inventing a workspace or repository", async () => {
    const fixture = createMockAppClient();
    const snapshot = await fixture.snapshot();
    const session = snapshot.sessions[0];
    render(<HarnessGui client={{
      snapshot: async () => ({
        ...snapshot,
        connection: "connected",
        source: {
          kind: "live", serviceInstanceId: "service-live", muxSpaceId: "mux-live",
          muxName: "Coding sessions", connectionEpoch: "1",
        },
        capabilities: snapshot.capabilities.map((capability) => ({
          ...capability, availability: "unavailable", version: null,
        })),
        workspaces: [],
        sessions: [{
          ...session, status: "idle", documents: [], run: null, changeSet: null,
          context: {
            ...session.context, project: "coding", source: "live", scope: "cwd",
            scopeFingerprint: "a".repeat(64), muxId: "mux-live",
          },
        }],
        recentSessionIds: [session.id],
        selectedSessionId: session.id,
      }),
      subscribe: () => () => undefined,
      submitText: async (input) => ({ submissionId: input.submissionId, accepted: true }),
      interrupt: async () => ({ accepted: false }),
    }} />);

    await screen.findByRole("heading", { name: session.title });
    const navigation = screen.getByRole("region", { name: "Chats" });
    expect(within(navigation).getByRole("button", { name: `${session.title} · Idle` })).toBeVisible();
    expect(within(navigation).queryByText("Coding sessions")).not.toBeInTheDocument();
    expect(within(navigation).queryByText("Workspace details unavailable")).not.toBeInTheDocument();
    expect(within(navigation).queryByText(/git ·/)).not.toBeInTheDocument();
    const context = within(screen.getByLabelText("Environment summary")).getByLabelText("AppHost session context");
    expect(within(context).getByText("cwd")).toBeVisible();
    expect(within(context).getByText("a".repeat(64))).toBeVisible();
    expect(within(context).getByText("Workspace details unavailable")).toBeVisible();
  });

  it.each([
    { empty: false, refresh: "none" },
    { empty: true, refresh: "none" },
    { empty: false, refresh: "reject" },
    { empty: false, refresh: "timeout" },
  ])("selects a created Session after the replacement snapshot ($empty, $refresh)", async ({ empty, refresh }) => {
    const user = userEvent.setup();
    const fixture = createMockAppClient();
    const fixtureSnapshot = await fixture.snapshot();
    const snapshot: ClientSnapshot = {
      ...fixtureSnapshot,
      connection: "connected",
      source: {
        kind: "live",
        serviceInstanceId: "service-live",
        muxSpaceId: "mux-live",
        connectionEpoch: "1",
      },
      sessions: fixtureSnapshot.sessions.map((session) => ({
        ...session,
        status: "idle" as const,
        context: { ...session.context, source: "live" as const },
      })),
    };
    let publishSnapshot: ((value: ClientSnapshot) => void) | undefined;
    const createSession = vi.fn(async () => ({ sessionId: "session-new" }));
    if (empty) createSession.mockRejectedValueOnce(new Error("creation unavailable"));
    render(<HarnessGui client={{
      snapshot: async () => empty ? { ...snapshot, sessions: [], selectedSessionId: "", recentSessionIds: [] } : snapshot,
      subscribe: () => () => undefined,
      subscribeSnapshots: (listener) => {
        publishSnapshot = listener;
        return () => { publishSnapshot = undefined; };
      },
      submitText: async (input) => ({ submissionId: input.submissionId, accepted: true }),
      interrupt: async () => ({ accepted: false }),
      createSession,
      requestResync: refresh === "reject" ? async () => { throw new Error("refresh unavailable"); }
        : refresh === "timeout" ? () => new Promise<void>(() => undefined)
        : undefined,
    }} />);

    if (empty) await screen.findByText("No Session is available.");
    else await screen.findByRole("heading", { name: "GUI development" });
    if (refresh === "timeout") {
      vi.useFakeTimers();
      try {
        await act(async () => { fireEvent.click(screen.getByRole("button", { name: "New Session" })); });
        expect(screen.getByRole("button", { name: "Creating…" })).toBeDisabled();
        await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
      } finally {
        vi.useRealTimers();
      }
    } else {
      await user.click(screen.getByRole("button", { name: "New Session" }));
    }
    if (empty) {
      expect(await screen.findByText("New Session could not be created.")).toBeVisible();
      await user.click(screen.getByRole("button", { name: "New Session" }));
    }
    expect(createSession).toHaveBeenCalledWith({
      sourceSessionId: empty ? undefined : "session-gui",
      title: "New Session",
    });
    if (refresh !== "none") {
      expect(await screen.findByText("New Session was created, but it could not be shown yet.")).toBeVisible();
      expect(screen.getByRole("button", { name: "New Session" })).toBeEnabled();
      expect(createSession).toHaveBeenCalledTimes(1);
    } else {
      expect(screen.getByRole("button", { name: "Creating…" })).toBeDisabled();
    }

    const source = snapshot.sessions[0];
    const created = {
      ...source,
      id: "session-new",
      title: "New Session",
      context: {
        ...source.context,
        memberId: "member-new",
        sessionId: "session-new",
      },
    };
    await act(async () => {
      publishSnapshot?.({
        ...snapshot,
        generation: "2",
        sessions: [...snapshot.sessions, created],
        recentSessionIds: ["session-new", ...snapshot.recentSessionIds],
        selectedSessionId: "session-new",
      });
    });
    expect(screen.getByRole("heading", { name: "New Session" })).toBeVisible();
    expect(screen.getByText("New Session created and attached.")).toBeVisible();
  });

  it("navigates three Workspace kinds and preserves per-Session drafts", async () => {
    const user = userEvent.setup();
    render(<HarnessGui client={createMockAppClient()} />);

    await screen.findByRole("heading", { name: "GUI development" });
    expect(screen.getAllByText("git · main")[0]).toBeVisible();
    expect(screen.getByText("svn · trunk")).toBeVisible();
    expect(screen.getByText("plain")).toBeVisible();
    expect(screen.getByRole("button", { name: "GUI development · Running" })).toBeVisible();

    const guiInput = screen.getByRole("textbox", { name: "Message for GUI development" });
    await user.type(guiInput, "GUI draft");
    await user.click(screen.getByRole("button", { name: "Operational ontology · Idle" }));
    const ontologyInput = screen.getByRole("textbox", { name: "Message for Operational ontology" });
    expect(ontologyInput).toHaveValue("");
    await user.type(ontologyInput, "Ontology draft");

    await user.click(screen.getByRole("button", { name: "GUI development · Running" }));
    expect(screen.getByRole("textbox", { name: "Message for GUI development" })).toHaveValue("GUI draft");

    const loushang = screen.getByRole("button", { name: /Loushang.*git.*main/ });
    await user.click(loushang);
    expect(screen.queryByRole("button", { name: "GUI development · Running" })).not.toBeInTheDocument();
    await user.click(loushang);
    expect(screen.getByRole("button", { name: "GUI development · Running" })).toBeVisible();
  });

  it("expands Run activities and advances the current Task", async () => {
    const user = userEvent.setup();
    const client = createMockAppClient();
    render(<HarnessGui client={client} />);
    await screen.findByRole("heading", { name: "GUI development" });

    const progress = screen.getByRole("button", { name: "Step 1 / 4" });
    await user.click(progress);
    const taskList = screen.getByLabelText("Run tasks");
    expect(within(taskList).getByRole("button", { name: /Inspect GUI workspace/ })).toBeVisible();

    const activity = screen.getByRole("button", { name: /Build the Workspace.*Activities: 3/ });
    await user.click(activity);
    const timeline = screen.getByLabelText("Run activity");
    expect(within(timeline).getByText(/rg -n.*SessionSnapshot/)).toBeVisible();

    await user.click(screen.getByText(/Fixture playback ·/));
    const advance = screen.getByRole("button", { name: "Advance fixture" });
    await user.click(advance);
    expect(within(timeline).getByText("Fixture tool call · no repository access")).toBeVisible();
    await user.click(advance);
    expect(screen.getByRole("button", { name: "Step 2 / 4" })).toBeVisible();

    while (client.remainingFixtureSteps() > 0) await user.click(advance);
    expect(screen.getByRole("button", { name: "4 / 4 complete" })).toBeVisible();
    expect(screen.getByRole("button", { name: "GUI development · Idle" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Open Work Dock" }));
    const dock = screen.getByLabelText("Work Dock");
    await user.click(within(dock).getByRole("button", { name: "Subagents" }));
    const agents = within(dock).getByLabelText("AgentRun details");
    await user.click(within(agents).getByRole("button", { name: /Interface reviewer.*completed/ }));
    expect(within(agents).getByText(/Confirmed the Product-neutral UI boundary/)).toBeVisible();
  });

  it("moves from ChangeSet quick look to full Review and cross-links Task and AgentRun", async () => {
    const user = userEvent.setup();
    render(<HarnessGui client={createMockAppClient()} />);
    await screen.findByRole("heading", { name: "GUI development" });

    const changes = screen.getByLabelText("Fixture changes");
    const fileButton = within(changes).getByRole("button", { name: /gui-interface-specification\.md/ });
    await user.click(fileButton);
    const quickLook = screen.getByLabelText("Quick look gui-interface-specification.md");
    expect(within(quickLook).getByText(/Activity groups retain their Run/)).toBeVisible();
    await user.click(within(quickLook).getByRole("button", { name: "Close quick look" }));
    expect(fileButton).toHaveFocus();

    await user.click(fileButton);
    const reopenedQuickLook = screen.getByLabelText("Quick look gui-interface-specification.md");
    await user.click(within(reopenedQuickLook).getByRole("button", { name: "Open full review →" }));

    const dock = screen.getByLabelText("Work Dock");
    const review = within(dock).getByLabelText("Read-only review");
    expect(within(review).getByRole("article", { name: "gui-interface-specification.md" })).toBeVisible();
    expect(within(review).getByRole("button", { name: "Commit or push" })).toBeDisabled();

    await user.click(within(dock).getByRole("button", { name: "Tasks" }));
    const taskPanel = within(dock).getByLabelText("Task details");
    await user.click(within(taskPanel).getByRole("button", { name: /Inspect GUI workspace/ }));
    await user.click(within(taskPanel).getByRole("button", { name: "Open Primary agent →" }));
    const agentPanel = within(dock).getByLabelText("AgentRun details");
    expect(within(agentPanel).getByText("Owns the fixture implementation and verification.")).toBeVisible();
    await user.click(within(agentPanel).getByRole("button", { name: /Open Inspect GUI workspace/ }));
    expect(within(dock).getByLabelText("Task details")).toBeVisible();
  });
});
