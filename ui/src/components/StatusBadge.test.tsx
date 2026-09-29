import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { STATUS } from "@/lib/format";
import type { Status } from "@/lib/types";

import { ModelBadge } from "./ModelBadge";
import { StatusBadge } from "./StatusBadge";

describe("StatusBadge", () => {
  it.each(Object.keys(STATUS) as Status[])("names the %s status in words", (status) => {
    render(<StatusBadge status={status} />);
    const badge = screen.getByText(STATUS[status].label);
    expect(badge).toHaveAttribute("data-status", status);
    expect(badge).toHaveAttribute("title", STATUS[status].hint);
  });
});

describe("ModelBadge", () => {
  it("marks the playbook as a baseline, not an LLM", () => {
    render(
      <ModelBadge
        model={{
          spec: "fake:playbook",
          kind: "baseline",
          label: "Rule-based playbook",
          description: "d",
        }}
      />,
    );
    expect(screen.getByText("Baseline, not an LLM")).toBeInTheDocument();
  });

  it("marks real models as LLMs", () => {
    render(<ModelBadge model={{ spec: "groq:x", kind: "llm", label: "x", description: "d" }} />);
    expect(screen.getByText("LLM")).toBeInTheDocument();
  });
});
