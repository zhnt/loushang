import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { HarnessGui } from "../../src/App";
import { MessageMarkdown } from "../../src/markdown/MessageMarkdown";
import { projectNativeInitialSnapshot } from "../../src/client/nativeLiveClient";
import { createMockAppClient } from "../support/mockAppClient";
import { liveSnapshot } from "../support/liveSnapshot";
import type { ClientSnapshot, CreateSessionReceipt, FixturePlaybackPort, HarnessClientUiPort, SessionModels, ThinkingLevel } from "../../src/client/model";

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
  it("reveals a temporary Session artifact directly without reading its preview", async () => {
    const raw = liveSnapshot();
    raw.sessions[0].source.source.records[1].text = "已完成：index.html";
    const snapshot = projectNativeInitialSnapshot(raw);
    const previewWorkspace = vi.fn();
    const openProjectPath = vi.fn().mockResolvedValue({ fileMissing: true });
    const client: HarnessClientUiPort = {
      snapshot: async () => snapshot,
      subscribe: () => () => {},
      submitText: async ({ submissionId }) => ({ accepted: false, submissionId }),
      interrupt: async () => ({ accepted: false }),
      previewWorkspace,
    };
    const session = snapshot.sessions[0];
    render(<HarnessGui client={client}
      managedHostConnection={{ status: "running", serviceInstanceId: "service-1" }}
      projectNavigation={{
        hostKey: "local", directory: { projects: [], temporarySessions: [] }, available: true,
        pending: false, error: false, folderInput: false, selection: { workspace: "@temporary", id: session.id },
        openFolder: () => {}, closeFolder: () => {}, register: async () => false,
        createChat: async () => null, togglePin: () => {}, select: () => {}, openProjectPath,
      }} />);
    const artifact = await screen.findByRole("button", { name: "index.html" });
    expect(artifact).not.toHaveAttribute("aria-haspopup");
    fireEvent.click(artifact);
    expect(await screen.findByText("File not found. Opened the nearest existing folder.")).toBeVisible();
    expect(openProjectPath).toHaveBeenCalledExactlyOnceWith("@temporary", "a".repeat(64), "index.html");
    expect(previewWorkspace).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens desktop Markdown links through the system browser bridge and reports failures", async () => {
    const url = "https://example.org/search?q=weather#results";
    const invoke = vi.fn().mockResolvedValueOnce(undefined).mockRejectedValueOnce("open_failed");
    vi.stubGlobal("isTauri", true);
    vi.stubGlobal("__TAURI_INTERNALS__", { invoke });
    try {
      render(<MessageMarkdown text={`[Reference](${url})`} />);
      const link = screen.getByRole("link", { name: "Reference" });
      fireEvent.click(link);
      expect(invoke).toHaveBeenCalledWith("open_web_link", { url }, undefined);
      fireEvent.click(link);
      expect(await screen.findByRole("alert")).toHaveTextContent("Could not open the link in the system browser.");
    } finally {
      vi.unstubAllGlobals();
    }
  });

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
    await user.click(screen.getByRole("button", { name: "Execution" }));
    const current = within(screen.getByRole("region", { name: "Current work" }));
    expect(current.getByText("No work is running.")).toBeVisible();
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
    await user.click(within(screen.getByLabelText("Session transcript")).getByText(/^Execution failed$/i));
    const recent = within(screen.getByRole("region", { name: "Most recent execution" }));
    expect(recent.getByText("Failed", { exact: true })).toBeVisible();
    await user.click(recent.getByRole("button", { name: "View conversation" }));
    expect(screen.getByLabelText("Session transcript")).toHaveFocus();
    await user.click(recent.getByText("Execution details"));
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
    await user.click(screen.getByRole("button", { name: "Execution" }));
    const dock = screen.getByLabelText("Work Dock");
    expect(within(dock).queryByRole("button", { name: "Subagents" })).not.toBeInTheDocument();
    expect(within(dock).queryByLabelText("Task details")).not.toBeInTheDocument();
    await user.click(within(dock).getByRole("button", { name: "Review" }));
    expect(within(dock).getByText(/Review capability/)).toBeVisible();
    view.rerender(<HarnessGui client={withSnapshot(client, snapshot)} />);
    expect(await screen.findByLabelText("Fixture changes")).toBeVisible();
    expect(screen.getByLabelText("Read-only review")).toBeVisible();
  });

  it("sends, streams, interrupts and starts another fixture Run", async () => {
    const user = userEvent.setup();
    const client = createMockAppClient();
    render(<HarnessGui client={client} />);
    await screen.findByRole("heading", { name: "GUI development" });
    await user.click(screen.getByLabelText("Operational ontology · Idle"));
    const input = screen.getByRole("textbox", { name: "Message for Operational ontology" });
    fireEvent.change(input, { target: { value: "Test streaming" } });
    await user.click(screen.getByLabelText("Send"));
    expect(input).toHaveValue("");
    expect(screen.queryByRole("button", { name: "Send" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Interrupt" })).toBeEnabled();
    // The global fixture queue also contains events for the inactive GUI Session.
    for (let steps = 0; steps < 30 && !screen.queryByText(/The GUI keeps a separate client scope/); steps++) {
      await act(async () => { await client.advanceFixture(); });
    }
    expect(screen.getByText(/The GUI keeps a separate client scope/)).toBeVisible();
    await user.click(screen.getByLabelText("Interrupt"));
    expect(screen.getByRole("button", { name: "Operational ontology · Interrupted" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Interrupt" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    fireEvent.change(input, { target: { value: "Complete another Run" } });
    await user.click(screen.getByLabelText("Send"));
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
    expect(screen.getByText("Disconnected", { exact: true })).toHaveAttribute("title", "Resync required");
    expect(screen.getByText("Synchronization interrupted. Resynchronize to continue.")).toBeVisible();
  });

  it("shows the managed Host status before any conversation is open", async () => {
    const { container, rerender } = render(<HarnessGui client={null} managedHostConnection={{ status: "connecting" }} />);
    const chip = () => container.querySelector(".connection-chip");
    expect(chip()).toHaveClass("connecting");
    expect(chip()).toHaveTextContent(/^Connecting$/);
    rerender(<HarnessGui client={null} managedHostConnection={{ status: "running", serviceInstanceId: "host" }} />);
    expect(chip()).toHaveClass("connected");
    expect(chip()).toHaveTextContent(/^Connected$/);
    await act(async () => rerender(<HarnessGui client={null} managedHostConnection={{ status: "disconnected" }} />));
    expect(chip()).toHaveClass("disconnected");
    expect(chip()).toHaveTextContent(/^Disconnected$/);
  });

  it("reports a lost live connection until a fresh snapshot arrives", async () => {
    const snapshot = projectNativeInitialSnapshot(liveSnapshot());
    let resolveInitial!: (value: ClientSnapshot) => void;
    const initial = new Promise<ClientSnapshot>((resolve) => { resolveInitial = resolve; });
    let notify!: Parameters<NonNullable<HarnessClientUiPort["subscribeConnection"]>>[0];
    let publish!: (value: ClientSnapshot) => void;
    const client: HarnessClientUiPort = {
      snapshot: () => initial,
      subscribe: () => () => {},
      subscribeConnection: (listener) => { notify = listener; return () => {}; },
      subscribeSnapshots: (listener) => { publish = listener; return () => {}; },
      submitText: async ({ submissionId }) => ({ accepted: false, submissionId }),
      interrupt: async () => ({ accepted: false }),
    };
    const { container } = render(<HarnessGui client={client}
      managedHostConnection={{ status: "running", serviceInstanceId: "service-1" }} />);
    const chip = () => container.querySelector(".connection-chip");
    expect(chip()).toHaveTextContent(/^Connecting$/);
    act(() => notify("disconnected"));
    expect(chip()).toHaveClass("disconnected");
    expect(chip()).toHaveTextContent(/^Disconnected$/);
    await act(async () => resolveInitial(snapshot));
    expect(chip()).toHaveTextContent(/^Disconnected$/);
    act(() => publish(snapshot));
    expect(chip()).toHaveTextContent(/^Connected$/);
    act(() => notify("disconnected"));
    expect(chip()).toHaveTextContent(/^Disconnected$/);
    act(() => publish(snapshot));
    expect(chip()).toHaveTextContent(/^Connected$/);
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
      thinking: { currentLevel: level ?? null, availableLevels: ["off", "xhigh", "max"] },
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
    expect(selector).toHaveTextContent("Default");
    expect(within(effort).getByRole("menuitemradio", { name: "Extra high" })).not.toBeChecked();
    expect(within(effort).queryByRole("menuitemradio", { name: "Medium" })).not.toBeInTheDocument();
    await user.click(within(effort).getByRole("menuitemradio", { name: "Maximum" }));
    expect(selectModel).toHaveBeenLastCalledWith("session-gui", "provider-b:endpoint-b:shared-model", "max");
    expect(selector).toHaveTextContent("provider-b · shared-model");
    expect(selector).toHaveTextContent("Maximum");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    await user.click(selector);
    await user.click(screen.getByRole("menuitemradio", { name: /provider-b · shared-model/ }));
    await user.click(screen.getByRole("menuitemradio", { name: "Off" }));
    expect(selectModel).toHaveBeenLastCalledWith("session-gui", "provider-b:endpoint-b:shared-model", "off");
    expect(selector).toHaveTextContent("Off");
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
    expect(within(context).getByText("a".repeat(64))).not.toBeVisible();
    fireEvent.click(within(context).getByText("Technical details"));
    expect(within(context).getByText("cwd")).toBeVisible();
    expect(within(context).getByText("a".repeat(64))).toBeVisible();
    const user = userEvent.setup();
    const copy = within(context).getByRole("button", { name: "Copy Scope fingerprint" });
    expect(copy).not.toHaveTextContent("Copy");
    await user.click(copy);
    expect(await navigator.clipboard.readText()).toBe("a".repeat(64));
    expect(within(context).getByText("Workspace details unavailable")).toBeVisible();
  });

  it("opens and focuses a blank draft without creating a Session", async () => {
    const initial = await createMockAppClient().snapshot();
    const createSession = vi.fn(async () => ({ sessionId: "new-session" }));
    render(<HarnessGui client={{
      snapshot: async () => ({
        ...initial, connection: "connected",
        source: { kind: "live", serviceInstanceId: "draft-host", muxSpaceId: "draft-mux", connectionEpoch: "1" },
      }),
      createSession,
      subscribe: () => () => {},
      submitText: async ({ submissionId }) => ({ accepted: true, submissionId }),
      interrupt: async () => ({ accepted: false }),
    }} />);
    const start = await screen.findByRole("button", { name: "New Session" });
    await waitFor(() => expect(start).toBeEnabled());
    const heading = screen.getByRole("heading", { name: "New Session" });
    const transcript = screen.getByLabelText("Session transcript");
    const input = screen.getByRole("textbox");
    const model = screen.getByRole("button", { name: "Session model" });
    expect(createSession).not.toHaveBeenCalled();
    expect(within(screen.getByRole("navigation", { name: "Chats" })).queryByRole("button", { name: "New Session" })).toBeNull();
    expect(screen.getByLabelText("Session transcript")).toBe(transcript);
    expect(within(transcript).getByRole("heading", { name: "What would you like to work on?" })).toBeVisible();
    expect(within(transcript).queryByRole("article")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Session model" })).toBe(model);
    expect(model).toBeDisabled();
    expect(screen.getByText("Default model")).toBeVisible();
    expect(screen.getByRole("button", { name: /^GUI development ·/ })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("textbox")).toBe(input);
    expect(input).toHaveFocus();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Keep this draft" } });
    fireEvent.click(screen.getByRole("button", { name: /^GUI development ·/ }));
    expect(screen.getByRole("heading", { name: "GUI development" })).toBe(heading);
    fireEvent.click(start);
    expect(screen.getByRole("textbox")).toHaveValue("Keep this draft");
    fireEvent.click(screen.getByRole("button", { name: /^GUI development ·/ }));
    expect(createSession).not.toHaveBeenCalled();
    fireEvent.click(start);
    expect(screen.getByRole("textbox")).toHaveValue("Keep this draft");
  });

  it("keeps unsent text separate by Host and project without creating a Session", async () => {
    const seed = await createMockAppClient().snapshot();
    const snapshot: ClientSnapshot = {
      ...seed, connection: "connected", sessions: [], selectedSessionId: "",
      source: { kind: "live", serviceInstanceId: "drafts", muxSpaceId: "drafts", connectionEpoch: "1" },
    };
    const client: HarnessClientUiPort = {
      snapshot: async () => snapshot, subscribe: () => () => {},
      submitText: async ({ submissionId }) => ({ accepted: true, submissionId }),
      interrupt: async () => ({ accepted: false }),
    };
    const createChat = vi.fn(async () => null);
    const props = (hostKey: string) => ({
      client,
      projectNavigation: {
        hostKey, directory: { projects: [{ path: "/work/alpha", sessions: [] },
          { path: "/work/beta", sessions: [] }], temporarySessions: [] },
        available: true, pending: false, error: false, folderInput: false, selection: null,
        openFolder: () => {}, closeFolder: () => {}, register: async () => false,
        createChat, togglePin: () => {}, select: () => {},
      },
    });
    const { rerender } = render(<HarnessGui {...props("host-a")} />);
    const open = (project: string) => fireEvent.click(screen.getByRole("button", { name: `New chat in ${project}` }));
    open("alpha");
    expect(screen.getByRole("heading", { name: "alpha / New Session" })).toBeVisible();
    expect(within(screen.getByRole("region", { name: "Projects" })).queryByRole("button", { name: "New Session" })).toBeNull();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Alpha draft" } });
    open("beta");
    expect(screen.getByRole("textbox")).toHaveValue("");
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Beta draft" } });
    rerender(<HarnessGui {...props("host-b")} />);
    open("alpha");
    expect(screen.getByRole("textbox")).toHaveValue("");
    rerender(<HarnessGui {...props("host-a")} />);
    open("alpha");
    expect(screen.getByRole("textbox")).toHaveValue("Alpha draft");
    open("beta");
    expect(screen.getByRole("textbox")).toHaveValue("Beta draft");
    const input = screen.getByRole("textbox");
    fireEvent.compositionStart(input);
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.compositionEnd(input);
    expect(createChat).not.toHaveBeenCalled();
  });

  it.each(["none", "model", "reasoning"] as const)(
    "applies the draft model and effort before sending (first rejection: %s)",
    async (rejection) => {
    const inputSnapshot = await createMockAppClient().snapshot();
    const defaultModel = { ...liveModel, supportsThinking: true };
    const second = { ...liveModel, id: "test:primary:second", modelId: "second", supportsThinking: true };
    const choices: SessionModels = { currentId: defaultModel.id, models: [defaultModel, second] };
    const defaultModels = vi.fn(async (_path: string | null, id?: string): Promise<SessionModels> => id === second.id
      ? { ...choices, currentId: id, thinking: { currentLevel: null, availableLevels: ["high", "max"] } }
      : id === defaultModel.id
        ? { ...choices, thinking: { currentLevel: "high", availableLevels: ["low", "high"] } }
      : choices);
    let snapshot: ClientSnapshot = {
      ...inputSnapshot,
      connection: "connected",
      source: { kind: "live", serviceInstanceId: "host", muxSpaceId: "workspace", connectionEpoch: "1" },
      sessions: [], selectedSessionId: "", recentSessionIds: [],
    };
    let publish: ((value: ClientSnapshot) => void) | undefined;
    let activeModel = liveModel.id;
    let activeLevel: ThinkingLevel | null = null;
    let rejected = false;
    const settings = (): SessionModels => ({ ...choices, currentId: activeModel, thinking: activeModel === second.id
      ? { currentLevel: activeLevel, availableLevels: ["high", "max"] } : undefined });
    const selectModel = vi.fn(async (_sessionId: string, modelId: string, level?: ThinkingLevel) => {
      if (!rejected && rejection === (level === undefined ? "model" : "reasoning")) {
        rejected = true;
        return settings();
      }
      activeModel = modelId;
      if (level !== undefined) activeLevel = level;
      return settings();
    });
    const submitText = vi.fn<HarnessClientUiPort["submitText"]>(async ({ submissionId }) => {
      expect(activeModel).toBe(second.id);
      expect(activeLevel).toBe("max");
      return { accepted: true, submissionId };
    });
    const client: HarnessClientUiPort = {
      snapshot: async () => snapshot,
      subscribe: () => () => {},
      subscribeSnapshots: (listener) => { publish = listener; return () => {}; },
      interrupt: async () => ({ accepted: false }),
      sessionModels: async () => settings(),
      selectModel, submitText,
    };
    const createChat = vi.fn(async (_path: string | null, continuityId: string) => {
      const session = {
        ...inputSnapshot.sessions[0], id: "first-model", title: "New Session", messages: [],
        context: { ...inputSnapshot.sessions[0].context, continuityId },
      };
      snapshot = { ...snapshot, sessions: [session], selectedSessionId: session.id };
      return {
        client, sessionId: session.id,
        show: () => { publish?.(snapshot); return true; },
      };
    });
    const previousChats = ["earlier", "later"].map((id) => ({ id, title: "Repeated title", scope: "temporary", pinned: false }));
    const projectNavigation = {
      hostKey: "local", directory: { projects: [], temporarySessions: previousChats }, available: true,
      pending: false, error: false, folderInput: false, selection: null,
      openFolder: () => {}, closeFolder: () => {}, register: async () => false,
      createChat, draftModels: defaultModels, togglePin: () => {}, select: () => {},
    };
    const managedHostConnection = { status: "running", serviceInstanceId: "host" } as const;
    const { rerender } = render(<HarnessGui client={client} managedHostConnection={managedHostConnection}
      projectNavigation={projectNavigation} />);
    const chats = within(screen.getByRole("region", { name: "Chats" }));
    expect(chats.getAllByRole("button", { name: "Repeated title" })).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "New Session" }));
    expect(chats.queryByRole("button", { name: "New Session" })).toBeNull();
    const welcome = screen.getByRole("heading", { name: "What would you like to work on?" });
    expect(welcome).toBeVisible();
    expect(screen.getByRole("textbox")).toHaveFocus();
    const picker = screen.getByRole("button", { name: "Session model" });
    await waitFor(() => expect(picker).toHaveTextContent(/test · model\s*High/));
    expect(defaultModels).toHaveBeenCalledWith(null);
    expect(defaultModels).toHaveBeenCalledWith(null, defaultModel.id);
    const goal = screen.getByRole("button", { name: "Development goal" });
    fireEvent.click(goal);
    expect(screen.getByText(/Send an ordinary message/)).toBeVisible();
    expect(createChat).not.toHaveBeenCalled();
    fireEvent.click(goal);
    expect(screen.getByText(/Send an ordinary message/)).not.toBeVisible();
    fireEvent.click(picker);
    fireEvent.click(screen.getByRole("menuitemradio", { name: /test · second/ }));
    await waitFor(() => expect(picker).toHaveTextContent("test · second"));
    const effort = await screen.findByRole("menu", { name: "Reasoning effort" });
    fireEvent.click(within(effort).getByRole("menuitemradio", { name: "Maximum" }));
    expect(picker).toHaveTextContent("Maximum");
    expect(createChat).not.toHaveBeenCalled();
    expect(selectModel).not.toHaveBeenCalled();
    expect(submitText).not.toHaveBeenCalled();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Use the selected model" } });
    expect(screen.getByRole("heading", { name: "New Session" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    const transcript = within(screen.getByLabelText("Session transcript"));
    expect(transcript.getByText("Use the selected model")).toBeVisible();
    expect(transcript.getByText("Creating Session…")).toBeVisible();
    expect(welcome).not.toBeInTheDocument();
    expect(screen.getByText("Connected", { exact: true })).toBeVisible();
    expect(screen.getByRole("textbox")).toHaveValue("");
    expect(screen.getByRole("heading", { name: "Use the selected model" })).toBeVisible();
    expect(chats.queryByRole("button", { name: "Use the selected model" })).toBeNull();
    if (rejection !== "none") {
      expect(await screen.findByText(rejection === "model"
        ? "The selected model could not be applied. Your draft is saved."
        : "The selected reasoning effort could not be applied. Your draft is saved.")).toBeVisible();
      expect(submitText).not.toHaveBeenCalled();
      expect(screen.getByRole("textbox")).toHaveValue("Use the selected model");
      rerender(<HarnessGui client={client} managedHostConnection={managedHostConnection} projectNavigation={{
        ...projectNavigation, directory: { projects: [], temporarySessions: [
          { id: snapshot.sessions[0].id, title: "New Session", scope: "temporary", pinned: false }, ...previousChats,
        ] },
      }} />);
      expect(chats.queryByRole("button", { name: "New Session" })).toBeNull();
      fireEvent.click(screen.getByRole("button", { name: "Send" }));
    }
    await waitFor(() => expect(submitText).toHaveBeenCalledOnce());
    expect(await transcript.findByText("Waiting for a reply…")).toBeVisible();
    expect(chats.getByRole("button", { name: "Use the selected model" })).toHaveAttribute("aria-current", "true");
    expect(transcript.getAllByText("Use the selected model")).toHaveLength(1);

    const session = snapshot.sessions[0];
    const entry = { id: session.id, title: "New Session", scope: "temporary", pinned: false };
    rerender(<HarnessGui client={client} managedHostConnection={managedHostConnection} projectNavigation={{
      ...projectNavigation, directory: { projects: [], temporarySessions: [entry, ...previousChats] },
      selection: { workspace: "@temporary", id: session.id },
    }} />);
    expect(screen.getByRole("heading", { name: "Use the selected model" })).toBeVisible();
    expect(chats.getByRole("button", { name: "Use the selected model" })).toBeVisible();
    const message = { id: "first-user", role: "user", phase: "sent", content: "Use the selected model" } as const;
    const titled = { ...session, title: message.content };
    act(() => publish?.({ ...snapshot, sessions: [{ ...titled, cursor: "first-user", messages: [message] }] }));
    expect(transcript.getAllByText("Use the selected model")).toHaveLength(1);
    expect(transcript.getByText("Waiting for a reply…")).toBeVisible();
    const reply = { id: "first-assistant", role: "assistant", phase: "streaming", content: "First reply" } as const;
    const replied = { ...titled, cursor: "first-assistant", messages: [message, reply] };
    act(() => publish?.({ ...snapshot, sessions: [replied] }));
    expect(transcript.getByText("First reply")).toBeVisible();
    expect(transcript.queryByText("Waiting for a reply…")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: message.content })).toBeVisible();
    act(() => publish?.({ ...snapshot, sessions: [{ ...replied, title: "Model selection summary" }] }));
    expect(screen.getByRole("heading", { name: "Model selection summary" })).toBeVisible();
    expect(chats.getByRole("button", { name: "Model selection summary" })).toBeVisible();
    expect(transcript.getByText(message.content)).toBeVisible();
    expect(createChat).toHaveBeenCalledExactlyOnceWith(null, expect.any(String), "New Session");
    expect(selectModel.mock.calls).toEqual([
      ["first-model", second.id],
      ...(rejection === "model" ? [["first-model", second.id]] : []),
      ["first-model", second.id, "max"],
      ...(rejection === "reasoning" ? [["first-model", second.id, "max"]] : []),
    ]);
  });

  it.each(["rejected", "lost-create", "unconfirmed-create", "rejected-submit", "lost-submit"] as const)(
    "binds first send to the confirmed Session and preserves the draft on %s",
    async (failure) => {
      const seed = await createMockAppClient().snapshot();
      let snapshot: ClientSnapshot = {
        ...seed, connection: "connected",
        source: { kind: "live", serviceInstanceId: "draft-host", muxSpaceId: "draft-mux", connectionEpoch: "1" },
        sessions: [],
        selectedSessionId: "",
        recentSessionIds: [],
      };
      let feed: ((value: ClientSnapshot) => void) | undefined;
      const createSession = vi.fn(async (input: { continuityId?: string }): Promise<CreateSessionReceipt> => {
        if (failure === "rejected" && createSession.mock.calls.length === 1) return { rejected: true };
        const created = {
          ...seed.sessions[0], id: "session-new", title: "New Session", messages: [],
          context: {
            ...seed.sessions[0].context, sessionId: "session-new",
            continuityId: failure === "unconfirmed-create" ? "some-other-create" : input.continuityId,
          },
        };
        snapshot = { ...snapshot, sessions: [created], selectedSessionId: created.id };
        if (failure === "lost-create" || failure === "unconfirmed-create") {
          throw new Error("disconnected during create");
        }
        return { sessionId: created.id };
      });
      const submitText = vi.fn<HarnessClientUiPort["submitText"]>(async ({ submissionId }) => {
        if (failure === "lost-submit") throw new Error("response lost");
        if (failure === "rejected-submit" && submitText.mock.calls.length === 1) {
          return { accepted: false, submissionId, reason: "operation_unavailable" };
        }
        return { accepted: true, submissionId, executionId: "execution-new" };
      });
      render(<HarnessGui client={{
        snapshot: async () => snapshot,
        subscribe: () => () => {},
        subscribeSnapshots: (listener) => { feed = listener; return () => {}; },
        submitText, createSession,
        requestResync: async () => { feed?.(snapshot); },
        interrupt: async () => ({ accepted: false }),
      }} />);
      const start = await screen.findByRole("button", { name: "New Session" });
      await waitFor(() => expect(start).toBeEnabled());
      fireEvent.click(start);
      const input = screen.getByRole("textbox");
      const transcript = screen.getByLabelText("Session transcript");
      const heading = screen.getByRole("heading", { name: "New Session" });
      const model = screen.getByRole("button", { name: "Session model" });
      fireEvent.change(input, { target: { value: "First message" } });
      const send = screen.getByRole("button", { name: "Send" });
      if (failure === "unconfirmed-create") {
        vi.useFakeTimers();
        try {
          await act(async () => { fireEvent.click(send); });
          await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
          expect(screen.getByText("Session creation is unconfirmed. Your draft is saved.")).toBeVisible();
          expect(input).toHaveValue("First message");
          await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Check creation status" })); });
          await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
          expect(createSession).toHaveBeenCalledTimes(1);
          expect(submitText).not.toHaveBeenCalled();
        } finally {
          vi.useRealTimers();
        }
        return;
      }
      fireEvent.click(send);
      fireEvent.submit(input.closest("form")!);
      expect(createSession).toHaveBeenCalledTimes(1);
      if (failure === "rejected") {
        expect(await screen.findByText("New Session could not be created.")).toBeVisible();
        expect(input).toHaveValue("First message");
        expect(submitText).not.toHaveBeenCalled();
        fireEvent.click(send);
      }
      await waitFor(() => expect(submitText).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({
        sessionId: "session-new", text: "First message",
      })));
      if (failure === "rejected-submit") {
        expect(await screen.findByText("The first message was rejected. Your draft is saved.")).toBeVisible();
        expect(input).toHaveValue("First message");
        fireEvent.click(send);
        await waitFor(() => expect(submitText).toHaveBeenCalledTimes(2));
        expect(submitText.mock.calls[1][0].sessionId).toBe("session-new");
        expect(createSession).toHaveBeenCalledTimes(1);
      }
      if (failure === "lost-submit") {
        expect(await screen.findByText("The first message outcome is unknown. Your draft is saved.")).toBeVisible();
        expect(input).toHaveValue("First message");
        expect(send).toBeDisabled();
        expect(screen.queryByRole("button", { name: /^New Session ·/ })).toBeNull();
        fireEvent.submit(input.closest("form")!);
        expect(submitText).toHaveBeenCalledTimes(1);
        expect(createSession).toHaveBeenCalledTimes(1);
      } else {
        await waitFor(() => expect(input).toHaveValue(""));
        expect(screen.getByRole("textbox")).toBe(input);
        expect(screen.getByLabelText("Session transcript")).toBe(transcript);
        expect(screen.getByRole("heading", { name: "First message" })).toBe(heading);
        expect(screen.getByRole("button", { name: "Session model" })).toBe(model);
      }
    },
  );

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
    const taskList = screen.getByLabelText("Task details");
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
    expect(screen.getByRole("button", { name: /^GUI development ·/ })).toBeVisible();
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

    await user.click(within(dock).getByRole("button", { name: "Execution" }));
    const taskPanel = within(dock).getByLabelText("Task details");
    await user.click(within(taskPanel).getByRole("button", { name: /Inspect GUI workspace/ }));
    await user.click(within(taskPanel).getByRole("button", { name: "Open Primary agent →" }));
    const agentPanel = within(dock).getByLabelText("AgentRun details");
    expect(within(agentPanel).getByText("Owns the fixture implementation and verification.")).toBeVisible();
    await user.click(within(agentPanel).getByRole("button", { name: /Open Inspect GUI workspace/ }));
    expect(within(dock).getByLabelText("Task details")).toBeVisible();
  });
});

it("keeps approvals in their own session and removes them on dismissal or disconnect", async () => {
  const fixture = await createMockAppClient().snapshot();
  const [a, b] = fixture.sessions;
  const session = {
    ...a,
    status: "idle" as const,
    pendingApprovals: [{ sessionId: a.id, interactionId: "test-approval", text: "Preview operation", status: "pending" as const }],
  };
  const snapshot: ClientSnapshot = {
    ...fixture, connection: "connected", selectedSessionId: a.id,
    source: { kind: "live", serviceInstanceId: "approval-host", muxSpaceId: "approval-mux", connectionEpoch: "1" },
    sessions: [session, { ...b, status: "idle" }],
  };
  let feed!: (snapshot: ClientSnapshot) => void;
  let disconnect!: (state: "disconnected") => void;
  const respondInteraction = vi.fn().mockResolvedValue({ accepted: true });
  const client: HarnessClientUiPort = {
    snapshot: async () => snapshot,
    subscribe: () => () => {},
    subscribeSnapshots: (listener) => { feed = listener; return () => {}; },
    subscribeConnection: (listener) => { disconnect = listener; return () => {}; },
    submitText: async ({ submissionId }) => ({ submissionId, accepted: false }),
    interrupt: async () => ({ accepted: false }),
    respondInteraction,
  };
  render(<HarnessGui client={client} />);
  const approval = await screen.findByRole("region", { name: "Tool approval" });
  fireEvent.click(screen.getByRole("button", { name: "Execution" }));
  fireEvent.click(screen.getByRole("button", { name: "Go to tool approval" }));
  expect(approval).toHaveFocus();
  fireEvent.click(screen.getByRole("button", { name: `${b.title} · Idle` }));
  expect(screen.queryByRole("button", { name: "Go to tool approval" })).not.toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Tool approval" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: `${a.title} · Idle` }));
  fireEvent.click(screen.getByRole("button", { name: "Cancel operation" }));
  expect(respondInteraction).toHaveBeenCalledExactlyOnceWith(a.id, "test-approval", "cancel");
  act(() => feed({ ...snapshot, sessions: [{ ...session, pendingApprovals: [] }, snapshot.sessions[1]] }));
  expect(screen.queryByRole("region", { name: "Tool approval" })).not.toBeInTheDocument();
  act(() => feed(snapshot));
  await screen.findByRole("region", { name: "Tool approval" });
  act(() => disconnect("disconnected"));
  expect(screen.queryByRole("region", { name: "Tool approval" })).not.toBeInTheDocument();
});

describe("Hosted business choices", () => {
  it("preserves an uncertain answer and waits for the authority to clear the question", async () => {
    const seed = await createMockAppClient().snapshot();
    const session = seed.sessions.find((item) => item.id === seed.selectedSessionId)!;
    const initial: ClientSnapshot = {
      ...seed, connection: "connected",
      source: { kind: "live", muxSpaceId: "choice-mux", serviceInstanceId: "choice-host", connectionEpoch: "1" },
      sessions: [{
        ...session, status: "idle", execution: null, userChoice: {
          questionId: "question-1", question: "Which plan?",
          options: [
            { id: "a", label: "Gradual", description: "Small steps" },
            { id: "b", label: "Rewrite", description: null },
          ],
        },
      }],
    };
    let publish: (snapshot: ClientSnapshot) => void = () => {};
    let receipt!: (accepted: boolean) => void;
    const submitText = vi.fn<HarnessClientUiPort["submitText"]>(async ({ submissionId }) => {
      const accepted = await new Promise<boolean>((resolve) => { receipt = resolve; });
      return { submissionId, accepted, reason: accepted ? undefined : "submission_outcome_unknown" };
    });
    const client: HarnessClientUiPort = {
      snapshot: async () => initial,
      subscribe: () => () => undefined,
      subscribeSnapshots: (listener) => { publish = listener; return () => undefined; },
      submitText, interrupt: async () => ({ accepted: false }),
      sessionModels: async () => ({ currentId: liveModel.id, models: [liveModel] }),
    };
    render(<HarnessGui client={client} />);
    const form = await screen.findByRole("form", { name: "Choose a direction" });
    fireEvent.click(screen.getByRole("button", { name: "Execution" }));
    fireEvent.click(screen.getByRole("button", { name: "Go to question" }));
    expect(form).toHaveFocus();
    const card = within(form);
    expect(card.getByText("Which plan?")).toBeVisible();
    fireEvent.click(card.getByRole("radio", { name: "Rewrite" }));
    const note = card.getByRole("textbox", { name: "Additional notes (optional)" });
    fireEvent.change(note, { target: { value: "Keep the public API" } });
    const confirm = card.getByRole("button", { name: "Confirm choice" });
    expect(confirm).toHaveClass("primary-button");
    await waitFor(() => expect(confirm).toBeEnabled());
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    expect(submitText).toHaveBeenCalledTimes(1);
    expect(submitText).toHaveBeenCalledWith(expect.objectContaining({
      sessionId: session.id, text: "Question: Which plan?\nSelected option b: Rewrite\nAdditional notes: Keep the public API",
    }));
    await act(async () => receipt(false));
    expect(card.getByRole("radio", { name: "Rewrite" })).toBeChecked();
    expect(note).toHaveValue("Keep the public API");
    expect(confirm).toBeDisabled();
    act(() => publish({ ...initial, sessions: [{
      ...initial.sessions[0], userChoice: undefined,
      messages: [...initial.sessions[0].messages, {
        id: "published-choice", role: "user", phase: "complete",
        content: "Question: Which plan?\nSelected option b: Rewrite\nAdditional notes: Keep the public API",
      }],
    }] }));
    expect(screen.queryByRole("form", { name: "Choose a direction" })).not.toBeInTheDocument();
    const summary = await screen.findByText("Selected · Rewrite");
    expect(summary.closest("details")).not.toHaveAttribute("open");
    expect(summary.closest("article.user")).toBeNull();
  });
});

describe("Hosted Goal observation", () => {
  it("shows authoritative paused facts and discards observations after a Session or connection change", async () => {
    const seed = await createMockAppClient().snapshot();
    const [session, other] = seed.sessions;
    const execution = {
      id: "goal-execution", status: "running" as const, revision: 3,
      interruptRequested: false, sourceStatus: null, finalCursor: null, truncated: false,
    };
    const initial: ClientSnapshot = {
      ...seed, connection: "connected", selectedSessionId: session.id,
      source: { kind: "live", serviceInstanceId: "goal-host", muxSpaceId: "goal-mux", connectionEpoch: "1" },
      sessions: [{ ...session, execution, supportsGoalProgress: true }],
    };
    const observed = {
      executionId: execution.id, presence: "present" as const, goalId: "real-goal",
      status: "paused" as const, reasonCode: "advance_budget_exhausted", validity: "not_checked" as const,
      executionUnresolved: true, advances: 2, modelCalls: 3, batchCount: 17,
      batches: Array.from({ length: 16 }, (_, index) => ({
        batchId: `batch-${index + 2}`, workStatus: index ? "completed" as const : null,
        recordingAvailable: index > 0, cancellationStatus: index ? "not_requested" as const : null,
        observationUnavailable: index === 0,
      })),
    };
    let publish: (snapshot: ClientSnapshot) => void = () => {};
    let disconnect: (state: "disconnected") => void = () => {};
    let settle!: (value: typeof observed) => void;
    const goalProgress = vi.fn<NonNullable<HarnessClientUiPort["goalProgress"]>>()
      .mockImplementationOnce(() => new Promise((resolve) => { settle = resolve; }))
      .mockResolvedValue(observed);
    const client: HarnessClientUiPort = {
      snapshot: async () => initial,
      subscribe: () => () => {},
      subscribeSnapshots(listener) { publish = listener; return () => {}; },
      subscribeConnection(listener) { disconnect = listener; return () => {}; },
      submitText: async ({ submissionId }) => ({ submissionId, accepted: false }),
      interrupt: async () => ({ accepted: false }),
      goalProgress,
    };
    render(<HarnessGui client={client} />);
    await waitFor(() => expect(goalProgress).toHaveBeenCalledWith(session.id, execution.id));
    act(() => publish({ ...initial, selectedSessionId: other.id, sessions: [{ ...other, execution }] }));
    await act(async () => settle(observed));
    expect(screen.queryByRole("region", { name: "Goal progress" })).not.toBeInTheDocument();
    expect(goalProgress).toHaveBeenCalledTimes(1);

    act(() => publish(initial));
    fireEvent.click(await screen.findByRole("button", { name: "Execution" }));
    const panel = within(await screen.findByRole("region", { name: "Goal progress" }));
    expect(panel.getByText("real-goal")).not.toBeVisible();
    fireEvent.click(panel.getByText("Execution details"));
    expect(panel.getByText("real-goal")).toBeVisible();
    expect(panel.getByText("Paused")).toBeVisible();
    expect(panel.getByText("advance_budget_exhausted")).toBeVisible();
    expect(panel.getByText("Not checked")).toBeVisible();
    const work = panel.getByText("Work execution details");
    expect(work.closest("details")).not.toHaveAttribute("open");
    fireEvent.click(work);
    const table = within(panel.getByRole("table", { name: "Work execution details" }));
    const [, first, second, ...remaining] = table.getAllByRole("row");
    expect(within(first).getByText("batch-2")).toBeVisible();
    expect(within(first).getAllByText("Not observed")).toHaveLength(2);
    expect(within(first).getByText("Unavailable")).toBeVisible();
    expect(within(first).getByText("Some information is unavailable")).toBeVisible();
    expect(within(second).getByText("Completed")).toBeVisible();
    expect(within(second).getByText("Observable")).toBeVisible();
    expect(within(second).getByText("Not requested")).toBeVisible();
    expect(within(remaining[remaining.length - 1]).getByText("batch-17")).toBeVisible();
    expect(panel.getByText("Showing the latest 16 of 17 batches.")).toBeVisible();
    expect(panel.getByText("Paused")).toBeVisible();

    goalProgress.mockResolvedValueOnce(null);
    act(() => publish({ ...initial, sessions: [{
      ...initial.sessions[0], execution: { ...execution, status: "succeeded" },
    }] }));
    expect(await panel.findByText(/Last confirmed observation/)).toBeVisible();
    expect(within(first).getByText("batch-2")).toBeVisible();
    const total = goalProgress.mock.calls.length;
    act(() => disconnect("disconnected"));
    expect(await panel.findByText(/Last confirmed observation/)).toBeVisible();
    await new Promise((resolve) => setTimeout(resolve, 2100));
    expect(goalProgress).toHaveBeenCalledTimes(total);
  });
});

describe("Hosted Goal start", () => {
  it("keeps an uncertain start locked for the original Host until its execution is observed", async () => {
    const seed = await createMockAppClient().snapshot();
    const session = { ...seed.sessions[0], status: "idle" as const, execution: null };
    const source = { kind: "live" as const, serviceInstanceId: "goal-host", muxSpaceId: "goal-mux", connectionEpoch: "1" };
    const initial: ClientSnapshot = { ...seed, source, connection: "connected", sessions: [session], selectedSessionId: session.id };
    const ready: ClientSnapshot = { ...initial, sessions: [{ ...session, supportsGoalStart: true }] };
    type Start = NonNullable<HarnessClientUiPort["startGoal"]>;
    let publish: (snapshot: ClientSnapshot) => void = () => {};
    let disconnect: (state: "disconnected") => void = () => {};
    let finish!: () => void;
    const startGoal = vi.fn<Start>(({ submissionId }) => new Promise((resolve) => {
      finish = () => resolve({ submissionId, accepted: false, reason: "submission_outcome_unknown" });
    }));
    const client: HarnessClientUiPort = {
      snapshot: async () => initial,
      subscribe: () => () => {},
      subscribeSnapshots(listener) { publish = listener; return () => {}; },
      subscribeConnection(listener) { disconnect = listener; return () => {}; },
      startGoal,
      submitText: async ({ submissionId }) => ({ submissionId, accepted: false }),
      interrupt: async () => ({ accepted: false }),
    };
    render(<HarnessGui client={client} />);
    await screen.findByRole("textbox", { name: /message/i });
    expect(screen.queryByRole("button", { name: "Start Goal" })).not.toBeInTheDocument();
    act(() => publish(ready));
    fireEvent.click(await screen.findByRole("button", { name: "Execution" }));
    const button = await screen.findByRole("button", { name: "Start Goal" });
    act(() => { fireEvent.click(button); fireEvent.click(button); });
    expect(button).toBeDisabled();
    expect(startGoal).toHaveBeenCalledExactlyOnceWith(
      { sessionId: session.id, submissionId: expect.stringMatching(/^gui-/) }, "goal-host",
    );
    await act(async () => finish());
    const unknown = /Goal start outcome is unknown/;
    expect(screen.getByText(unknown)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Start Goal" })).not.toBeInTheDocument();

    act(() => disconnect("disconnected"));
    const reconnected = { ...ready, source: { ...source, connectionEpoch: "2" } };
    act(() => publish(reconnected));
    expect(await screen.findByText(unknown)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Start Goal" })).not.toBeInTheDocument();
    act(() => publish({ ...reconnected, sessions: [{ ...session, status: "running", execution: {
      id: "goal-execution", status: "running", revision: 2,
      interruptRequested: false, sourceStatus: "running", finalCursor: null, truncated: false,
    } }] }));
    expect(screen.queryByText(unknown)).not.toBeInTheDocument();
    expect(within(screen.getByLabelText("Session transcript")).getByText("Execution Running")).toBeVisible();
    expect(startGoal).toHaveBeenCalledTimes(1);
    const current = within(screen.getByRole("region", { name: "Current work" }));
    expect(current.getByRole("status")).toHaveTextContent("Running");
    expect(current.getByRole("button", { name: "Stop execution" })).toBeEnabled();
    act(() => disconnect("disconnected"));
    expect(current.getByRole("status")).toHaveTextContent("Running");
    expect(current.getByText(/last confirmed information/i)).toBeVisible();
    expect(current.getByRole("button", { name: "Stop execution" })).toBeDisabled();

    act(() => publish({ ...ready, source: { ...source, serviceInstanceId: "new-host", connectionEpoch: "3" } }));
    const dock = screen.queryByLabelText("Work Dock");
    if (!dock || !within(dock).queryByRole("button", { name: "Start Goal" })) {
      fireEvent.click(screen.getByRole("button", { name: "Execution" }));
    }
    expect(await screen.findByRole("button", { name: "Start Goal" })).toBeEnabled();
    expect(startGoal).toHaveBeenCalledTimes(1);
  });
});

describe("Interactive development goal", () => {
  it("waits for capability and readiness, then reconciles a lost receipt by Goal status", async () => {
    const seed = await createMockAppClient().snapshot();
    const session = { ...seed.sessions[0], status: "idle" as const, execution: null };
    const source = { kind: "live" as const, serviceInstanceId: "goal-host", muxSpaceId: "goal-mux", connectionEpoch: "1" };
    const initial: ClientSnapshot = { ...seed, source, connection: "connected", sessions: [session], selectedSessionId: session.id };
    const supported: ClientSnapshot = { ...initial, sessions: [{ ...session, supportsInteractiveGoal: true }] };
    const absent = { goalId: null, status: null, revision: null, epoch: null, executionUnresolved: null };
    const interactiveGoalStatus = vi.fn<NonNullable<HarnessClientUiPort["interactiveGoalStatus"]>>()
      .mockResolvedValueOnce({ ...absent, availability: "not_ready" })
      .mockResolvedValueOnce({ ...absent, availability: "ready" })
      .mockResolvedValueOnce(null)
      .mockResolvedValue({
        availability: "present", goalId: "goal-original", status: "active", revision: 1, epoch: 1,
        executionUnresolved: false,
      });
    let loseReceipt!: () => void;
    const createInteractiveGoal = vi.fn<NonNullable<HarnessClientUiPort["createInteractiveGoal"]>>(
      () => new Promise((_, reject) => { loseReceipt = () => reject(new Error("connection lost")); }),
    );
    let publish: (snapshot: ClientSnapshot) => void = () => {};
    const client: HarnessClientUiPort = {
      snapshot: async () => initial,
      subscribe: () => () => {},
      subscribeSnapshots(listener) { publish = listener; return () => {}; },
      interactiveGoalStatus,
      createInteractiveGoal,
      submitText: async ({ submissionId }) => ({ submissionId, accepted: false }),
      interrupt: async () => ({ accepted: false }),
    };
    render(<HarnessGui client={client} />);
    await screen.findByRole("textbox", { name: /message/i });
    expect(screen.queryByRole("region", { name: "Development goal" })).not.toBeInTheDocument();
    expect(interactiveGoalStatus).not.toHaveBeenCalled();

    act(() => publish(supported));
    const entry = await screen.findByRole("button", { name: "Development goal" });
    expect(entry.closest("form")).toContainElement(screen.getByRole("textbox", { name: /message/i }));
    expect(entry).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("button", { name: "Check goal status" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create development goal" })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Goal target" })).not.toBeInTheDocument();
    fireEvent.click(entry);
    expect(entry).toHaveAttribute("aria-expanded", "true");
    const goal = within(await screen.findByRole("region", { name: "Development goal" }));
    expect(within(screen.getByRole("complementary", { name: "Work Dock" }))
      .getByRole("button", { name: "Execution" })).toHaveAttribute("aria-pressed", "true");
    expect(await goal.findByText(/Send an ordinary message/)).toBeVisible();
    expect(goal.queryByRole("button", { name: "Create development goal" })).not.toBeInTheDocument();
    fireEvent.click(goal.getByRole("button", { name: "Check goal status" }));
    fireEvent.click(await goal.findByRole("button", { name: "Create development goal" }));
    const target = goal.getByRole("textbox", { name: "Goal target" });
    fireEvent.change(target, { target: { value: "Preserve this target" } });
    const create = goal.getByRole("button", { name: "Create goal" });
    act(() => { fireEvent.click(create); fireEvent.click(create); });
    expect(create).toBeDisabled();
    expect(createInteractiveGoal).toHaveBeenCalledExactlyOnceWith({
      serviceInstanceId: "goal-host", connectionEpoch: "1", sessionId: session.id,
      goalTarget: "Preserve this target",
    });
    await act(async () => loseReceipt());
    expect(goal.getByText("Goal creation is not yet confirmed.")).toBeVisible();
    expect(target).toHaveValue("Preserve this target");
    expect(create).toBeDisabled();

    fireEvent.click(goal.getByRole("button", { name: "Check goal status" }));
    expect(await goal.findByText("Goal created. Execution has not started.")).toBeVisible();
    fireEvent.click(goal.getByText("Execution details"));
    expect(goal.getByText("goal-original")).toBeVisible();
    expect(goal.getByText("Goal created. Execution has not started.")).toBeVisible();
    expect(goal.queryByRole("button", { name: "Create goal" })).not.toBeInTheDocument();
    expect(createInteractiveGoal).toHaveBeenCalledTimes(1);
    fireEvent.click(entry);
    expect(entry).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("region", { name: "Development goal" })).not.toBeInTheDocument();
  });
});

it("reconciles a Goal command by identity and distinguishes pause from cancellation settlement", async () => {
  const seed = await createMockAppClient().snapshot();
  const session = {
    ...seed.sessions[0], status: "idle" as const, execution: null,
    supportsInteractiveGoal: true as const, supportsInteractiveGoalCommands: true as const,
  };
  const initial: ClientSnapshot = {
    ...seed, sessions: [session], selectedSessionId: session.id, connection: "connected",
    source: { kind: "live", serviceInstanceId: "goal-host", muxSpaceId: "goal-mux", connectionEpoch: "1" },
  };
  type Status = NonNullable<HarnessClientUiPort["interactiveGoalStatus"]>;
  type Control = NonNullable<HarnessClientUiPort["controlInteractiveGoal"]>;
  let observed: Awaited<ReturnType<Status>> = {
    availability: "present", goalId: "original-goal", status: "active", revision: 1, epoch: 1, executionUnresolved: false,
  };
  const interactiveGoalStatus = vi.fn<Status>().mockImplementation(async () => observed);
  const controlInteractiveGoal = vi.fn<Control>().mockImplementation(async (input) => {
    if (input.action === "step" || input.action === "resume") {
      return observed = { ...observed!, status: "active",
        command: { commandId: input.commandId, action: input.action, status: "finished" } };
    }
    if (input.action === "run") {
      observed = { ...observed!, command: { commandId: input.commandId, action: "run", status: "running" } };
      throw new Error("Lost reply");
    }
    if (input.action === "pause") {
      return observed = {
        ...observed!, status: "paused", revision: 2,
        command: { commandId: input.commandId, action: "pause", status: "settling" },
      };
    }
    return observed = {
      ...observed!, command: { commandId: input.commandId, action: "cancel", status: "settling" },
    };
  });
  const client: HarnessClientUiPort = {
    snapshot: async () => initial,
    subscribe: () => () => {},
    createInteractiveGoal: async () => null,
    interactiveGoalStatus, controlInteractiveGoal,
    submitText: async ({ submissionId }) => ({ submissionId, accepted: false }),
    interrupt: async () => ({ accepted: false }),
  };
  render(<HarnessGui client={client} />);
  const entry = await screen.findByRole("button", { name: "Development goal" });
  fireEvent.click(screen.getByRole("button", { name: "Execution" }));
  const goal = within(await screen.findByRole("region", { name: "Development goal" }));
  fireEvent.click(await goal.findByRole("button", { name: "Step" }));
  expect(await goal.findByText("Goal command finished")).toBeVisible();
  const run = await goal.findByRole("button", { name: /^Run$/ });
  act(() => { fireEvent.click(run); fireEvent.click(run); });
  expect(await goal.findByText("Goal command running")).toBeVisible();
  expect(controlInteractiveGoal).toHaveBeenLastCalledWith({
    goalId: "original-goal", commandId: expect.stringMatching(/^gui-/), action: "run",
    sessionId: session.id, serviceInstanceId: "goal-host", connectionEpoch: "1",
  });
  expect(goal.queryByRole("button", { name: "Step" })).not.toBeInTheDocument();
  fireEvent.click(entry);
  expect(screen.queryByRole("region", { name: "Development goal" })).not.toBeInTheDocument();
  fireEvent.click(entry);
  expect(goal.getByText("Goal command running")).toBeVisible();

  fireEvent.click(goal.getByRole("button", { name: /^Pause$/ }));
  expect(await goal.findByText("Paused. Waiting for current Work to settle.")).toBeVisible();
  expect(goal.queryByRole("button", { name: "Resume" })).not.toBeInTheDocument();
  fireEvent.click(goal.getByRole("button", { name: "Cancel execution" }));
  expect(await goal.findByText("Cancellation requested. Waiting for current Work to settle.")).toBeVisible();
  observed = { ...observed!, command: { ...observed!.command!, status: "finished" } };
  fireEvent.click(goal.getByRole("button", { name: "Check goal status" }));
  fireEvent.click(await goal.findByRole("button", { name: "Resume" }));
  await waitFor(() => expect(controlInteractiveGoal.mock.calls.map(([input]) => input.action))
    .toEqual(["step", "run", "pause", "cancel", "resume"]));
});

it("offers Goal review only for a current candidate and gates acceptance on check evidence", async () => {
  const seed = await createMockAppClient().snapshot();
  const session = {
    ...seed.sessions[0], status: "idle" as const, execution: null,
    supportsInteractiveGoal: true as const, supportsInteractiveGoalCommands: true as const,
  };
  type Status = NonNullable<HarnessClientUiPort["interactiveGoalStatus"]>;
  type Review = NonNullable<HarnessClientUiPort["interactiveGoalReview"]>;
  type Submit = NonNullable<HarnessClientUiPort["submitInteractiveGoalReview"]>;
  const paused: Awaited<ReturnType<Status>> = {
    availability: "present", goalId: "development", status: "paused", revision: 1, epoch: 3,
    executionUnresolved: false, reviewAvailable: true,
  };
  let view = paused;
  const summary = vi.fn<Review>()
    .mockResolvedValueOnce(null)
    .mockResolvedValue({
      goalId: "development", revision: 1, epoch: 3, reviewToken: "a".repeat(64),
      changedFiles: ["note.txt"], checkCount: 1, checksSatisfied: false, filesTruncated: false,
    });
  const submitReview = vi.fn<Submit>().mockImplementation(async (input) => {
    view = {
      ...paused, status: "active", epoch: 4, reviewAvailable: undefined,
      command: { commandId: input.commandId, action: "reject", status: "finished" },
    };
    throw new Error("Reply lost");
  });
  const client: HarnessClientUiPort = {
    snapshot: async () => ({
      ...seed, sessions: [session], selectedSessionId: session.id, connection: "connected",
      source: { kind: "live", serviceInstanceId: "goal-host", muxSpaceId: "goal-mux", connectionEpoch: "1" },
    }),
    subscribe: () => () => {},
    createInteractiveGoal: async () => null,
    interactiveGoalStatus: async () => view,
    interactiveGoalReview: summary,
    submitInteractiveGoalReview: submitReview,
    submitText: async ({ submissionId }) => ({ submissionId, accepted: false }),
    interrupt: async () => ({ accepted: false }),
  };
  render(<HarnessGui client={client} />);
  const entry = await screen.findByRole("button", { name: "Development goal" });
  fireEvent.click(entry);
  const goal = within(await screen.findByRole("region", { name: "Development goal" }));
  expect(goal.getByRole("heading", { name: "Goal review needed" })).toBeVisible();
  const review = await goal.findByRole("button", { name: "Review result" });
  fireEvent.click(review);
  expect(await goal.findByText(/Current candidate unavailable/)).toBeVisible();
  expect(goal.queryByRole("button", { name: "Accept result" })).not.toBeInTheDocument();
  fireEvent.click(review);
  expect(await goal.findByText("note.txt")).toBeVisible();
  expect(goal.getByText(/Verify the actual changes/)).toBeVisible();
  expect(goal.getByRole("button", { name: "Accept result" })).toBeDisabled();
  const reject = goal.getByRole("button", { name: "Reject with feedback" });
  expect(reject).toBeDisabled();
  fireEvent.change(goal.getByRole("textbox", { name: "Specific rejection feedback" }), { target: { value: "Add a sign-off" } });
  act(() => { fireEvent.click(reject); fireEvent.click(reject); });
  expect(await goal.findByText("Feedback recorded. You can run the Goal again.")).toBeVisible();
  expect(submitReview).toHaveBeenCalledExactlyOnceWith({
    sessionId: session.id, serviceInstanceId: "goal-host", connectionEpoch: "1",
    goalId: "development", reviewToken: "a".repeat(64), commandId: expect.stringMatching(/^gui-/),
    decision: "reject", reason: "Add a sign-off",
  });
  expect(goal.queryByText("Completed")).not.toBeInTheDocument();
});

it.each([
  { status: "active", reason: "created", label: "Active when last recorded", unresolved: true },
  { status: "paused", reason: "review_required", label: "Paused", unresolved: false },
  { status: "completed", reason: "requirements_satisfied", label: "Completed", unresolved: false },
] as const)("replaces a prior Host's command with read-only $status Goal history", async ({
  status, reason, label, unresolved,
}) => {
  const seed = await createMockAppClient().snapshot();
  const active = {
    ...seed.sessions[0], status: "idle" as const, execution: null,
    supportsInteractiveGoal: true as const, supportsInteractiveGoalCommands: true as const,
  };
  const deferred = {
    ...active, supportsInteractiveGoal: undefined, supportsInteractiveGoalCommands: undefined,
    supportsInteractiveGoalRecovery: true as const,
  };
  const initial: ClientSnapshot = {
    ...seed, sessions: [active], selectedSessionId: active.id, connection: "connected",
    source: { kind: "live", serviceInstanceId: "first-host", muxSpaceId: "mux", connectionEpoch: "1" },
  };
  type Recover = NonNullable<HarnessClientUiPort["interactiveGoalRecovery"]>;
  const recover = vi.fn<Recover>().mockResolvedValue({
    presence: "present", goalId: "original-goal", goalStatus: status, reasonCode: reason, revision: 1, epoch: 1,
    batchCount: 2, completedCount: unresolved ? 1 : 2, failedCount: 0, cancelledCount: 0,
    orphanedCount: unresolved ? 1 : 0, executionUnresolved: unresolved, readOnly: true,
  });
  let publish: (snapshot: ClientSnapshot) => void = () => {};
  const control = vi.fn();
  const client: HarnessClientUiPort = {
    snapshot: async () => initial,
    subscribe: () => () => {},
    subscribeSnapshots(listener) { publish = listener; return () => {}; },
    createInteractiveGoal: async () => null,
    controlInteractiveGoal: control,
    interactiveGoalRecovery: recover,
    interactiveGoalStatus: async () => ({
      availability: "present", goalId: "original-goal", status: "active", revision: 1, epoch: 1, executionUnresolved: false,
      command: { action: "run", commandId: "old-run", status: "running" },
    }),
    submitText: async ({ submissionId }) => ({ submissionId, accepted: false }),
    interrupt: async () => ({ accepted: false }),
  };
  render(<HarnessGui client={client} />);
  fireEvent.click(await screen.findByRole("button", { name: "Development goal" }));
  expect(await screen.findByText("Goal command running")).toBeVisible();
  expect(recover).not.toHaveBeenCalled();
  act(() => publish({
    ...initial, sessions: [deferred],
    source: { kind: "live", serviceInstanceId: "second-host", muxSpaceId: "mux", connectionEpoch: "2" },
  }));
  const entry = await screen.findByRole("button", { name: "Development goal" });
  expect(entry).toHaveAttribute("aria-expanded", "true");
  const panel = within(await screen.findByRole("region", { name: "Historical Goal" }));
  expect(await panel.findByText(label)).toBeVisible();
  expect(panel.getByText(reason)).not.toBeVisible();
  fireEvent.click(panel.getByText("Execution details"));
  expect(panel.getByText(reason)).toBeVisible();
  expect(panel.queryAllByText(/Some execution results are unconfirmed/)).toHaveLength(unresolved ? 1 : 0);
  expect(panel.queryAllByRole("button")).toHaveLength(0);
  expect(screen.queryByText("Goal command running")).not.toBeInTheDocument();
  expect(control).not.toHaveBeenCalled();
  expect(recover).toHaveBeenCalledExactlyOnceWith({ sessionId: active.id, serviceInstanceId: "second-host", connectionEpoch: "2" });
});
