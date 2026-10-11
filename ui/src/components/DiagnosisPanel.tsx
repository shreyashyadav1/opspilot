import { categoryLabel, money, percent, signature, sourceLabel } from "@/lib/format";
import { callAnchor, callNumbers, evidenceCall } from "@/lib/timeline";
import type { InvestigationDetail } from "@/lib/types";

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

/**
 * What the agent concluded and the evidence it cited, each piece linked to the tool call it came
 * from. It heads the evidence trail; what to do about it lives in the next-step column.
 */
export function DiagnosisPanel({ investigation }: { investigation: InvestigationDetail }) {
  const { diagnosis, usage } = investigation;
  if (!diagnosis) return null;
  const numbers = callNumbers(investigation.trace);
  return (
    <section className={styles.panel} aria-labelledby="diagnosis-title">
      <div className={styles.head}>
        <h2 id="diagnosis-title">Diagnosis</h2>
        <p className={styles.confidence}>
          <span className="numeric">{percent(diagnosis.confidence)}</span> confident
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

      {investigation.time_to_diagnosis_s !== null ? (
        <p className={`${styles.stats} numeric`}>
          Diagnosed in {investigation.time_to_diagnosis_s.toFixed(1)} s with {usage.turns} model
          turns and {usage.tool_calls} tool calls. Cost: <CostNote investigation={investigation} />
        </p>
      ) : null}
    </section>
  );
}
