import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { HarnessGui } from "../../src/App";
import { createMockAppClient } from "../../src/client/mockAppClient";
import type { ClientSnapshot, FixturePlaybackPort } from "../../src/client/model";

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
  it("restores independent transcript positions when switching Sessions", async () => {
    const user = userEvent.setup();
    const client = createMockAppClient();
    render(<HarnessGui client={client} />);
    await screen.findByRole("heading", { name: "GUI development" });
    const transcript = screen.getByLabelText("Session transcript");
    fireEvent.scroll(transcript, { target: { scrollTop: 180 } });
    await user.click(screen.getByRole("button", { name: "Operational ontology · Idle" }));
    expect(transcript.scrollTop).toBe(0);
    fireEvent.scroll(transcript, { target: { scrollTop: 45 } });
    await user.click(screen.getByRole("button", { name: "GUI development · Running" }));
    expect(transcript.scrollTop).toBe(180);
    await act(async () => { await client.advanceFixture(); });
    expect(transcript.scrollTop).toBe(180);
    await user.click(screen.getByRole("button", { name: "Operational ontology · Idle" }));
    expect(transcript.scrollTop).toBe(45);
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
    await screen.findAllByText(/workspace capability/);
    expect(screen.queryByLabelText("Fixture changes")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Quick look gui-interface-specification.md")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Step 1 / 4" })).not.toBeInTheDocument();
    expect(screen.queryByText("git · main")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Open Work Dock" }));
    const dock = screen.getByLabelText("Work Dock");
    for (const [label, facet] of [["Tasks", "tasks"], ["Subagents", "agents"], ["Review", "changes"]]) {
      await user.click(within(dock).getByRole("button", { name: label }));
      expect(within(dock).getByText(new RegExp(`${facet} capability`))).toBeVisible();
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
    await user.click(screen.getByRole("button", { name: "Operational ontology · Idle" }));
    const input = screen.getByRole("textbox", { name: "Message for Operational ontology" });
    await user.type(input, "Keep this draft");
    await user.keyboard("{Control>}{Enter}{/Control}");
    expect(input).toHaveValue("Keep this draft");
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    expect(screen.queryByText("Keep this draft", { selector: "article p" })).not.toBeInTheDocument();
    await user.click(screen.getByText(/Fixture playback ·/));
    expect(screen.getByRole("button", { name: "Advance fixture" })).toBeDisabled();
  });

  it("keeps a live snapshot visibly read-only and hides fixture controls", async () => {
    const fixture = createMockAppClient();
    const snapshot = await fixture.snapshot();
    render(<HarnessGui client={{
      snapshot: async () => ({
        ...snapshot,
        connection: "connected",
        source: { kind: "live", serviceInstanceId: "service-live", muxSpaceId: "mux-live" },
        capabilities: snapshot.capabilities.map((capability) => ({
          ...capability,
          availability: capability.name === "tasks" || capability.name === "agents" ? "live" : "unavailable",
          version: capability.name === "tasks" || capability.name === "agents" ? "loushang.execution/v1" : null,
        })),
        sessions: snapshot.sessions.map((session) => ({
          ...session,
          context: { ...session.context, source: "live" },
          changeSet: null,
          documents: [],
        })),
      }),
      subscribe: () => () => undefined,
      submitText: async (input) => ({ submissionId: input.submissionId, accepted: false }),
      interrupt: async () => ({ accepted: false }),
    }} />);
    await screen.findByText("Live AppHost · read-only");
    expect(screen.queryByLabelText("Fixture playback controls")).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Message for GUI development" })).toBeDisabled();
    expect(screen.getByText("Live · read-only")).toBeVisible();
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

    const activity = screen.getByRole("button", { name: /Build the Workspace.*3 activities/ });
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
