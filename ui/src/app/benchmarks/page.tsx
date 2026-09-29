import type { Metadata } from "next";

import { BenchmarkRuns } from "@/components/BenchmarkRuns";

import styles from "../page.module.css";

export const metadata: Metadata = { title: "Benchmark" };

export default function BenchmarksPage() {
  return (
    <div className={styles.page}>
      <div className={styles.intro}>
        <h1>Benchmark</h1>
        <p>
          Runs of the fault-injection benchmark found in <code>evals/results</code>. Every scenario
          injects one fault with a known root cause and scores the diagnosis against it. Only runs
          that exist on disk are listed.
        </p>
      </div>
      <BenchmarkRuns />
    </div>
  );
}
