import type { InvestigationDetail, TraceEvent } from "./types";

type Of<K extends TraceEvent["kind"]> = Extract<TraceEvent, { kind: K }>;

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
