"use client";

import Link from "next/link";

import { dateTime, percent } from "@/lib/format";
import { useBenchmarks } from "@/lib/hooks";
import type { BenchmarkRun } from "@/lib/types";

import { ModelBadge } from "./ModelBadge";
import { EmptyState, Notice, Skeleton } from "./ui";
import styles from "./Benchmark.module.css";

export function EnvironmentTag({ run }: { run: BenchmarkRun }) {
  const simulated = run.run.environment === "simulated";
  return (
    <span className={`${styles.env} ${simulated ? styles.simulated : styles.live}`}>
      {simulated ? "Simulated telemetry" : "Live demo stack"}
    </span>
  );
}

function RunRow({ run }: { run: BenchmarkRun }) {
  const s = run.summary;
  return (
    <li className={styles.run}>
      <div className={styles.runHead}>
        <Link href={`/benchmarks/${encodeURIComponent(run.id)}`} className={styles.runLink}>
          {run.model.label}
        </Link>
        <ModelBadge model={run.model} />
        <EnvironmentTag run={run} />
      </div>
      <p className={styles.note}>{run.environment_note}</p>
      <dl className={styles.stats}>
        <div>
          <dt>Started</dt>
          <dd>
            <time dateTime={run.run.started_at}>{dateTime(run.run.started_at)}</time>
          </dd>
        </div>
        <div>
          <dt>Scenarios</dt>
          <dd className="numeric">
            {s.scenarios ?? "n/a"}
            {run.run.repeats > 1 ? ` (${run.run.repeats} repeats each)` : ""}
          </dd>
        </div>
        <div>
          <dt>Root-cause accuracy</dt>
          <dd className="numeric">{percent(s.root_cause_accuracy)}</dd>
        </div>
        <div>
          <dt>Action accuracy</dt>
          <dd className="numeric">{percent(s.action_accuracy)}</dd>
        </div>
        <div>
          <dt>Commit</dt>
          <dd>
            <code>{run.run.commit ?? "unknown"}</code>
          </dd>
        </div>
      </dl>
    </li>
  );
}

export function BenchmarkRuns() {
  const { data, error, isLoading } = useBenchmarks();
  if (error) {
    return (
      <Notice tone="danger" role="alert">
        <p>Could not load benchmark runs: {error.message}</p>
      </Notice>
    );
  }
  if (isLoading || !data) {
    return (
      <div aria-busy="true" aria-label="Loading benchmark runs" className={styles.loading}>
        <Skeleton width="60%" />
        <Skeleton width="40%" />
      </div>
    );
  }
  if (data.runs.length === 0) {
    return (
      <EmptyState title="No benchmark runs yet">
        <p>
          Runs appear here once <code>opspilot-eval</code> has written results to{" "}
          <code>evals/results</code>. <code>make eval-fake</code> runs the rule-based playbook on
          simulated telemetry in a few seconds; <code>make eval</code> runs an LLM against the live
          stack.
        </p>
      </EmptyState>
    );
  }
  return (
    <ul className={styles.runs} aria-label="Benchmark runs">
      {data.runs.map((run) => (
        <RunRow key={run.id} run={run} />
      ))}
    </ul>
  );
}
