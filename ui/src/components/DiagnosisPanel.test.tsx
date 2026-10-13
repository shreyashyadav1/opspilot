import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LLM, investigation, withDeployHistory } from "@/test/fixtures";

import { DiagnosisPanel } from "./DiagnosisPanel";

describe("DiagnosisPanel", () => {
  it("labels a zero cost from the rule-based baseline as a real zero, not a gap", () => {
    render(<DiagnosisPanel investigation={investigation()} />);
    expect(screen.getByText(/Cost: \$0\.00/)).toBeInTheDocument();
    expect(screen.getByText(/rule-based baseline, no LLM calls/)).toBeInTheDocument();
  });

  it("shows the priced cost of a real model without the baseline note", () => {
    const withCost = investigation({
      model: LLM,
      usage: {
        turns: 2,
        model_calls: 2,
        tool_calls: 2,
        input_tokens: 900,
        output_tokens: 120,
        cost_usd: 0.000207,
      },
    });
    render(<DiagnosisPanel investigation={withCost} />);
    expect(screen.getByText(/Cost: \$0\.0002/)).toBeInTheDocument();
    expect(screen.queryByText(/rule-based baseline/)).not.toBeInTheDocument();
  });

  it("links each piece of evidence to the tool call it came from", () => {
    render(<DiagnosisPanel investigation={withDeployHistory()} />);
    const items = screen.getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Deploys");
    expect(
      within(items[0]!).getByRole("link", { name: /^Call 2 in the timeline/ }),
    ).toHaveAttribute("href", "#call-4");
    // No search_logs call ran, so the log evidence is not pinned to any call.
    expect(within(items[1]!).queryByRole("link")).not.toBeInTheDocument();
  });

  it("reports an unpriced model's cost as not available", () => {
    const unpriced = investigation({
      model: { spec: "custom:x", kind: "llm", label: "x", description: "d" },
      usage: {
        turns: 2,
        model_calls: 2,
        tool_calls: 2,
        input_tokens: 900,
        output_tokens: 120,
        cost_usd: null,
      },
    });
    render(<DiagnosisPanel investigation={unpriced} />);
    expect(screen.getByText(/Cost: n\/a/)).toBeInTheDocument();
  });
});
