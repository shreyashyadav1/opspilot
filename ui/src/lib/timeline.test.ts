import { describe, expect, it } from "vitest";

import { executed, investigation, rejected, withDeployHistory } from "@/test/fixtures";

import { buildTimeline, callNumbers, citedCalls, evidenceCall, gateState } from "./timeline";

describe("buildTimeline", () => {
  it("nests tool calls under the model turn that requested them", () => {
    const items = buildTimeline(investigation().trace);
    expect(items.map((item) => item.type)).toEqual(["event", "turn", "turn", "event", "gate"]);
    const firstTurn = items[1];
    expect(firstTurn?.type === "turn" && firstTurn.calls.map((c) => c.data.tool)).toEqual([
      "get_service_health",
      "get_recent_deploys",
    ]);
  });

  it("attaches the decision to the approval gate", () => {
    const gate = buildTimeline(rejected().trace).find((item) => item.type === "gate");
    expect(gate?.type === "gate" && gate.decision?.data.reviewer).toBe("bob");
  });

  it("derives the gate state from the investigation status", () => {
    expect(gateState(investigation())).toBe("pending");
    expect(gateState(rejected())).toBe("rejected");
    expect(gateState(executed())).toBe("executed");
    expect(gateState(investigation({ approval_request: null }))).toBeNull();
  });
});

describe("callNumbers", () => {
  it("numbers tool calls in the order they ran", () => {
    expect([...callNumbers(investigation().trace)]).toEqual([
      [3, 1],
      [4, 2],
    ]);
  });
});

describe("evidenceCall", () => {
  it("cites the successful call the evidence came from", () => {
    const { trace } = withDeployHistory();
    const deploys = { source: "deploys" as const, service: "orders", detail: "1.8.4 changed it" };
    expect(evidenceCall(trace, deploys)?.seq).toBe(4);
  });

  it("never cites a failed call or one that did not happen", () => {
    const { trace } = investigation();
    const deploys = { source: "deploys" as const, service: "orders", detail: "1.8.4 changed it" };
    const logs = { source: "logs" as const, service: "orders", detail: "40x ERROR" };
    expect(evidenceCall(trace, deploys)).toBeNull();
    expect(evidenceCall(trace, logs)).toBeNull();
  });

  it("collects the calls the diagnosis cites", () => {
    expect([...citedCalls(withDeployHistory())]).toEqual([4]);
    expect(citedCalls(investigation({ diagnosis: null })).size).toBe(0);
  });

  it("prefers the metric the evidence names", () => {
    const base = investigation().trace;
    const metric = (seq: number, name: string) => ({
      seq,
      at: base[2]!.at,
      kind: "tool_call" as const,
      data: {
        turn: 1,
        tool: "query_metric",
        args: { service: "orders", metric: name },
        ok: true,
        error: null,
        latency_ms: 5,
        summary: `${name} reading`,
        output: null,
      },
    });
    const trace = [...base, metric(20, "error_rate"), metric(21, "latency_p95")];
    const evidence = { source: "metrics" as const, service: "orders", detail: "error_rate 0.74" };
    expect(evidenceCall(trace, evidence)?.seq).toBe(20);
  });
});
