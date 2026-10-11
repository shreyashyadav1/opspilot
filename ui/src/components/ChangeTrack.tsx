import { clockTime, leadTime } from "@/lib/format";
import { configValue, type RollbackPlan } from "@/lib/change";
import { callAnchor } from "@/lib/timeline";
import type { GateState } from "@/lib/timeline";

import styles from "./ChangeTrack.module.css";

const CAPTIONS: Record<GateState, { to: string; from: string; path: string | null }> = {
  pending: { to: "after rollback", from: "running now", path: null },
  executing: { to: "after rollback", from: "running now", path: "rolling back" },
  executed: { to: "running now", from: "rolled back", path: null },
  rejected: { to: "proposed", from: "still running", path: "not taken" },
  failed: { to: "intended", from: "still running", path: "did not complete" },
};

const CONFIG_LABELS: Record<GateState, [string, string]> = {
  pending: ["Now", "After"],
  executing: ["Now", "After"],
  executed: ["Before", "Now"],
  rejected: ["Now", "Proposed"],
  failed: ["Now", "Intended"],
};

const UNDO_VERB: Record<GateState, string> = {
  pending: "Undoes",
  executing: "Undoes",
  executed: "Undid",
  rejected: "Would have undone",
  failed: "Was to undo",
};

function sentence(plan: RollbackPlan, state: GateState): string {
  const target = plan.to ? `to ${plan.to}` : "to the version before the one running";
  const from = plan.from ? ` from ${plan.from}` : "";
  if (state === "executed") return `${plan.service} was rolled back${from} ${target}.`;
  if (state === "rejected") return `Not done: rolling ${plan.service} back${from} ${target}.`;
  return `Rolls ${plan.service} back${from} ${target}.`;
}

/**
 * The rollback drawn on a version line: older versions to the left, the change as a path from
 * the running version back to its predecessor. Magenta while it is only the agent's intent, green
 * once it ran, broken when it was rejected or failed.
 */
export function ChangeTrack({
  plan,
  state,
  alertAt,
  callNumber,
}: {
  plan: RollbackPlan;
  state: GateState;
  /** When the alert fired, to say how long before it the undone deploy went out. */
  alertAt: string;
  /** Number of the tool call the versions were read from, when there is one. */
  callNumber: number | null;
}) {
  const captions = CAPTIONS[state];
  const [beforeLabel, afterLabel] = CONFIG_LABELS[state];
  const undoes = plan.undoes;
  const lead = undoes ? leadTime(undoes.deployed_at, alertAt) : null;

  return (
    <div className={`${styles.change} ${styles[state]}`}>
      <p className="visually-hidden">{sentence(plan, state)}</p>
      <div className={styles.track}>
        <span className={`${styles.version} ${plan.to ? "" : styles.unknown}`} aria-hidden="true">
          {plan.to ?? "previous version"}
        </span>
        <span
          className={`${styles.version} ${styles.from} ${plan.from ? "" : styles.unknown}`}
          aria-hidden="true"
        >
          {plan.from ?? "running version"}
        </span>
        <span className={styles.rail} aria-hidden="true">
          <svg className={styles.head} viewBox="0 0 10 12" width="10" height="12">
            <path d="M10 0 L0 6 L10 12 Z" />
          </svg>
          <span className={styles.line} />
          <span className={styles.mover}>
            <span className={styles.dot} />
          </span>
          {captions.path ? <span className={styles.pathLabel}>{captions.path}</span> : null}
        </span>
        <span className={styles.caption} aria-hidden="true">
          {captions.to}
        </span>
        {plan.confirmed ? (
          <span className={styles.citation}>reported by the tool</span>
        ) : plan.sourceSeq !== null && callNumber !== null ? (
          <span className={styles.citation}>
            <a
              href={`#${callAnchor(plan.sourceSeq)}`}
              aria-label={`Versions read in call ${callNumber} of the timeline`}
            >
              read in call {callNumber}
            </a>
          </span>
        ) : null}
        <span className={`${styles.caption} ${styles.from}`} aria-hidden="true">
          {captions.from}
        </span>
      </div>

      {undoes ? (
        <p className={styles.undoes}>
          {UNDO_VERB[state]} the deploy{undoes.author ? ` ${undoes.author} shipped` : ""} at{" "}
          <time dateTime={undoes.deployed_at} className="numeric">
            {clockTime(undoes.deployed_at)}
          </time>
          {lead ? `, ${lead} the alert` : ""}
          {undoes.change_summary ? (
            <>
              : <q className={styles.summary}>{undoes.change_summary}</q>
            </>
          ) : (
            "."
          )}
        </p>
      ) : null}

      {plan.config.length > 0 ? (
        <dl className={styles.config}>
          {plan.config.map((change) => (
            <div key={change.key} className={styles.configRow}>
              <dt>
                <code>{change.key}</code>
              </dt>
              <dd>
                <span className={styles.configLabel}>{beforeLabel}</span>
                <code className={styles.configValue}>{configValue(change.before)}</code>
              </dd>
              <dd>
                <span className={styles.configLabel}>{afterLabel}</span>
                <code className={`${styles.configValue} ${styles.after}`}>
                  {configValue(change.after)}
                </code>
              </dd>
            </div>
          ))}
        </dl>
      ) : null}

      {!plan.confirmed && (plan.sourceSeq === null || callNumber === null) ? (
        <p className={styles.source}>
          The agent&apos;s tool calls did not report the versions; the rollback returns to the
          version before the one running.
        </p>
      ) : null}
    </div>
  );
}
