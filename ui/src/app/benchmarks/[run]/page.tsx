import type { Metadata } from "next";

import { BenchmarkRunView } from "@/components/BenchmarkRunView";

export const metadata: Metadata = { title: "Benchmark run" };

export default async function BenchmarkRunPage({ params }: { params: Promise<{ run: string }> }) {
  const { run } = await params;
  return <BenchmarkRunView runId={decodeURIComponent(run)} />;
}
