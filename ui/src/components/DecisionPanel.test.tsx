import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  executed,
  executedWithRecord,
  investigation,
  rejected,
  withDeployHistory,
} from "@/test/fixtures";
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

  it("says exactly what the rollback changes, from the agent's own evidence", () => {
    render(<DecisionPanel investigation={withDeployHistory()} onDecided={() => {}} />);
    expect(screen.getByText("Rolls orders back from 1.8.4 to 1.8.3.")).toBeInTheDocument();
    expect(screen.getByText(/Undoes the deploy s\.patel shipped at/)).toBeInTheDocument();
    expect(
      screen.getByText("Route payment calls through the new payments endpoint"),
    ).toBeInTheDocument();
    const config = screen.getByText("payments.base-url").closest("dl");
    expect(config).toHaveTextContent("payments.base-url");
    expect(config).toHaveTextContent("Nowhttp://payments-v2:8080");
    expect(config).toHaveTextContent("Afterhttp://payments:8080");
    expect(
      screen.getByRole("link", { name: "Versions read in call 2 of the timeline" }),
    ).toHaveAttribute("href", "#call-4");
    expect(screen.getByText("Rolls orders back to 1.8.3 now.")).toBeInTheDocument();
  });

  it("says so when no tool call reported the versions", () => {
    render(<DecisionPanel investigation={investigation()} onDecided={() => {}} />);
    expect(screen.getByText(/did not report the versions/)).toBeInTheDocument();
    expect(screen.getByText("Rolls orders back now.")).toBeInTheDocument();
  });

  it("describes an executed rollback from the tool's own record", () => {
    render(<DecisionPanel investigation={executedWithRecord()} onDecided={() => {}} />);
    expect(screen.getByRole("heading", { name: "Rollback approved" })).toBeInTheDocument();
    expect(screen.getByText("orders was rolled back from 1.8.4 to 1.8.3.")).toBeInTheDocument();
    expect(screen.getByText("reported by the tool")).toBeInTheDocument();
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
