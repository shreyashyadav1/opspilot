import type { ModelInfo } from "@/lib/types";

import styles from "./ModelBadge.module.css";

/** Says what kind of model produced a result, so the playbook is never mistaken for an LLM. */
export function ModelBadge({ model }: { model: ModelInfo }) {
  const baseline = model.kind === "baseline";
  return (
    <span
      className={`${styles.badge} ${baseline ? styles.baseline : styles.llm}`}
      title={model.description}
    >
      {baseline ? "Baseline, not an LLM" : "LLM"}
    </span>
  );
}
