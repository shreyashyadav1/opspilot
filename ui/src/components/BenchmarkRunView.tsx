"use client";

import { Check, ChevronLeft, X } from "lucide-react";
import Link from "next/link";

import { dateTime, number, percent } from "@/lib/format";
import { useBenchmark } from "@/lib/hooks";
import type { BenchmarkResult, BenchmarkSummary } from "@/lib/types";

import { EnvironmentTag } from "./BenchmarkRuns";
import { ModelBadge } from "./ModelBadge";
import { Notice, Skeleton } from "./ui";
import styles from "./Benchmark.module.css";

type MetricRow = { label: string; value: string; definition: string };

function metrics(s: BenchmarkSummary): MetricRow[] {
  const cost =
    s.mean_cost_usd === null || s.mean_cost_usd === undefined
      ? "n/a"
      : `$${s.mean_cost_usd.toFixed(4)}`;
  return [
    {
      label: "Root-cause accuracy",
      value: percent(s.root_cause_accuracy),
      definition: "Both the root-cause service and the fault category match the injected fault.",
    },
    {
      label: "Service / category accuracy",
      value: `${percent(s.service_accuracy)} / ${percent(s.category_accuracy)}`,
      definition: "Each half of the root cause on its own.",
    },
    {
      label: "Action accuracy",
      value: percent(s.action_accuracy),
      definition: "The proposed action type and target match the scenario’s expected action.",
    },
    {
      label: "Tool-call precision",
      value: percent(s.tool_call_precision),
      definition:
        "Successful, non-repeated calls on services relevant to the incident, over all calls.",
    },
    {
      label: "Evidence recall",
      value: percent(s.evidence_recall),
      definition: "Share of the scenario’s required observations the agent collected.",
    },
    {
      label: "Steps and tool calls",
      value: `${number(s.mean_steps)} turns, ${number(s.mean_tool_calls)} calls`,
      definition: "Mean model turns and tool calls per incident.",
    },
    {
      label: "Time to diagnosis",
      value: `${number(s.median_time_to_diagnosis_s, 2)} s median, ${number(s.max_time_to_diagnosis_s, 2)} s max`,
      definition: "From the start of the agent run to a schema-valid diagnosis.",
    },
    {
      label: "Tokens per incident",
      value: `${number(s.mean_input_tokens, 0)} in, ${number(s.mean_output_tokens, 0)} out`,
      definition: "As reported by the model; the playbook estimates them from text length.",
    },
    {
      label: "Cost per incident",
      value: cost,
      definition: "Token usage priced with evals/pricing.yaml.",
    },
    {
      label: "Unapproved writes",
      value: String(s.unapproved_writes ?? "n/a"),
      definition: "Write actions executed without an approval. Must be zero.",
    },
    {
      label: "Rollbacks verified",
      value: `${s.remediations_verified ?? 0} of ${s.actions_executed ?? 0}`,
      definition: "Approved rollbacks after which the control plane marked the fault resolved.",
    },
  ];
}

function Mark({ ok }: { ok: boolean }) {
  return ok ? (
    <span className={styles.yes}>
      <Check size={14} aria-hidden="true" /> yes
    </span>
  ) : (
    <span className={styles.no}>
      <X size={14} aria-hidden="true" /> no
    </span>
  );
}

function diagnosed(result: BenchmarkResult): string {
  const d = result.investigation.diagnosis;
  if (d) return `${d.root_cause_service} / ${d.category}`;
  return result.error ? `error: ${result.error}` : "no diagnosis";
}

export function BenchmarkRunView({ runId }: { runId: string }) {
  const { data, error } = useBenchmark(runId);
  if (error) {
    return (
      <div className={styles.page}>
        <BackLink />
        <Notice tone="danger" role="alert">
          {error.status === 404 ? (
            <p>
              There is no benchmark run {runId}. Runs are read from evals/results; pick one from the
              list.
            </p>
          ) : (
            <>
              <p>{error.message}</p>
              <p>Check that the agent API is running (make api-dev), then reload this page.</p>
            </>
          )}
        </Notice>
      </div>
    );
  }
  if (!data) {
    return (
      <div className={styles.page} aria-busy="true" aria-label="Loading benchmark run">
        <BackLink />
        <Skeleton width="50%" />
      </div>
    );
  }
  return (
    <div className={styles.page}>
      <BackLink />
      <header className={styles.header}>
        <h1>{data.model.label}</h1>
        <div className={styles.tags}>
          <ModelBadge model={data.model} />
          <EnvironmentTag run={data} />
        </div>
        <p className={styles.lede}>{data.model.description}</p>
        <dl className={styles.stats}>
          <div>
            <dt>Run</dt>
            <dd>
              <code>{data.run.run_id}</code>
            </dd>
          </div>
          <div>
            <dt>Started</dt>
            <dd>{dateTime(data.run.started_at)}</dd>
          </div>
          <div>
            <dt>Commit</dt>
            <dd>
              <code>{data.run.commit ?? "unknown"}</code>
            </dd>
          </div>
          <div>
            <dt>Approval policy</dt>
            <dd>{data.run.approval}</dd>
          </div>
          <div>
            <dt>Model spec</dt>
            <dd>
              <code>{data.run.model}</code>
            </dd>
          </div>
        </dl>
      </header>

      {!data.reportable ? (
        <Notice tone="attention">
          <p>{data.environment_note}</p>
          {data.model.kind === "baseline" ? (
            <p>The playbook is a fixed rule set. Its scores describe the harness, not an LLM.</p>
          ) : null}
        </Notice>
      ) : null}

      <section aria-labelledby="summary-title">
        <h2 id="summary-title" className={styles.sectionTitle}>
          Summary
        </h2>
        <div className={styles.tableWrap} tabIndex={0} aria-label="Summary metrics">
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">Metric</th>
                <th scope="col">Value</th>
                <th scope="col">Definition</th>
              </tr>
            </thead>
            <tbody>
              {metrics(data.summary).map((row) => (
                <tr key={row.label}>
                  <th scope="row">{row.label}</th>
                  <td className="numeric">{row.value}</td>
                  <td className={styles.definition}>{row.definition}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section aria-labelledby="scenarios-title">
        <h2 id="scenarios-title" className={styles.sectionTitle}>
          Scenarios
        </h2>
        <div className={styles.tableWrap} tabIndex={0} aria-label="Scenario results">
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">Scenario</th>
                <th scope="col">Expected</th>
                <th scope="col">Diagnosed</th>
                <th scope="col">Root cause</th>
                <th scope="col">Action</th>
                <th scope="col">Tool precision</th>
                <th scope="col">Steps</th>
                <th scope="col">Time (s)</th>
              </tr>
            </thead>
            <tbody>
              {data.results.map((result) => (
                <tr key={`${result.scenario}-${result.repeat ?? 0}`}>
                  <th scope="row">
                    <code>{result.scenario}</code>
                  </th>
                  <td>{result.expected}</td>
                  <td>{diagnosed(result)}</td>
                  <td>
                    <Mark ok={result.score.root_cause_correct} />
                  </td>
                  <td>
                    <Mark ok={result.score.action_correct} />
                  </td>
                  <td className="numeric">{percent(result.score.tool_call_precision)}</td>
                  <td className="numeric">{result.score.steps ?? "n/a"}</td>
                  <td className="numeric">{number(result.score.time_to_diagnosis_s ?? null, 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function BackLink() {
  return (
    <Link href="/benchmarks" className={styles.back}>
      <ChevronLeft size={16} aria-hidden="true" />
      All benchmark runs
    </Link>
  );
}
