import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { mockApi } from "./mock-api";

async function expectNoSeriousA11yIssues(page: Page) {
  const results = await new AxeBuilder({ page }).analyze();
  const serious = results.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map(
      (v) =>
        `${v.id}: ${v.nodes.map((n) => `${n.target.join(" ")} (${n.failureSummary})`).join("; ")}`,
    );
  expect(serious).toEqual([]);
}

test("an operator approves a proposed rollback", async ({ page }) => {
  const api = await mockApi(page);
  await page.goto("/");

  const pending = page.getByRole("list", { name: "Waiting for your decision" });
  await expect(pending.getByText("Needs approval")).toBeVisible();
  await expectNoSeriousA11yIssues(page);
  await pending.getByRole("link", { name: "Checkout error rate above SLO" }).click();

  await expect(
    page.getByRole("heading", { name: "Approve the rollback of orders?" }),
  ).toBeVisible();
  const gate = page.getByRole("listitem", { name: "Approval gate" });
  await expect(gate).toContainText('rollback_deploy(service="orders") runs only after approval.');
  await expect(page.getByText("get_recent_deploys(since_minutes=60)")).toBeVisible();
  await expectNoSeriousA11yIssues(page);

  await page.getByLabel("Your name").fill("alice");
  await page.getByRole("button", { name: "Approve rollback" }).click();

  await expect(page.getByRole("status")).toContainText("orders rolled back from 1.8.4 to 1.8.3.");
  await expect(page.getByText("Executed", { exact: true }).first()).toBeVisible();
  await expect(gate).toContainText("Approved and executed.");
  expect(api.decisions).toEqual([{ decision: "approve", reviewer: "alice", comment: null }]);
});

test("a rejected action is never shown as executed", async ({ page }) => {
  const api = await mockApi(page);
  await page.goto("/investigations/inv-0007");

  await page.getByRole("button", { name: "Reject" }).click();

  await expect(page.getByRole("heading", { name: "Rollback rejected" })).toBeVisible();
  await expect(page.getByRole("status")).toContainText("Nothing was executed.");
  await expect(page.getByRole("listitem", { name: "Approval gate" })).toContainText(
    'rollback_deploy(service="orders") was not executed.',
  );
  await expect(page.getByText("Action executed")).toHaveCount(0);
  expect(api.decisions).toHaveLength(1);
});

test("benchmark runs are labelled with what they measure", async ({ page }) => {
  await mockApi(page);
  await page.goto("/benchmarks");

  const runs = page.getByRole("list", { name: "Benchmark runs" });
  await expect(runs.getByText("Baseline, not an LLM")).toBeVisible();
  await expect(runs.getByText("Simulated telemetry", { exact: true })).toBeVisible();
  await expectNoSeriousA11yIssues(page);

  await page.getByRole("link", { name: "Rule-based playbook" }).click();
  await expect(page.getByText(/these numbers are not benchmark results/)).toBeVisible();
  await expect(page.getByRole("rowheader", { name: "payments-outage" })).toBeVisible();
  await expectNoSeriousA11yIssues(page);
});
