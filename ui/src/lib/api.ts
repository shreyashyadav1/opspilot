// Typed client for the agent API. The browser only talks to this app's origin: `/api/*` is
// proxied to the agent API by the route handler in src/app/api/[...path]/route.ts.

import type {
  BenchmarkRun,
  BenchmarkRunDetail,
  FaultRecord,
  FaultType,
  InvestigationDetail,
  InvestigationSummary,
  Me,
  ServiceConfig,
} from "./types";

export const API_BASE = "/api";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function detailOf(body: unknown): string | null {
  if (!body || typeof body !== "object" || !("detail" in body)) return null;
  const detail = (body as { detail: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    // FastAPI validation errors: [{loc: [...], msg: "..."}]
    return detail
      .map((item) => {
        const loc = Array.isArray(item?.loc) ? item.loc.filter((p: unknown) => p !== "body") : [];
        return loc.length ? `${loc.join(".")}: ${item.msg}` : String(item?.msg ?? item);
      })
      .join("; ");
  }
  return null;
}

export async function request<T>(
  path: string,
  init: RequestInit = {},
  base: string = API_BASE,
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("accept", "application/json");
  if (init.body) headers.set("content-type", "application/json");
  let response: Response;
  try {
    response = await fetch(`${base}${path}`, { ...init, headers, cache: "no-store" });
  } catch {
    throw new ApiError(0, "The dashboard server did not respond. Check that it is running.");
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(
      response.status,
      detailOf(body) ?? `Request failed (HTTP ${response.status}).`,
    );
  }
  return body as T;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
  });

export interface StartInvestigation {
  alert: string;
  service?: string | null;
  details?: string | null;
  firing_minutes?: number | null;
  model?: string | null;
}

export interface DecisionBody {
  decision: "approve" | "reject";
  /** Only used when the API has no keys; otherwise the key names the reviewer. */
  reviewer?: string;
  comment?: string | null;
}

export interface FaultBody {
  type: string;
  target: string;
  params: Record<string, number>;
}

const id = (value: string) => encodeURIComponent(value);

export const api = {
  config: () => request<ServiceConfig>("/config"),
  me: () => request<Me>("/me"),
  signIn: (key: string) =>
    request<Me>("/session", { method: "POST", body: JSON.stringify({ key }) }, ""),
  signOut: () => fetch("/session", { method: "DELETE" }).then(() => undefined),
  investigations: () => request<{ investigations: InvestigationSummary[] }>("/investigations"),
  investigation: (investigationId: string) =>
    request<InvestigationDetail>(`/investigations/${id(investigationId)}`),
  start: (body: StartInvestigation) => post<InvestigationDetail>("/investigations", body),
  decide: (investigationId: string, body: DecisionBody) =>
    post<InvestigationDetail>(`/investigations/${id(investigationId)}/decision`, body),
  catalog: () => request<{ fault_types: FaultType[] }>("/demo/catalog"),
  faults: () => request<{ faults: FaultRecord[] }>("/demo/faults"),
  inject: (body: FaultBody) => post<FaultRecord>("/demo/faults", body),
  clearFault: (faultId: string) =>
    request<FaultRecord>(`/demo/faults/${id(faultId)}`, { method: "DELETE" }),
  resetDemo: () => post<{ status: string; resolved_faults: number }>("/demo/reset"),
  benchmarks: () => request<{ runs: BenchmarkRun[] }>("/benchmarks"),
  benchmark: (runId: string) => request<BenchmarkRunDetail>(`/benchmarks/${id(runId)}`),
};

export const eventsUrl = (investigationId: string) =>
  `${API_BASE}/investigations/${id(investigationId)}/events`;
