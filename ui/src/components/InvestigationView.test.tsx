import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TRACE_ID, investigation } from "@/test/fixtures";
import { mockApi, renderWithSWR } from "@/test/utils";

import { InvestigationView } from "./InvestigationView";

describe("InvestigationView", () => {
  it("shows the trace id, so the run can be looked up in the trace backend", async () => {
    mockApi({ "/api/investigations/inv-0007": [200, investigation()] });
    renderWithSWR(<InvestigationView investigationId="inv-0007" />);
    expect(await screen.findByText(TRACE_ID)).toBeInTheDocument();
    expect(screen.getByText("Trace")).toBeInTheDocument();
  });

  it("leaves the trace line out when the run has no trace id", async () => {
    mockApi({ "/api/investigations/inv-0007": [200, investigation({ trace_id: null })] });
    renderWithSWR(<InvestigationView investigationId="inv-0007" />);
    expect(await screen.findByText("inv-0007")).toBeInTheDocument();
    expect(screen.queryByText("Trace")).not.toBeInTheDocument();
  });
});
