"use client";

import { useEffect, useId, useRef, useState } from "react";

import { ApiError, api } from "@/lib/api";
import { actionLabel, clockTime, percent } from "@/lib/format";
import { useStoredValue } from "@/lib/hooks";
import { gateState, type GateState } from "@/lib/timeline";
import type { InvestigationDetail } from "@/lib/types";

import { GateMark } from "./GateMark";
import { Button, Notice, uiStyles } from "./ui";
import styles from "./DecisionPanel.module.css";

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
 * The approval gate as a control. The agent proposes; only this decision can let the
 * proposed action run. After a decision the panel reports what happened.
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

  if (!request || !state) return null;
  const action = request.action;
  const noun = verb(request.tool);

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
      setError(exc instanceof ApiError ? exc.message : "The decision could not be sent.");
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
      <div className={styles.strip} aria-hidden="true" />
      <div className={styles.inner}>
        <div className={styles.heading}>
          <GateMark className={styles.mark} />
          <h2 id={`${ids}-title`}>{title(state, noun, action.target_service)}</h2>
        </div>

        <dl className={styles.facts}>
          <div>
            <dt>Proposed action</dt>
            <dd>
              {actionLabel(action.type)} of <strong>{action.target_service}</strong>
              <code className={styles.tool}>{request.tool}</code>
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
              The agent cannot run this itself. Nothing changes until someone approves; rejecting
              ends the investigation without touching the system.
            </p>
            <div className={styles.fields}>
              <div className={uiStyles.field}>
                <label htmlFor={`${ids}-reviewer`} className={uiStyles.label}>
                  Your name
                </label>
                <input
                  id={`${ids}-reviewer`}
                  className={uiStyles.input}
                  value={reviewer}
                  maxLength={64}
                  autoComplete="name"
                  onChange={(event) => setReviewer(event.target.value)}
                />
              </div>
              <div className={uiStyles.field}>
                <label htmlFor={`${ids}-comment`} className={uiStyles.label}>
                  Note <span className={styles.optional}>(optional)</span>
                </label>
                <textarea
                  id={`${ids}-comment`}
                  className={uiStyles.input}
                  value={comment}
                  maxLength={500}
                  rows={2}
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
                aria-describedby={`${ids}-title`}
              >
                {submitting === "approve" ? "Approving..." : `Approve ${noun}`}
              </Button>
              <Button
                variant="secondary"
                size="large"
                className={styles.reject}
                onClick={() => void decide("reject")}
                disabled={submitting !== null}
              >
                {submitting === "reject" ? "Rejecting..." : "Reject"}
              </Button>
            </div>
          </>
        ) : (
          <div className={styles.outcome} ref={outcome} tabIndex={-1} role="status">
            {approval ? (
              <p className={styles.who}>
                {approval.approved ? "Approved" : "Rejected"} by {approval.reviewer} at{" "}
                <time dateTime={approval.decided_at}>{clockTime(approval.decided_at)}</time>.
                {approval.comment ? (
                  <span className={styles.note}> “{approval.comment}”</span>
                ) : null}
              </p>
            ) : null}
            <p className={styles.result}>
              {state === "rejected" && "Nothing was executed."}
              {state === "executing" && `Running the ${noun}...`}
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
      </div>
    </section>
  );
}
