"use client";

import { Ban, Check, CircleAlert, X } from "lucide-react";
import { useState, type ReactNode } from "react";

import { actionLabel, categoryLabel, clockTime, offset, percent } from "@/lib/format";
import {
  buildTimeline,
  callAnchor,
  callNumbers,
  citedCalls,
  gateState,
  type GateState,
  type TimelineItem,
} from "@/lib/timeline";
import type { InvestigationDetail, Status, TraceEvent } from "@/lib/types";

import { GateMark } from "./GateMark";
import { JsonBlock } from "./JsonBlock";
import { ReviewerName, UNVERIFIED } from "./ReviewerName";
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

function ToolCall({
  call,
  number,
  fresh,
  cited,
}: {
  call: Of<"tool_call">;
  number: number | undefined;
  fresh: boolean;
  /** The diagnosis cites this call as evidence. */
  cited: boolean;
}) {
  const { tool, args, ok, latency_ms: latency, summary, output } = call.data;
  const violation = call.data.policy_violation;
  const Icon = ok ? Check : violation ? Ban : X;
  return (
    <li
      id={callAnchor(call.seq)}
      className={`${styles.call} ${ok ? "" : styles.callFailed} ${cited ? styles.cited : ""}`}
      data-fresh={fresh || undefined}
    >
      <span
        className={`${styles.callNo} numeric`}
        title={cited ? "Cited as evidence in the diagnosis" : undefined}
      >
        <span className="visually-hidden">Call </span>
        {number}
        {cited ? <span className="visually-hidden">, cited as evidence</span> : null}
      </span>
      <div className={styles.callMain}>
        <div className={styles.callHead}>
          <span className={styles.signature}>
            <Signature tool={tool} args={args} />
          </span>
          <span className={ok ? styles.ok : styles.failed}>
            <Icon size={14} aria-hidden="true" />
            {ok ? "ok" : violation ? "refused" : "failed"}
            <span className={`${styles.latency} numeric`}>{Math.round(latency)} ms</span>
          </span>
        </div>
        <p className={styles.summary}>{summary}</p>
        {output !== null && output !== undefined ? (
          <details className={styles.details}>
            <summary>Tool output</summary>
            <JsonBlock value={output} label={`Output of ${tool}`} />
          </details>
        ) : null}
      </div>
    </li>
  );
}

function Turn({
  item,
  start,
  numbers,
  cited,
  isFresh,
}: {
  item: Extract<TimelineItem, { type: "turn" }>;
  start: string;
  numbers: Map<number, number>;
  cited: Set<number>;
  isFresh: (key: string) => boolean;
}) {
  const { turn, calls } = item;
  const submitted = turn.data.requested.includes("submit_diagnosis");
  const toolCount = calls.length;
  const tokens = (turn.data.input_tokens ?? 0) + (turn.data.output_tokens ?? 0);
  return (
    <li className={styles.entry} data-fresh={isFresh(item.key) || undefined}>
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
          {turn.data.input_tokens !== undefined && tokens > 0 ? (
            <span className="numeric">
              {" "}
              {turn.data.input_tokens} tokens in, {turn.data.output_tokens ?? 0} out.
            </span>
          ) : null}
        </p>
        {toolCount > 0 ? (
          <ol className={styles.calls} aria-label={`Tool calls of turn ${turn.data.turn}`}>
            {calls.map((call) => (
              <ToolCall
                key={call.seq}
                call={call}
                number={numbers.get(call.seq)}
                fresh={isFresh(callAnchor(call.seq))}
                cited={cited.has(call.seq)}
              />
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
  fresh,
}: {
  item: Extract<TimelineItem, { type: "gate" }>;
  state: GateState;
  start: string;
  fresh: boolean;
}) {
  const { request, decision } = item;
  const action = request.data.action;
  return (
    <li
      className={`${styles.gate} ${styles[`gate_${state}`]}`}
      aria-label="Approval gate"
      data-fresh={fresh || undefined}
    >
      <div className={styles.gateBand}>
        <When at={request.at} start={start} />
        <GateMark className={styles.gateMark} />
        <div className={styles.body}>
          <h3 className={styles.title}>
            Approval gate for <code>{request.data.tool}</code> on {action.target_service}
          </h3>
          <p className={styles.gateText}>{GATE_TEXT[state]}</p>
          {decision ? (
            <p className={styles.meta}>
              {decision.data.decision === "approve" ? "Approved" : "Rejected"} by{" "}
              <ReviewerName
                name={decision.data.reviewer}
                authenticated={decision.data.authenticated}
              />{" "}
              at <time dateTime={decision.at}>{clockTime(decision.at)}</time>
              {decision.data.comment ? `: “${decision.data.comment}”` : "."}
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
  fresh,
}: {
  event: Extract<TimelineItem, { type: "event" }>["event"];
  start: string;
  fresh: boolean;
}) {
  let title: string;
  let detail: ReactNode = null;
  let tone: string | undefined;
  switch (event.kind) {
    case "alert":
      title = `Alert received${event.data.service ? ` on ${event.data.service}` : ""}`;
      detail = <p className={styles.meta}>{event.data.details ?? event.data.title}</p>;
      tone = styles.origin;
      break;
    case "nudge":
      title = "Nudged the model back to its tools";
      detail = <p className={styles.meta}>{event.data.message}</p>;
      break;
    case "diagnosis": {
      const d = event.data.diagnosis;
      title = `Diagnosed ${categoryLabel(d.category).toLowerCase()} in ${d.root_cause_service}`;
      detail = (
        <p className={styles.meta}>
          Confidence {percent(d.confidence)}. Proposed:{" "}
          {actionLabel(d.proposed_action.type).toLowerCase()} ({d.proposed_action.target_service}).
        </p>
      );
      tone = styles.verdict;
      break;
    }
    case "diagnosis_invalid":
      title = "Diagnosis rejected by schema validation";
      detail = <p className={styles.meta}>{event.data.feedback}</p>;
      tone = styles.warn;
      break;
    case "decision":
      title = `${event.data.decision === "approve" ? "Approved" : "Rejected"} by ${event.data.reviewer}`;
      if (event.data.authenticated !== true) title += ` (${UNVERIFIED})`;
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
      title = FINISHED[finishedStatus(event.data.outcome)] ?? "Finished";
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
    <li className={`${styles.entry} ${tone ?? ""}`} data-fresh={fresh || undefined}>
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

const FINISHED: Partial<Record<Status, string>> = {
  executed: "Finished after the approved action ran",
  action_failed: "Finished after the approved action failed",
  rejected: "Finished without acting",
  advisory: "Finished with a recommendation",
  no_diagnosis: "Finished without a diagnosis",
  failed: "Stopped with an error",
};

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

function keysOf(items: TimelineItem[]): Set<string> {
  const keys = new Set<string>();
  for (const item of items) {
    keys.add(item.key);
    if (item.type === "turn") for (const call of item.calls) keys.add(callAnchor(call.seq));
  }
  return keys;
}

export function Timeline({ investigation }: { investigation: InvestigationDetail }) {
  const items = buildTimeline(investigation.trace);
  const numbers = callNumbers(investigation.trace);
  const cited = citedCalls(investigation);
  const start = investigation.trace[0]?.at ?? investigation.created_at;
  const state = gateState(investigation);
  const running = investigation.status === "running" || investigation.status === "queued";
  // Steps on screen at first render are history; anything that arrives later gets a brief mark.
  const [initial] = useState(() => keysOf(items));
  const isFresh = (key: string) => !initial.has(key);
  const last = investigation.trace[investigation.trace.length - 1]?.at;
  return (
    <section aria-labelledby="timeline-title" className={styles.section}>
      <div className={styles.headingRow}>
        <h2 id="timeline-title" className={styles.heading}>
          Investigation timeline
        </h2>
        {numbers.size > 0 && last ? (
          <p className={`${styles.count} numeric`}>
            {numbers.size} tool {numbers.size === 1 ? "call" : "calls"} in{" "}
            {offset(start, last).replace("+", "")}
            {cited.size > 0 ? `, ${cited.size} cited as evidence` : ""}
          </p>
        ) : null}
      </div>
      <ol className={styles.timeline}>
        {items.map((item) => {
          if (item.type === "turn")
            return (
              <Turn
                key={item.key}
                item={item}
                start={start}
                numbers={numbers}
                cited={cited}
                isFresh={isFresh}
              />
            );
          if (item.type === "gate")
            return (
              <Gate
                key={item.key}
                item={item}
                state={state ?? "pending"}
                start={start}
                fresh={isFresh(item.key)}
              />
            );
          return (
            <EventEntry key={item.key} event={item.event} start={start} fresh={isFresh(item.key)} />
          );
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
