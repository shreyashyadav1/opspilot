import { Check, CircleAlert, X } from "lucide-react";
import type { ReactNode } from "react";

import { actionLabel, categoryLabel, clockTime, offset, percent, STATUS } from "@/lib/format";
import { buildTimeline, gateState, type GateState, type TimelineItem } from "@/lib/timeline";
import type { InvestigationDetail, TraceEvent } from "@/lib/types";

import { GateMark } from "./GateMark";
import { JsonBlock } from "./JsonBlock";
import { Signature } from "./Signature";
import styles from "./Timeline.module.css";

type Of<K extends TraceEvent["kind"]> = Extract<TraceEvent, { kind: K }>;

function When({ at, start }: { at: string; start: string }) {
  return (
    <div className={styles.when}>
      <time dateTime={at} className="numeric">
        {clockTime(at)}
      </time>
      <span className={`${styles.offset} numeric`}>{offset(start, at)}</span>
    </div>
  );
}

function ToolCall({ call }: { call: Of<"tool_call"> }) {
  const { tool, args, ok, latency_ms: latency, summary, output } = call.data;
  const violation = call.data.policy_violation;
  return (
    <li className={`${styles.call} ${ok ? "" : styles.callFailed}`}>
      <div className={styles.callHead}>
        <span className={styles.signature}>
          <Signature tool={tool} args={args} />
        </span>
        <span className={ok ? styles.ok : styles.failed}>
          {ok ? <Check size={14} aria-hidden="true" /> : <X size={14} aria-hidden="true" />}
          {ok ? "ok" : violation ? "refused" : "failed"}
          <span className="numeric">{Math.round(latency)} ms</span>
        </span>
      </div>
      <p className={styles.summary}>{summary}</p>
      {output !== null && output !== undefined ? (
        <details className={styles.details}>
          <summary>Tool output</summary>
          <JsonBlock value={output} label={`Output of ${tool}`} />
        </details>
      ) : null}
    </li>
  );
}

function Turn({ item, start }: { item: Extract<TimelineItem, { type: "turn" }>; start: string }) {
  const { turn, calls } = item;
  const submitted = turn.data.requested.includes("submit_diagnosis");
  const toolCount = calls.length;
  return (
    <li className={styles.entry}>
      <When at={turn.at} start={start} />
      <span className={styles.dot} aria-hidden="true" />
      <div className={styles.body}>
        <h3 className={styles.title}>Model turn {turn.data.turn}</h3>
        {turn.data.text ? <p className={styles.reasoning}>{turn.data.text}</p> : null}
        <p className={styles.meta}>
          {toolCount > 0
            ? `Requested ${toolCount} tool ${toolCount === 1 ? "call" : "calls"}${toolCount > 1 ? ", run in parallel" : ""}.`
            : submitted
              ? "Submitted a diagnosis."
              : "Replied without calling a tool."}
          {turn.data.input_tokens !== undefined ? (
            <span className="numeric">
              {" "}
              {turn.data.input_tokens} tokens in, {turn.data.output_tokens ?? 0} out
            </span>
          ) : null}
        </p>
        {toolCount > 0 ? (
          <ol className={styles.calls} aria-label={`Tool calls of turn ${turn.data.turn}`}>
            {calls.map((call) => (
              <ToolCall key={call.seq} call={call} />
            ))}
          </ol>
        ) : null}
      </div>
    </li>
  );
}

const GATE_TEXT: Record<GateState, string> = {
  pending: "Waiting for a decision. Nothing runs until someone approves.",
  executing: "Approved. The action is running.",
  executed: "Approved and executed.",
  failed: "Approved, but the action did not complete.",
  rejected: "Rejected. The action was not executed.",
};

function Gate({
  item,
  state,
  start,
}: {
  item: Extract<TimelineItem, { type: "gate" }>;
  state: GateState;
  start: string;
}) {
  const { request, decision } = item;
  const action = request.data.action;
  return (
    <li className={`${styles.gate} ${styles[`gate_${state}`]}`} aria-label="Approval gate">
      <div className={styles.gateBand}>
        <When at={request.at} start={start} />
        <GateMark className={styles.gateMark} />
        <div className={styles.body}>
          <h3 className={styles.title}>
            Approval gate: <code>{request.data.tool}</code> on {action.target_service}
          </h3>
          <p className={styles.gateText}>{GATE_TEXT[state]}</p>
          {decision ? (
            <p className={styles.meta}>
              {decision.data.decision === "approve" ? "Approved" : "Rejected"} by{" "}
              {decision.data.reviewer} at{" "}
              <time dateTime={decision.at}>{clockTime(decision.at)}</time>
              {decision.data.comment ? `: "${decision.data.comment}"` : "."}
            </p>
          ) : state === "pending" ? (
            <p className={styles.meta}>
              <a href="#decision">Review the proposal and decide</a>
            </p>
          ) : null}
        </div>
      </div>
      {state === "pending" || state === "rejected" ? (
        <div className={styles.ghost}>
          <span className={styles.ghostDot} aria-hidden="true" />
          <p>
            <Signature tool={request.data.tool} args={{ service: action.target_service }} />{" "}
            {state === "pending" ? "runs only after approval." : "was not executed."}
          </p>
        </div>
      ) : null}
    </li>
  );
}

function EventEntry({
  event,
  start,
}: {
  event: Extract<TimelineItem, { type: "event" }>["event"];
  start: string;
}) {
  let title: string;
  let detail: ReactNode = null;
  let tone: string | undefined;
  switch (event.kind) {
    case "alert":
      title = `Alert received${event.data.service ? ` on ${event.data.service}` : ""}`;
      detail = <p className={styles.meta}>{event.data.details ?? event.data.title}</p>;
      break;
    case "nudge":
      title = "Nudged the model back to its tools";
      detail = <p className={styles.meta}>{event.data.message}</p>;
      break;
    case "diagnosis": {
      const d = event.data.diagnosis;
      title = `Diagnosis submitted: ${d.root_cause_service}, ${categoryLabel(d.category).toLowerCase()}`;
      detail = (
        <p className={styles.meta}>
          Confidence {percent(d.confidence)}. Proposed:{" "}
          {actionLabel(d.proposed_action.type).toLowerCase()} ({d.proposed_action.target_service}).
        </p>
      );
      break;
    }
    case "diagnosis_invalid":
      title = "Diagnosis rejected by schema validation";
      detail = <p className={styles.meta}>{event.data.feedback}</p>;
      tone = styles.warn;
      break;
    case "decision":
      title = `${event.data.decision === "approve" ? "Approved" : "Rejected"} by ${event.data.reviewer}`;
      break;
    case "action":
      title = event.data.ok ? "Action executed" : "Action failed";
      detail = (
        <>
          <p className={styles.meta}>
            <Signature tool={event.data.tool} args={event.data.args} />
          </p>
          {event.data.summary ? <p className={styles.summary}>{event.data.summary}</p> : null}
        </>
      );
      tone = event.data.ok ? styles.good : styles.bad;
      break;
    case "finished":
      title = `Finished: ${STATUS[finishedStatus(event.data.outcome)].label.toLowerCase()}`;
      break;
    case "note":
      title = event.data.message;
      break;
    case "error":
      title = "Error";
      detail = <p className={styles.meta}>{event.data.message}</p>;
      tone = styles.bad;
      break;
    default:
      title = event.kind.replaceAll("_", " ");
  }
  return (
    <li className={`${styles.entry} ${tone ?? ""}`}>
      <When at={event.at} start={start} />
      <span className={styles.dot} aria-hidden="true">
        {event.kind === "error" ? <CircleAlert size={12} /> : null}
      </span>
      <div className={styles.body}>
        <h3 className={styles.title}>{title}</h3>
        {detail}
      </div>
    </li>
  );
}

function finishedStatus(outcome: string) {
  const map = {
    executed: "executed",
    failed: "action_failed",
    rejected: "rejected",
    advisory: "advisory",
    no_diagnosis: "no_diagnosis",
  } as const;
  return map[outcome as keyof typeof map] ?? "failed";
}

export function Timeline({ investigation }: { investigation: InvestigationDetail }) {
  const items = buildTimeline(investigation.trace);
  const start = investigation.trace[0]?.at ?? investigation.created_at;
  const state = gateState(investigation);
  const running = investigation.status === "running" || investigation.status === "queued";
  return (
    <section aria-labelledby="timeline-title" className={styles.section}>
      <h2 id="timeline-title" className={styles.heading}>
        Investigation timeline
      </h2>
      <ol className={styles.timeline}>
        {items.map((item) => {
          if (item.type === "turn") return <Turn key={item.key} item={item} start={start} />;
          if (item.type === "gate")
            return <Gate key={item.key} item={item} state={state ?? "pending"} start={start} />;
          return <EventEntry key={item.key} event={item.event} start={start} />;
        })}
        {running ? (
          <li className={`${styles.entry} ${styles.progress}`} aria-live="polite">
            <div className={styles.when} />
            <span className={`${styles.dot} ${styles.pulse}`} aria-hidden="true" />
            <div className={styles.body}>
              <p className={styles.meta}>
                {investigation.status === "queued"
                  ? "Waiting for a free investigation slot."
                  : "The agent is working. New steps appear as they happen."}
              </p>
            </div>
          </li>
        ) : null}
      </ol>
    </section>
  );
}
