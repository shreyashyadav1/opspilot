"use client";

import { useEffect, useId, useRef, useState } from "react";

import { ApiError, api } from "@/lib/api";
import { rollbackPlan } from "@/lib/change";
import { actionLabel, clockTime, percent } from "@/lib/format";
import { useStoredValue } from "@/lib/hooks";
import { callNumbers, gateState, type GateState } from "@/lib/timeline";
import type { InvestigationDetail } from "@/lib/types";

import { ChangeTrack } from "./ChangeTrack";
import { GateMark } from "./GateMark";
import { Signature } from "./Signature";
import { Button, Notice, uiStyles } from "./ui";
import styles from "./DecisionPanel.module.css";

const RUNS: Record<GateState, string> = {
  pending: "Runs",
  executing: "Running",
  executed: "Ran",
  failed: "Tried to run",
  rejected: "Would have run",
};

function verb(tool: string): string {
  return tool === "rollback_deploy" ? "rollback" : "action";
}

function title(state: GateState, noun: string, target: string): string {
  const Noun = noun.charAt(0).toUpperCase() + noun.slice(1);
  switch (state) {
    case "pending":
      return `Approve the ${noun} of ${target}?`;
    case "rejected":
      return `${Noun} rejected`;
    case "failed":
      return `${Noun} approved, not completed`;
    default:
      return `${Noun} approved`;
  }
}

/**
 * The approval gate as a control. The agent proposes; only this decision can let the proposed
 * action run. It states exactly what would change (service, versions, config) from the agent's own
 * evidence, and after a decision reports what happened.
 */
export function DecisionPanel({
  investigation,
  onDecided,
}: {
  investigation: InvestigationDetail;
  onDecided: (updated: InvestigationDetail) => void;
}) {
  const ids = useId();
  const [reviewer, setReviewer] = useStoredValue("opspilot.reviewer", "operator");
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const outcome = useRef<HTMLDivElement>(null);
  const previous = useRef<string | null>(null);
  const state = gateState(investigation);
  const request = investigation.approval_request;

  // Move focus to the result only when a decision lands while this page is open.
  useEffect(() => {
    if (previous.current === "pending" && state && state !== "pending") outcome.current?.focus();
    previous.current = state;
  }, [state]);

  // A note typed for a pending decision is not thrown away by a stray reload or tab close.
  const unsent = state === "pending" && comment.trim() !== "";
  useEffect(() => {
    if (!unsent) return;
    const keep = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", keep);
    return () => window.removeEventListener("beforeunload", keep);
  }, [unsent]);

  if (!request || !state) return null;
  const action = request.action;
  const noun = verb(request.tool);
  const plan = rollbackPlan(investigation);
  const numbers = callNumbers(investigation.trace);
  const alertAt = investigation.trace[0]?.at ?? investigation.created_at;

  async function decide(decision: "approve" | "reject") {
    setSubmitting(decision);
    setError(null);
    try {
      const updated = await api.decide(investigation.id, {
        decision,
        reviewer: reviewer.trim() || "operator",
        comment: comment.trim() || null,
      });
      onDecided(updated);
    } catch (exc) {
      setError(
        exc instanceof ApiError
          ? `${exc.message} Reload the page to see where this investigation stands.`
          : "The decision could not be sent. Check that the agent API is running, then try again.",
      );
    } finally {
      setSubmitting(null);
    }
  }

  const approval = investigation.approval;
  const actionEvent = [...investigation.trace].reverse().find((event) => event.kind === "action");

  return (
    <section
      id="decision"
      className={`${styles.panel} ${styles[state]}`}
      aria-labelledby={`${ids}-title`}
      tabIndex={-1}
    >
      <div className={styles.heading}>
        <GateMark className={styles.mark} />
        <h2 id={`${ids}-title`}>{title(state, noun, action.target_service)}</h2>
      </div>

      {plan ? (
        <ChangeTrack
          plan={plan}
          state={state}
          alertAt={alertAt}
          callNumber={plan.sourceSeq === null ? null : (numbers.get(plan.sourceSeq) ?? null)}
        />
      ) : (
        <p className={styles.generic}>
          {actionLabel(action.type)} of <strong>{action.target_service}</strong>
        </p>
      )}

      <dl className={styles.facts}>
        <div>
          <dt>{RUNS[state]}</dt>
          <dd>
            <Signature tool={request.tool} args={{ service: action.target_service }} />
          </dd>
        </div>
        <div>
          <dt>Why</dt>
          <dd>{action.rationale}</dd>
        </div>
        <div>
          <dt>Agent confidence</dt>
          <dd className="numeric">{percent(request.confidence)}</dd>
        </div>
      </dl>

      {state === "pending" ? (
        <>
          <p className={styles.explain}>
            The agent cannot run this itself: nothing changes until someone approves.
          </p>
          <div className={styles.fields}>
            <div className={uiStyles.field}>
              <label htmlFor={`${ids}-reviewer`} className={uiStyles.label}>
                Your name
              </label>
              <input
                id={`${ids}-reviewer`}
                name="reviewer"
                className={uiStyles.input}
                value={reviewer}
                maxLength={64}
                autoComplete="name"
                spellCheck={false}
                onChange={(event) => setReviewer(event.target.value)}
              />
            </div>
            <div className={uiStyles.field}>
              <label htmlFor={`${ids}-comment`} className={uiStyles.label}>
                Note <span className={styles.optional}>(optional)</span>
              </label>
              <textarea
                id={`${ids}-comment`}
                name="comment"
                className={uiStyles.input}
                value={comment}
                maxLength={500}
                rows={1}
                autoComplete="off"
                onChange={(event) => setComment(event.target.value)}
              />
            </div>
          </div>
          {error ? (
            <Notice tone="danger" role="alert">
              <p>{error}</p>
            </Notice>
          ) : null}
          <div className={styles.buttons}>
            <Button
              variant="primary"
              size="large"
              onClick={() => void decide("approve")}
              disabled={submitting !== null}
              aria-describedby={`${ids}-title ${ids}-approve-effect`}
            >
              {submitting === "approve" ? "Approving…" : `Approve ${noun}`}
            </Button>
            <Button
              variant="secondary"
              size="large"
              onClick={() => void decide("reject")}
              disabled={submitting !== null}
              aria-describedby={`${ids}-reject-effect`}
            >
              {submitting === "reject" ? "Rejecting…" : "Reject"}
            </Button>
            <p id={`${ids}-approve-effect`} className={styles.effect}>
              {request.tool === "rollback_deploy"
                ? `Rolls ${action.target_service} back${plan?.to ? ` to ${plan.to}` : ""} now.`
                : "Runs the action now."}
            </p>
            <p id={`${ids}-reject-effect`} className={styles.effect}>
              Ends the investigation. Nothing is changed.
            </p>
          </div>
        </>
      ) : (
        <div className={styles.outcome} ref={outcome} tabIndex={-1} role="status">
          {approval ? (
            <p className={styles.who}>
              {approval.approved ? "Approved" : "Rejected"} by {approval.reviewer} at{" "}
              <time dateTime={approval.decided_at}>{clockTime(approval.decided_at)}</time>.
              {approval.comment ? (
                <>
                  {" "}
                  <q className={styles.note}>{approval.comment}</q>
                </>
              ) : null}
            </p>
          ) : null}
          <p className={styles.result}>
            {state === "rejected" && "Nothing was executed."}
            {state === "executing" && `Running the ${noun}…`}
            {state === "executed" &&
              (actionEvent?.kind === "action" && actionEvent.data.summary
                ? actionEvent.data.summary
                : "The action ran.")}
            {state === "failed" &&
              (investigation.error ??
                (actionEvent?.kind === "action" ? actionEvent.data.summary : null) ??
                "The action did not complete.")}
          </p>
        </div>
      )}
    </section>
  );
}
