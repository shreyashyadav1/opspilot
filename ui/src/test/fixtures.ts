import type {
  BenchmarkRun,
  InvestigationDetail,
  InvestigationSummary,
  ServiceConfig,
  TraceEvent,
} from "@/lib/types";

const at = (seconds: number) =>
  new Date(Date.UTC(2026, 8, 28, 21, 4, 12) + seconds * 1000).toISOString();

export const TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736";

export const PLAYBOOK = {
  spec: "fake:playbook",
  kind: "baseline" as const,
  label: "Rule-based playbook",
  description:
    "A fixed triage runbook with simple rules over the tool results. A deterministic baseline, not an LLM.",
};

export const LLM = {
  spec: "groq:openai/gpt-oss-120b",
  kind: "llm" as const,
  label: "openai/gpt-oss-120b",
  description: "LLM served by Groq.",
};

const DIAGNOSIS = {
  root_cause_service: "orders",
  category: "bad_deploy",
  summary: "orders started failing right after its latest deploy changed payments.base-url.",
  evidence: [
    {
      source: "deploys" as const,
      service: "orders",
      detail: "1.8.4 changed payments.base-url to http://payments-v2:8080",
    },
    {
      source: "logs" as const,
      service: "orders",
      detail: "40x ERROR: UnknownHostException payments-v2",
    },
  ],
  confidence: 0.8,
  proposed_action: {
    type: "rollback_deploy",
    target_service: "orders",
    rationale: "Revert the deploy that introduced the failures.",
  },
};

const REQUEST = {
  type: "approval_request" as const,
  tool: "rollback_deploy",
  action: DIAGNOSIS.proposed_action,
  root_cause_service: "orders",
  category: "bad_deploy",
  confidence: 0.8,
  summary: DIAGNOSIS.summary,
  evidence: DIAGNOSIS.evidence,
};

export function pendingTrace(): TraceEvent[] {
  return [
    {
      seq: 1,
      at: at(0),
      kind: "alert",
      data: {
        title: "Checkout error rate above SLO",
        service: "storefront",
        details: "POST /checkout 5xx rate is above the 2% SLO.",
        firing_minutes: null,
      },
    },
    {
      seq: 2,
      at: at(0.4),
      kind: "model_turn",
      data: { turn: 1, text: "", requested: ["get_service_health", "get_recent_deploys"] },
    },
    {
      seq: 3,
      at: at(0.5),
      kind: "tool_call",
      data: {
        turn: 1,
        tool: "get_service_health",
        args: {},
        ok: true,
        error: null,
        latency_ms: 11,
        summary: "orders unhealthy (HTTP 503); 2 healthy.",
        output: {
          services: [{ service: "orders", status: "unhealthy", http_status: 503 }],
        },
      },
    },
    {
      seq: 4,
      at: at(0.5),
      kind: "tool_call",
      data: {
        turn: 1,
        tool: "get_recent_deploys",
        args: { since_minutes: 60 },
        ok: false,
        error: "deploy history unavailable",
        latency_ms: 30,
        summary: "Failed: deploy history unavailable",
        output: "deploy history unavailable",
      },
    },
    {
      seq: 5,
      at: at(0.9),
      kind: "model_turn",
      data: { turn: 2, text: "The deploy explains it.", requested: ["submit_diagnosis"] },
    },
    { seq: 6, at: at(1), kind: "diagnosis", data: { diagnosis: DIAGNOSIS } },
    { seq: 7, at: at(1.1), kind: "approval_requested", data: REQUEST },
  ];
}

export function investigation(overrides: Partial<InvestigationDetail> = {}): InvestigationDetail {
  return {
    id: "inv-0007",
    status: "awaiting_approval",
    alert: {
      title: "Checkout error rate above SLO",
      service: "storefront",
      details: "POST /checkout 5xx rate is above the 2% SLO.",
      firing_minutes: null,
    },
    model: PLAYBOOK,
    created_at: at(0),
    updated_at: at(1.1),
    finished_at: null,
    root_cause_service: "orders",
    category: "bad_deploy",
    confidence: 0.8,
    proposed_action: { type: "rollback_deploy", target_service: "orders", executable: true },
    approval_state: "pending",
    started_at: at(0),
    diagnosis: DIAGNOSIS,
    approval_request: REQUEST,
    approval: null,
    action_result: null,
    usage: {
      turns: 2,
      model_calls: 2,
      tool_calls: 2,
      input_tokens: 900,
      output_tokens: 120,
      // Matches the default fixture model, PLAYBOOK: a real, priced zero (see evals/pricing.yaml).
      cost_usd: 0.0,
    },
    time_to_diagnosis_s: 1,
    error: null,
    trace: pendingTrace(),
    trace_id: TRACE_ID,
    ...overrides,
  };
}

export function rejected(): InvestigationDetail {
  return investigation({
    status: "rejected",
    approval_state: "rejected",
    approval: {
      approved: false,
      reviewer: "bob",
      comment: "Deploy looks unrelated",
      decided_at: at(30),
    },
    finished_at: at(30),
    trace: [
      ...pendingTrace(),
      {
        seq: 8,
        at: at(30),
        kind: "decision",
        data: { decision: "reject", reviewer: "bob", comment: "Deploy looks unrelated" },
      },
      { seq: 9, at: at(30), kind: "finished", data: { outcome: "rejected" } },
    ],
  });
}

export function executed(): InvestigationDetail {
  const result = {
    tool: "rollback_deploy",
    args: { service: "orders", reason: "Revert the deploy that introduced the failures." },
    ok: true,
    output: { status: "rolled_back" },
    summary: "orders rolled back from 1.8.4 to 1.8.3.",
  };
  return investigation({
    status: "executed",
    approval_state: "approved",
    approval: { approved: true, reviewer: "alice", comment: null, decided_at: at(20) },
    action_result: result,
    finished_at: at(22),
    trace: [
      ...pendingTrace(),
      {
        seq: 8,
        at: at(20),
        kind: "decision",
        data: { decision: "approve", reviewer: "alice", comment: null },
      },
      { seq: 9, at: at(22), kind: "action", data: result },
      { seq: 10, at: at(22), kind: "finished", data: { outcome: "executed" } },
    ],
  });
}

export function summary(overrides: Partial<InvestigationSummary> = {}): InvestigationSummary {
  const detail = investigation();
  return {
    id: detail.id,
    status: detail.status,
    alert: detail.alert,
    model: detail.model,
    created_at: detail.created_at,
    updated_at: detail.updated_at,
    finished_at: detail.finished_at,
    root_cause_service: detail.root_cause_service,
    category: detail.category,
    confidence: detail.confidence,
    proposed_action: detail.proposed_action,
    approval_state: detail.approval_state,
    ...overrides,
  };
}

export function config(overrides: Partial<ServiceConfig> = {}): ServiceConfig {
  return {
    backend: "live",
    model: PLAYBOOK,
    models: [PLAYBOOK],
    model_error: null,
    demo_enabled: true,
    services: ["storefront", "orders", "payments"],
    ...overrides,
  };
}

export function benchmarkRun(overrides: Partial<BenchmarkRun> = {}): BenchmarkRun {
  return {
    id: "20260929T012025Z-035f2b-simulated-fake-playbook",
    run: {
      run_id: "20260929T012025Z-035f2b",
      started_at: "2026-09-29T01:20:25+00:00",
      finished_at: "2026-09-29T01:20:28+00:00",
      environment: "simulated",
      model: "fake:playbook",
      approval: "approve",
      repeats: 1,
      max_turns: 12,
      commit: "239ef10",
    },
    model: PLAYBOOK,
    environment_note:
      "Simulated telemetry. Checks the harness and the baseline; these numbers are not benchmark results.",
    reportable: false,
    summary: { scenarios: 11, root_cause_accuracy: 1, action_accuracy: 1 },
    ...overrides,
  };
}
