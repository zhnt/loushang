import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { HarnessGui } from "../../src/App";
import { createMockAppClient } from "../../src/client/mockAppClient";

describe("GUI-B1 deterministic playback", () => {
  it("preserves drafts and plays input, streaming, interrupt, and document reading", async () => {
    const user = userEvent.setup();
    render(<HarnessGui client={createMockAppClient()} />);

    await screen.findByRole("heading", { name: "GUI architecture" });
    expect(screen.getByText("Web Mock")).toBeVisible();
    const input = screen.getByRole("textbox", {
      name: "Message for GUI architecture",
    });
    await user.type(input, "Explain the shared-host boundary");

    await user.click(screen.getByRole("button", { name: /Provider review/ }));
    const reviewInput = screen.getByRole("textbox", {
      name: "Message for Provider review",
    });
    expect(reviewInput).toHaveValue("");
    await user.type(reviewInput, "Review-only draft");

    await user.click(screen.getByRole("button", { name: /GUI architecture/ }));
    expect(
      screen.getByRole("textbox", { name: "Message for GUI architecture" }),
    ).toHaveValue("Explain the shared-host boundary");

    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(screen.getByRole("button", { name: /GUI architecture/ })).toHaveTextContent(
      "Running",
    );
    expect(screen.getByText("Explain the shared-host boundary")).toBeVisible();
    expect(screen.getByText("4 queued events")).toBeVisible();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();

    const advance = screen.getByRole("button", { name: "Advance fixture" });
    await user.click(advance);
    await user.click(advance);
    expect(
      screen.getByText(/separate client scope.*shared service facts/s),
    ).toBeVisible();

    await user.click(advance);
    const diffTab = screen.getByRole("button", { name: "GUI B1 runbook.diff" });
    await user.click(diffTab);
    const document = screen.getByRole("article", { name: "GUI B1 runbook.diff" });
    expect(within(document).getByText("fixture-r2")).toBeVisible();
    expect(within(document).getByText(/GUI consumes accepted values only/)).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Interrupt" }));
    expect(screen.getByRole("button", { name: /GUI architecture/ })).toHaveTextContent(
      "Interrupted",
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "Fixture execution interrupted",
    );

    await user.click(screen.getByRole("button", { name: /Provider review/ }));
    expect(
      screen.getByRole("textbox", { name: "Message for Provider review" }),
    ).toHaveValue("Review-only draft");
  });
});
