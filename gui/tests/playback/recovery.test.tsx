import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { HarnessGui } from "../../src/App";
import { createMockAppClient } from "../../src/client/mockAppClient";
import type { ClientSnapshot, FixturePlaybackPort } from "../../src/client/model";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function controlledClient() {
  const source = createMockAppClient();
  const requests: ReturnType<typeof deferred<ClientSnapshot>>[] = [];
  let drop = false;
  const client: FixturePlaybackPort = {
    snapshot: () => { const request = deferred<ClientSnapshot>(); requests.push(request); return request.promise; },
    subscribe: (listener) => source.subscribe((event) => { if (!drop) listener(event); }),
    submitText: (input) => source.submitText(input),
    interrupt: (id) => source.interrupt(id),
    advanceFixture: () => source.advanceFixture(),
    remainingFixtureSteps: () => source.remainingFixtureSteps(),
  };
  return { client, source, requests, setDrop: (value: boolean) => { drop = value; } };
}

describe("fixture synchronization", () => {
  it.each([false, true])("buffers startup events (snapshot includes events: %s)", async (includesEvents) => {
    const fixture = controlledClient();
    const before = await fixture.source.snapshot();
    render(<HarnessGui client={fixture.client} />);
    await act(async () => {
      await fixture.source.advanceFixture();
      await fixture.source.advanceFixture();
      fixture.requests[0].resolve(includesEvents ? await fixture.source.snapshot() : before);
    });
    expect(await screen.findByRole("button", { name: "Step 2 / 4" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Resynchronize fixture" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Build the Workspace.*4 activities/ })).toBeVisible();
  });

  it("retries after failure, preserves drafts and buffers events during recovery", async () => {
    const user = userEvent.setup();
    const fixture = controlledClient();
    render(<HarnessGui client={fixture.client} />);
    await act(async () => { fixture.requests[0].resolve(await fixture.source.snapshot()); });
    const input = screen.getByRole("textbox", { name: "Message for GUI development" });
    await user.type(input, "Keep this draft");
    await act(async () => {
      fixture.setDrop(true);
      await fixture.source.advanceFixture();
      fixture.setDrop(false);
      await fixture.source.advanceFixture();
    });
    expect(screen.getByText(/cursor gap/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Interrupt" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Resynchronize fixture" }));
    expect(screen.getByRole("button", { name: "Resynchronize fixture" })).toBeDisabled();
    await act(async () => { fixture.requests[1].reject(new Error("offline")); });
    expect(screen.getByText(/synchronization failed/)).toBeVisible();
    expect(input).toHaveValue("Keep this draft");
    await user.click(screen.getByRole("button", { name: "Resynchronize fixture" }));
    const snapshot = await fixture.source.snapshot();
    await act(async () => {
      await fixture.source.advanceFixture();
      fixture.requests[2].resolve(snapshot);
    });
    expect(await screen.findByRole("button", { name: /Build the Workspace.*5 activities/ })).toBeVisible();
    expect(screen.getByRole("button", { name: "Interrupt" })).toBeEnabled();
    expect(input).toHaveValue("Keep this draft");
    expect(screen.queryByRole("button", { name: "Resynchronize fixture" })).not.toBeInTheDocument();
  });

  it("offers retry after initial failure and ignores an old client's late snapshot", async () => {
    const user = userEvent.setup();
    const old = controlledClient();
    const next = controlledClient();
    const view = render(<HarnessGui client={old.client} />);
    await act(async () => { old.requests[0].reject(new Error("initial failure")); });
    await user.click(screen.getByRole("button", { name: "Resynchronize fixture" }));
    view.rerender(<HarnessGui client={next.client} />);
    const snapshot = await next.source.snapshot();
    await act(async () => { next.requests[0].resolve({ ...snapshot, generation: "replacement" }); });
    await waitFor(() => expect(screen.getByText("replacement")).toBeVisible());
    await act(async () => { old.requests[1].resolve(await old.source.snapshot()); });
    expect(screen.getByText("replacement")).toBeVisible();
  });
});
