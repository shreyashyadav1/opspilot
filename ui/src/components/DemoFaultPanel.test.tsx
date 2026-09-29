import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { config } from "@/test/fixtures";
import { mockApi, renderWithSWR } from "@/test/utils";

import { DemoFaultPanel } from "./DemoFaultPanel";

const CATALOG = {
  fault_types: [
    {
      type: "latency_spike",
      category: "latency",
      description: "Adds a delay to the target's business requests.",
      targets: ["orders", "payments", "storefront"],
      params: { delay_ms: { type: "integer", default: 1200, minimum: 50, maximum: 10000 } },
    },
    {
      type: "db_pool_exhaustion",
      category: "resource_exhaustion",
      description: "A background export job leaks database connections until the pool is empty.",
      targets: ["orders"],
      params: {},
    },
  ],
};

const FAULTS = {
  faults: [
    {
      id: "flt-0001",
      type: "bad_config_deploy",
      target: "orders",
      params: {},
      ground_truth: { service: "orders", category: "bad_deploy" },
      injected_at: "2026-09-28T21:00:00Z",
      deploy_id: "dep-0010",
      resolved_at: "2026-09-28T21:05:00Z",
      resolved_by: "rollback",
      active: false,
    },
  ],
};

describe("DemoFaultPanel", () => {
  it("explains how to enable fault injection when it is off", async () => {
    mockApi({ "/api/config": [200, config({ demo_enabled: false })] });
    renderWithSWR(<DemoFaultPanel />);
    expect(await screen.findByText(/Fault injection is off/)).toBeInTheDocument();
  });

  it("injects the chosen fault into an allowed target", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "/api/config": [200, config()],
      "/api/demo/catalog": [200, CATALOG],
      "/api/demo/faults": [200, FAULTS],
      "POST /api/demo/faults": (init) => [
        201,
        {
          ...FAULTS.faults[0],
          ...JSON.parse(String(init?.body)),
          id: "flt-0002",
          active: true,
        },
      ],
    });
    renderWithSWR(<DemoFaultPanel />);

    expect(
      await screen.findByText("Resolved by a rollback at", { exact: false }),
    ).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Fault"), "db_pool_exhaustion");
    expect(screen.getByLabelText("Target service")).toHaveTextContent("orders");
    expect(screen.queryByLabelText("Delay (ms)")).not.toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Fault"), "latency_spike");
    await user.selectOptions(screen.getByLabelText("Target service"), "payments");
    await user.clear(screen.getByLabelText("Delay (ms)"));
    await user.type(screen.getByLabelText("Delay (ms)"), "900");
    await user.click(screen.getByRole("button", { name: "Inject fault" }));

    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({
      type: "latency_spike",
      target: "payments",
      params: { delay_ms: 900 },
    });
    expect(
      await screen.findByText(/Injected latency spike into payments \(flt-0002\)/),
    ).toBeInTheDocument();
  });
});
