import { actionPhrase, money } from "@/lib/format";
import type { InvestigationDetail } from "@/lib/types";

import { Notice } from "./ui";
import styles from "./NextStep.module.css";

/**
 * The right-hand column when nothing is held at the approval gate: what the agent is doing, or
 * what it recommends a person does next. (A gated action gets the decision panel instead.)
 */
export function NextStep({ investigation }: { investigation: InvestigationDetail }) {
  const { diagnosis, status, usage } = investigation;

  if (status === "running" || status === "queued") {
    const calls = `${usage.tool_calls} tool ${usage.tool_calls === 1 ? "call" : "calls"}`;
    const turns = `${usage.turns} model ${usage.turns === 1 ? "turn" : "turns"}`;
    return (
      <section className={styles.panel} aria-labelledby="next-step-title" aria-busy="true">
        <h2 id="next-step-title" className={styles.working}>
          <svg
            viewBox="0 0 16 16"
            width="20"
            height="20"
            aria-hidden="true"
            className={styles.spin}
          >
            <path
              d="M8 2.5a5.5 5.5 0 1 1-5.5 5.5"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
            />
          </svg>
          {status === "queued" ? "Queued" : "Investigating"}
        </h2>
        <p className={styles.progress}>
          {status === "queued"
            ? "Waiting for a free investigation slot."
            : `${turns} and ${calls} so far, at a cost of ${money(usage.cost_usd)}.`}
        </p>
      </section>
    );
  }

  if (!diagnosis) {
    return (
      <section className={styles.panel} aria-labelledby="next-step-title">
        <h2 id="next-step-title">No diagnosis</h2>
        <Notice tone={status === "no_diagnosis" ? "attention" : "danger"}>
          <p>
            {status === "no_diagnosis"
              ? "The agent used its turn budget without submitting a valid diagnosis."
              : (investigation.error ?? "The investigation ended without a diagnosis.")}
          </p>
          <p>Read the timeline for what it found, or start a new investigation with more detail.</p>
        </Notice>
      </section>
    );
  }

  const action = diagnosis.proposed_action;
  const executable = investigation.proposed_action?.executable ?? false;
  return (
    <section className={styles.panel} aria-labelledby="next-step-title">
      <h2 id="next-step-title">{executable ? "Proposed action" : "Recommended next step"}</h2>
      <p className={styles.action}>{actionPhrase(action.type, action.target_service)}.</p>
      <p className={styles.rationale}>{action.rationale}</p>
      <p className={styles.note}>
        {executable
          ? "The agent can run this only after someone approves it."
          : "A recommendation for the operator. The agent does not run it."}
      </p>
    </section>
  );
}
