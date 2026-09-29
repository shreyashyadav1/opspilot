import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { executed, investigation, rejected } from "@/test/fixtures";
import { mockApi } from "@/test/utils";

import { DecisionPanel } from "./DecisionPanel";

describe("DecisionPanel", () => {
  it("asks for a decision with prominent approve and reject buttons", () => {
    render(<DecisionPanel investigation={investigation()} onDecided={() => {}} />);
    expect(
      screen.getByRole("heading", { name: "Approve the rollback of orders?" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Revert the deploy that introduced the failures.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve rollback" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeEnabled();
  });

  it("sends the reviewer, the note and the decision", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "POST /api/investigations/inv-0007/decision": [200, executed()],
    });
    const onDecided = vi.fn();
    render(<DecisionPanel investigation={investigation()} onDecided={onDecided} />);
    const name = screen.getByLabelText("Your name");
    await user.clear(name);
    await user.type(name, "alice");
    await user.type(screen.getByLabelText(/Note/), "Matches the deploy diff");
    await user.click(screen.getByRole("button", { name: "Approve rollback" }));

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0]!;
    expect(JSON.parse(String(init?.body))).toEqual({
      decision: "approve",
      reviewer: "alice",
      comment: "Matches the deploy diff",
    });
    expect(onDecided).toHaveBeenCalledWith(expect.objectContaining({ status: "executed" }));
  });

  it("reports a refused decision without changing anything", async () => {
    const user = userEvent.setup();
    mockApi({
      "POST /api/investigations/inv-0007/decision": [
        409,
        { detail: "inv-0007 is not waiting for a decision (rejected)" },
      ],
    });
    const onDecided = vi.fn();
    render(<DecisionPanel investigation={investigation()} onDecided={onDecided} />);
    await user.click(screen.getByRole("button", { name: "Reject" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("not waiting for a decision");
    expect(onDecided).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Approve rollback" })).toBeEnabled();
  });

  it("reports the outcome once decided", () => {
    const { rerender } = render(<DecisionPanel investigation={rejected()} onDecided={() => {}} />);
    expect(screen.getByRole("heading", { name: "Rollback rejected" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Rejected by bob");
    expect(screen.getByRole("status")).toHaveTextContent("Nothing was executed.");
    expect(screen.queryByRole("button", { name: "Approve rollback" })).not.toBeInTheDocument();

    rerender(<DecisionPanel investigation={executed()} onDecided={() => {}} />);
    expect(screen.getByRole("status")).toHaveTextContent("orders rolled back from 1.8.4 to 1.8.3.");
  });

  it("renders nothing when no action needs approval", () => {
    const { container } = render(
      <DecisionPanel
        investigation={investigation({ approval_request: null })}
        onDecided={() => {}}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
