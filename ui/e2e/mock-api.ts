import type { Page, Request } from "@playwright/test";

import type { InvestigationDetail } from "../src/lib/types";
import {
  benchmarkRun,
  config,
  executed,
  investigation,
  rejected,
  summary,
} from "../src/test/fixtures";

function toSummary(detail: InvestigationDetail) {
  return summary({
    id: detail.id,
    status: detail.status,
    approval_state: detail.approval_state,
    finished_at: detail.finished_at,
  });
}

function eventStream(detail: InvestigationDetail): string {
  const snapshot = `retry: 300\nevent: snapshot\ndata: ${JSON.stringify(detail)}\n\n`;
  const terminal = !["queued", "running", "awaiting_approval", "executing"].includes(detail.status);
  return terminal ? `${snapshot}event: end\ndata: {"status":"${detail.status}"}\n\n` : snapshot;
}

/**
 * Answers /api/* in the browser with one investigation waiting for approval. A decision
 * moves it to executed or rejected, as the real API would.
 */
export async function mockApi(page: Page) {
  let current = investigation();
  const decisions: unknown[] = [];

  await page.route("**/api/**", async (route) => {
    const request: Request = route.request();
    const path = new URL(request.url()).pathname.replace(/^\/api/, "");
    const method = request.method();

    if (path === "/config") return route.fulfill({ json: config() });
    if (path === "/investigations" && method === "GET") {
      return route.fulfill({ json: { investigations: [toSummary(current)] } });
    }
    if (path === `/investigations/${current.id}/events`) {
      return route.fulfill({
        status: 200,
        headers: { "content-type": "text/event-stream", "cache-control": "no-cache" },
        body: eventStream(current),
      });
    }
    if (path === `/investigations/${current.id}` && method === "GET") {
      return route.fulfill({ json: current });
    }
    if (path === `/investigations/${current.id}/decision` && method === "POST") {
      if (current.status !== "awaiting_approval") {
        return route.fulfill({ status: 409, json: { detail: "not waiting for a decision" } });
      }
      const body = request.postDataJSON() as { decision: string };
      decisions.push(body);
      current = body.decision === "approve" ? executed() : rejected();
      return route.fulfill({ json: current });
    }
    if (path === "/demo/catalog") return route.fulfill({ json: { fault_types: [] } });
    if (path === "/demo/faults") return route.fulfill({ json: { faults: [] } });
    if (path === "/benchmarks") return route.fulfill({ json: { runs: [benchmarkRun()] } });
    if (path === `/benchmarks/${benchmarkRun().id}`) {
      return route.fulfill({
        json: {
          ...benchmarkRun(),
          results: [
            {
              scenario: "payments-outage",
              expected: "payments / dependency_outage",
              score: { root_cause_correct: true, action_correct: true, steps: 4 },
              investigation: {},
            },
          ],
        },
      });
    }
    return route.fulfill({ status: 404, json: { detail: `no mock for ${method} ${path}` } });
  });

  return { decisions };
}
