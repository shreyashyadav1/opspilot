import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { summary } from "@/test/fixtures";
import { mockApi, renderWithSWR } from "@/test/utils";

import { IncidentList } from "./IncidentList";

describe("IncidentList", () => {
  it("puts investigations that need a decision first", async () => {
    mockApi({
      "/api/investigations": [
        200,
        {
          investigations: [
            summary({
              id: "inv-0003",
              status: "advisory",
              alert: { ...summary().alert, title: "Checkout p95 latency above SLO" },
            }),
            summary({ id: "inv-0002", status: "awaiting_approval" }),
            summary({
              id: "inv-0001",
              status: "running",
              root_cause_service: null,
              category: null,
            }),
          ],
        },
      ],
    });
    renderWithSWR(<IncidentList />);

    const pending = await screen.findByRole("list", { name: "Waiting for your decision" });
    expect(within(pending).getAllByRole("listitem")).toHaveLength(1);
    expect(within(pending).getByText("Needs approval")).toBeInTheDocument();
    expect(
      within(pending).getByRole("link", { name: "Checkout error rate above SLO" }),
    ).toHaveAttribute("href", "/investigations/inv-0002");

    const rest = screen.getByRole("list", { name: "Investigations" });
    const rows = within(rest).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("Diagnosed");
    expect(rows[1]).toHaveTextContent("Investigating");
    expect(rows[1]).toHaveTextContent("Not diagnosed yet");
  });

  it("invites a first investigation when there are none", async () => {
    mockApi({ "/api/investigations": [200, { investigations: [] }] });
    renderWithSWR(<IncidentList />);
    expect(
      await screen.findByRole("heading", { name: "No investigations yet" }),
    ).toBeInTheDocument();
  });

  it("explains what to do when the API is down", async () => {
    mockApi({
      "/api/investigations": [
        502,
        {
          detail: "The agent API is not reachable at http://127.0.0.1:8180. Is it running?",
        },
      ],
    });
    renderWithSWR(<IncidentList />);
    expect(await screen.findByRole("alert")).toHaveTextContent("not reachable");
  });
});
