import { describe, expect, it } from "vitest";

import {
  executedWithRecord,
  investigation,
  pendingTrace,
  withDeployHistory,
} from "@/test/fixtures";

import { configValue, rollbackPlan } from "./change";
import type { TraceEvent } from "./types";

describe("rollbackPlan", () => {
  it("reads the versions and the config change from the agent's deploy history", () => {
    const plan = rollbackPlan(withDeployHistory());
    expect(plan).toMatchObject({
      service: "orders",
      from: "1.8.4",
      to: "1.8.3",
      sourceSeq: 4,
      confirmed: false,
    });
    expect(plan?.undoes?.author).toBe("s.patel");
    expect(plan?.config).toEqual([
      {
        key: "payments.base-url",
        before: "http://payments-v2:8080",
        after: "http://payments:8080",
      },
    ]);
  });

  it("leaves the versions unknown when no tool call reported them", () => {
    // The default fixture's deploy-history call failed and its health check has no versions.
    const plan = rollbackPlan(investigation());
    expect(plan).toMatchObject({ service: "orders", from: null, to: null, undoes: null });
    expect(plan?.config).toEqual([]);
  });

  it("falls back to the running version a health check reported", () => {
    const trace = pendingTrace().map((event): TraceEvent =>
      event.kind === "tool_call" && event.data.tool === "get_service_health"
        ? {
            ...event,
            data: {
              ...event.data,
              output: { services: [{ service: "orders", status: "healthy", version: "1.8.4" }] },
            },
          }
        : event,
    );
    expect(rollbackPlan(investigation({ trace }))).toMatchObject({
      from: "1.8.4",
      to: null,
      sourceSeq: 3,
    });
  });

  it("goes back past a version that was already rolled back to", () => {
    const deploys = [
      {
        service: "orders",
        kind: "rollback",
        version: "1.8.3",
        deployed_at: "2026-09-28T21:00:00Z",
      },
      {
        service: "orders",
        kind: "deploy",
        version: "1.8.4",
        previous_version: "1.8.3",
        deployed_at: "2026-09-28T20:50:00Z",
      },
      {
        service: "orders",
        kind: "deploy",
        version: "1.8.3",
        previous_version: "1.8.2",
        deployed_at: "2026-09-28T20:00:00Z",
      },
    ];
    const base = withDeployHistory();
    const trace = base.trace.map((event): TraceEvent =>
      event.kind === "tool_call" && event.data.tool === "get_recent_deploys"
        ? { ...event, data: { ...event.data, output: { since_minutes: 120, deploys } } }
        : event,
    );
    expect(rollbackPlan({ ...base, trace })).toMatchObject({ from: "1.8.3", to: "1.8.2" });
  });

  it("uses the executed rollback's own record once it ran", () => {
    const plan = rollbackPlan(executedWithRecord());
    expect(plan).toMatchObject({ from: "1.8.4", to: "1.8.3", confirmed: true });
    expect(plan?.config).toEqual([
      {
        key: "payments.base-url",
        before: "http://payments-v2:8080",
        after: "http://payments:8080",
      },
    ]);
  });

  it("only describes rollbacks", () => {
    expect(rollbackPlan(investigation({ approval_request: null }))).toBeNull();
  });
});

describe("configValue", () => {
  it("shows strings as written and everything else as JSON", () => {
    expect(configValue("http://payments:8080")).toBe("http://payments:8080");
    expect(configValue(3)).toBe("3");
    expect(configValue(undefined)).toBe("not set");
  });
});
