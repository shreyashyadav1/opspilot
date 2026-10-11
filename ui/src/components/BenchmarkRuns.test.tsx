import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LLM, benchmarkRun } from "@/test/fixtures";
import { mockApi, renderWithSWR } from "@/test/utils";

import { BenchmarkRuns } from "./BenchmarkRuns";

describe("BenchmarkRuns", () => {
  it("labels the playbook as a baseline and simulated runs as harness checks", async () => {
    mockApi({
      "/api/benchmarks": [
        200,
        {
          runs: [
            benchmarkRun({
              id: "live-run",
              model: LLM,
              reportable: true,
              environment_note: "Live demo stack with real fault injection.",
              run: { ...benchmarkRun().run, environment: "live", model: LLM.spec },
            }),
            benchmarkRun(),
          ],
        },
      ],
    });
    renderWithSWR(<BenchmarkRuns />);
    const links = await screen.findAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual([
      "openai/gpt-oss-120b",
      "Rule-based playbook",
    ]);
    expect(screen.getByText("Baseline, not an LLM")).toBeInTheDocument();
    expect(screen.getByText("Simulated telemetry")).toBeInTheDocument();
    expect(screen.getByText(/these numbers are not benchmark results/)).toBeInTheDocument();
    expect(screen.getByText("Live demo stack")).toBeInTheDocument();
  });

  it("shows no numbers when no runs exist", async () => {
    mockApi({ "/api/benchmarks": [200, { runs: [] }] });
    renderWithSWR(<BenchmarkRuns />);
    expect(
      await screen.findByRole("heading", { name: "No benchmark runs yet" }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });
});
