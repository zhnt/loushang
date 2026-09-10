import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { HarnessGui } from "../../src/App";
import { createMockAppClient } from "../../src/client/mockAppClient";

describe("GUI-B1 Workspace / Task / Review fixture", () => {
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

    const advance = screen.getByRole("button", { name: "Advance fixture" });
    await user.click(advance);
    expect(within(timeline).getByText("Fixture tool call · no repository access")).toBeVisible();
    await user.click(advance);
    expect(screen.getByRole("button", { name: "Step 2 / 4" })).toBeVisible();

    while (client.remainingFixtureSteps() > 0) await user.click(advance);
    expect(screen.getByRole("button", { name: "4 / 4 complete" })).toBeVisible();
    expect(screen.getByRole("button", { name: "GUI development · Idle" })).toBeVisible();
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
