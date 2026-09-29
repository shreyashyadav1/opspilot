import { describe, expect, it } from "vitest";

import { executed, investigation, rejected } from "@/test/fixtures";

import { buildTimeline, gateState } from "./timeline";

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
