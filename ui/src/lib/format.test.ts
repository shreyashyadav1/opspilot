import { describe, expect, it } from "vitest";

import { actionPhrase, categoryLabel, offset, percent, relativeTime, signature } from "./format";

describe("format", () => {
  it("renders tool calls as function signatures", () => {
    expect(signature("query_metric", { service: "orders", metric: "up", window_minutes: 15 })).toBe(
      'query_metric(service="orders", metric="up", window_minutes=15)',
    );
    expect(signature("get_service_health", {})).toBe("get_service_health()");
  });

  it("formats offsets and relative times", () => {
    const start = "2026-09-28T21:04:12.000Z";
    expect(offset(start, "2026-09-28T21:04:12.400Z")).toBe("+0.4 s");
    expect(offset(start, "2026-09-28T21:04:42.000Z")).toBe("+30 s");
    expect(offset(start, "2026-09-28T21:14:12.000Z")).toBe("+10 min");
    const now = Date.parse("2026-09-28T21:10:00Z");
    expect(relativeTime("2026-09-28T21:09:40Z", now)).toBe("just now");
    expect(relativeTime("2026-09-28T21:06:00Z", now)).toBe("4 min ago");
    expect(relativeTime("2026-09-28T18:10:00Z", now)).toBe("3 h ago");
  });

  it("states proposed actions in plain words", () => {
    expect(actionPhrase("rollback_deploy", "orders")).toBe("Roll back the latest deploy of orders");
    expect(actionPhrase("escalate", "payments")).toBe("Escalate to the team that owns payments");
    expect(actionPhrase("drain_queue", "orders")).toBe("drain queue on orders");
  });

  it("labels categories and percentages", () => {
    expect(categoryLabel("resource_exhaustion")).toBe("Resource exhaustion");
    expect(categoryLabel("something_new")).toBe("something new");
    expect(percent(0.8)).toBe("80%");
    expect(percent(null)).toBe("n/a");
  });
});
