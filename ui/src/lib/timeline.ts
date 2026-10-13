import type { Evidence, InvestigationDetail, TraceEvent } from "./types";

type Of<K extends TraceEvent["kind"]> = Extract<TraceEvent, { kind: K }>;

/** Tool calls are numbered in the order they ran: call 1, call 2, ... keyed by trace seq. */
export function callNumbers(trace: TraceEvent[]): Map<number, number> {
  const numbers = new Map<number, number>();
  for (const event of trace) {
    if (event.kind === "tool_call") numbers.set(event.seq, numbers.size + 1);
  }
  return numbers;
}

/** The anchor of a tool call in the timeline. */
export const callAnchor = (seq: number) => `call-${seq}`;

const SOURCE_TOOLS: Record<Evidence["source"], string> = {
  logs: "search_logs",
  metrics: "query_metric",
  deploys: "get_recent_deploys",
  health: "get_service_health",
};

/**
 * The tool call a piece of evidence most likely came from: the latest successful call of the
 * matching tool on that service (or on every service), preferring a metric the evidence names.
 * Null when no successful call matches, so a citation is never invented.
 */
export function evidenceCall(trace: TraceEvent[], evidence: Evidence): Of<"tool_call"> | null {
  const tool = SOURCE_TOOLS[evidence.source];
  const calls = trace.filter(
    (event): event is Of<"tool_call"> =>
      event.kind === "tool_call" && event.data.ok && event.data.tool === tool,
  );
  const scoped = calls.filter((call) => call.data.args.service === evidence.service);
  const unscoped = calls.filter((call) => call.data.args.service == null);
  const pool = scoped.length > 0 ? scoped : unscoped;
  if (evidence.source === "metrics") {
    const named = pool.filter((call) => {
      const metric = call.data.args.metric;
      if (typeof metric !== "string" || !evidence.detail.startsWith(metric)) return false;
      // "error_rate 0.74 ..." names error_rate, not a metric called "error".
      const next = evidence.detail.charAt(metric.length);
      return next === "" || next === " " || next === ":";
    });
    if (named.length > 0) return named[named.length - 1] ?? null;
  }
  return pool[pool.length - 1] ?? null;
}

export type TimelineItem =
  | { type: "turn"; key: string; turn: Of<"model_turn">; calls: Of<"tool_call">[] }
  | {
      type: "gate";
      key: string;
      request: Of<"approval_requested">;
      decision: Of<"decision"> | null;
    }
  | { type: "event"; key: string; event: Exclude<TraceEvent, Of<"model_turn" | "tool_call">> };

/**
 * Group the flat trace into what a reader follows: each model turn with the tool calls it
 * requested, and the approval gate with the decision taken on it.
 */
/** The tool calls the diagnosis cites as evidence, by trace seq. */
export function citedCalls(investigation: InvestigationDetail): Set<number> {
  const cited = new Set<number>();
  for (const item of investigation.diagnosis?.evidence ?? []) {
    const call = evidenceCall(investigation.trace, item);
    if (call) cited.add(call.seq);
  }
  return cited;
}

export function buildTimeline(trace: TraceEvent[]): TimelineItem[] {
  const items: TimelineItem[] = [];
  const turns = new Map<number, Extract<TimelineItem, { type: "turn" }>>();
  let gate: Extract<TimelineItem, { type: "gate" }> | null = null;

  for (const event of trace) {
    switch (event.kind) {
      case "model_turn": {
        const item = {
          type: "turn" as const,
          key: `turn-${event.seq}`,
          turn: event,
          calls: [],
        };
        turns.set(event.data.turn, item);
        items.push(item);
        break;
      }
      case "tool_call": {
        const owner = turns.get(event.data.turn);
        if (owner) owner.calls.push(event);
        break;
      }
      case "approval_requested": {
        gate = { type: "gate", key: `gate-${event.seq}`, request: event, decision: null };
        items.push(gate);
        break;
      }
      case "decision": {
        if (gate && !gate.decision) {
          gate.decision = event;
        } else {
          items.push({ type: "event", key: `event-${event.seq}`, event });
        }
        break;
      }
      default:
        items.push({ type: "event", key: `event-${event.seq}`, event });
    }
  }
  return items;
}

export type GateState = "pending" | "executing" | "executed" | "failed" | "rejected";

export function gateState(investigation: InvestigationDetail): GateState | null {
  if (!investigation.approval_request) return null;
  switch (investigation.status) {
    case "awaiting_approval":
      return "pending";
    case "executing":
      return "executing";
    case "executed":
      return "executed";
    case "action_failed":
      return "failed";
    case "rejected":
      return "rejected";
    default:
      return investigation.approval?.approved === false ? "rejected" : "failed";
  }
}
