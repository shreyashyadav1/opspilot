import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { executed, investigation, rejected, withDeployHistory } from "@/test/fixtures";

import { Timeline } from "./Timeline";

describe("Timeline", () => {
  it("shows every tool call with its arguments, result and outcome", () => {
    render(<Timeline investigation={investigation()} />);
    const turn = screen.getByRole("list", { name: "Tool calls of turn 1" });
    const calls = within(turn).getAllByRole("listitem");
    expect(calls).toHaveLength(2);
    expect(calls[0]).toHaveTextContent("get_service_health()");
    expect(calls[0]).toHaveTextContent("orders unhealthy (HTTP 503); 2 healthy.");
    expect(calls[0]).toHaveTextContent("ok");
    expect(calls[1]).toHaveTextContent("get_recent_deploys(since_minutes=60)");
    expect(calls[1]).toHaveTextContent("failed");
    expect(screen.getByText("The deploy explains it.")).toBeInTheDocument();
  });

  it("numbers the tool calls and gives each an anchor to cite", () => {
    render(<Timeline investigation={withDeployHistory()} />);
    const calls = within(screen.getByRole("list", { name: "Tool calls of turn 1" })).getAllByRole(
      "listitem",
    );
    expect(calls.map((call) => call.id)).toEqual(["call-3", "call-4"]);
    expect(calls[0]).toHaveTextContent("Call 1");
    expect(calls[1]).toHaveTextContent("Call 2");
    expect(screen.getByText("2 tool calls in 1.1 s")).toBeInTheDocument();
  });

  it("draws the approval gate with the action waiting behind it", () => {
    render(<Timeline investigation={investigation()} />);
    const gate = screen.getByRole("listitem", { name: "Approval gate" });
    expect(gate).toHaveTextContent("Waiting for a decision. Nothing runs until someone approves.");
    expect(gate).toHaveTextContent('rollback_deploy(service="orders") runs only after approval.');
    expect(
      within(gate).getByRole("link", { name: "Review the proposal and decide" }),
    ).toHaveAttribute("href", "#decision");
  });

  it("shows a rejected action as never executed", () => {
    render(<Timeline investigation={rejected()} />);
    const gate = screen.getByRole("listitem", { name: "Approval gate" });
    expect(gate).toHaveTextContent("Rejected. The action was not executed.");
    expect(gate).toHaveTextContent('rollback_deploy(service="orders") was not executed.');
    expect(gate).toHaveTextContent("Rejected by bob");
    expect(screen.queryByText("Action executed")).not.toBeInTheDocument();
  });

  it("shows an executed action after the gate", () => {
    render(<Timeline investigation={executed()} />);
    expect(screen.getByRole("listitem", { name: "Approval gate" })).toHaveTextContent(
      "Approved and executed.",
    );
    expect(screen.getByText("Action executed")).toBeInTheDocument();
    expect(screen.getByText("orders rolled back from 1.8.4 to 1.8.3.")).toBeInTheDocument();
  });
});
