import { LoaderCircle } from "lucide-react";

import { actionLabel, categoryLabel, money, percent, signature, sourceLabel } from "@/lib/format";
import { callAnchor, callNumbers, evidenceCall } from "@/lib/timeline";
import type { InvestigationDetail } from "@/lib/types";

import { Notice } from "./ui";
import styles from "./DiagnosisPanel.module.css";

/** The cost figure, with a note when it is zero because the model is a non-LLM baseline rather
 * than because nothing was tracked. */
function CostNote({ investigation }: { investigation: InvestigationDetail }) {
  const { usage, model } = investigation;
  if (usage.cost_usd !== null && usage.cost_usd !== undefined && model.kind === "baseline") {
    return (
      <>
        {money(usage.cost_usd)}{" "}
        <span className={styles.note}>(rule-based baseline, no LLM calls)</span>
      </>
    );
  }
  return <>{money(usage.cost_usd)}</>;
}

export function DiagnosisPanel({ investigation }: { investigation: InvestigationDetail }) {
  const { diagnosis, status, usage } = investigation;

  if (!diagnosis) {
    if (status === "running" || status === "queued") {
      return (
        <section className={styles.panel} aria-labelledby="diagnosis-title" aria-busy="true">
          <h2 id="diagnosis-title">Diagnosis</h2>
          <p className={styles.working}>
            <LoaderCircle size={18} aria-hidden="true" className={styles.spin} />
            {status === "queued" ? "Queued" : "Investigating"}
          </p>
          <dl className={styles.progress}>
            <div>
              <dt>Model turns</dt>
              <dd className="numeric">{usage.turns}</dd>
            </div>
            <div>
              <dt>Tool calls</dt>
              <dd className="numeric">{usage.tool_calls}</dd>
            </div>
            <div>
              <dt>Cost so far</dt>
              <dd className="numeric">{money(usage.cost_usd)}</dd>
            </div>
          </dl>
        </section>
      );
    }
    return (
      <section className={styles.panel} aria-labelledby="diagnosis-title">
        <h2 id="diagnosis-title">Diagnosis</h2>
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
  // A held action is described, and decided, in the decision panel.
  const gated = investigation.approval_request !== null;
  const numbers = callNumbers(investigation.trace);
  return (
    <section className={styles.panel} aria-labelledby="diagnosis-title">
      <div className={styles.head}>
        <h2 id="diagnosis-title">Diagnosis</h2>
        <p className={styles.confidence}>
          <span className="numeric">{percent(diagnosis.confidence)}</span> confident
          <span className={styles.meter} aria-hidden="true">
            <span style={{ width: `${Math.round(diagnosis.confidence * 100)}%` }} />
          </span>
        </p>
      </div>
      <p className={styles.cause}>
        <span className={styles.service}>
          <span className="visually-hidden">Root cause service: </span>
          {diagnosis.root_cause_service}
        </span>
        <span className={styles.category}>
          <span className="visually-hidden">Category: </span>
          {categoryLabel(diagnosis.category)}
        </span>
      </p>
      <p className={styles.summary}>{diagnosis.summary}</p>

      <h3 className={styles.subhead}>Evidence the agent cited</h3>
      <ul className={styles.evidence}>
        {diagnosis.evidence.map((item, index) => {
          const call = evidenceCall(investigation.trace, item);
          const number = call ? numbers.get(call.seq) : undefined;
          return (
            <li key={index}>
              <span className={styles.source}>{sourceLabel(item.source)}</span>
              <span className={styles.detail}>
                <span className={styles.where}>{item.service}</span> {item.detail}
              </span>
              {call && number ? (
                <a
                  href={`#${callAnchor(call.seq)}`}
                  className={styles.cite}
                  aria-label={`Call ${number} in the timeline, ${signature(call.data.tool, call.data.args)}`}
                >
                  Call {number}
                </a>
              ) : null}
            </li>
          );
        })}
      </ul>

      {!gated ? (
        <div className={styles.recommendation}>
          <h3 className={styles.subhead}>
            {executable ? "Proposed action" : "Recommended action"}
          </h3>
          <p className={styles.action}>
            {actionLabel(action.type)}: <strong>{action.target_service}</strong>
          </p>
          <p className={styles.rationale}>{action.rationale}</p>
          <p className={styles.note}>
            {executable
              ? "The agent can run this only after someone approves it."
              : "A recommendation for the operator. The agent does not run it."}
          </p>
        </div>
      ) : null}

      {investigation.time_to_diagnosis_s !== null ? (
        <p className={`${styles.stats} numeric`}>
          Diagnosed in {investigation.time_to_diagnosis_s.toFixed(1)} s with {usage.turns} model
          turns and {usage.tool_calls} tool calls. Cost: <CostNote investigation={investigation} />
        </p>
      ) : null}
    </section>
  );
}
