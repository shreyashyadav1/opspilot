// Shapes of the agent API responses (api/opspilot_api/schemas.py and friends).

export type Status =
  | "queued"
  | "running"
  | "awaiting_approval"
  | "executing"
  | "executed"
  | "action_failed"
  | "rejected"
  | "advisory"
  | "no_diagnosis"
  | "failed";

export const TERMINAL_STATUSES: ReadonlySet<Status> = new Set([
  "executed",
  "action_failed",
  "rejected",
  "advisory",
  "no_diagnosis",
  "failed",
]);

export type ApprovalState = "not_required" | "pending" | "approved" | "rejected";

export interface ModelInfo {
  spec: string;
  kind: "baseline" | "llm";
  label: string;
  description: string;
}

export interface Alert {
  title: string;
  service: string | null;
  details: string | null;
  firing_minutes: number | null;
}

export interface ProposedActionBrief {
  type: string;
  target_service: string;
  executable: boolean;
}

export interface InvestigationSummary {
  id: string;
  status: Status;
  alert: Alert;
  model: ModelInfo;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
  root_cause_service: string | null;
  category: string | null;
  confidence: number | null;
  proposed_action: ProposedActionBrief | null;
  approval_state: ApprovalState | null;
}

export interface Evidence {
  source: "logs" | "metrics" | "deploys" | "health";
  service: string;
  detail: string;
}

export interface ProposedAction {
  type: string;
  target_service: string;
  rationale: string;
}

export interface Diagnosis {
  root_cause_service: string;
  category: string;
  summary: string;
  evidence: Evidence[];
  confidence: number;
  proposed_action: ProposedAction;
}

export interface ApprovalRequest {
  type: "approval_request";
  tool: string;
  action: ProposedAction;
  root_cause_service: string;
  category: string;
  confidence: number;
  summary: string;
  evidence: Evidence[];
}

export interface Approval {
  approved: boolean;
  reviewer: string;
  comment: string | null;
  decided_at: string;
  /** False when the API ran without keys, so the reviewer name was not verified. */
  authenticated?: boolean;
}

export interface ActionResult {
  tool: string;
  args: Record<string, unknown>;
  ok: boolean;
  output: unknown;
  summary?: string;
}

export interface Usage {
  turns: number;
  model_calls: number;
  tool_calls: number;
  input_tokens: number;
  output_tokens: number;
  // null when the model in use has no entry in the price table; 0 is a real, priced zero (the
  // fake:playbook baseline makes no model calls).
  cost_usd: number | null;
}

export interface ToolCallData {
  turn: number;
  tool: string;
  args: Record<string, unknown>;
  call_id?: string;
  started_at?: string;
  ok: boolean;
  error: string | null;
  latency_ms: number;
  policy_violation?: boolean;
  summary: string;
  output: unknown;
}

export interface ModelTurnData {
  turn: number;
  text: string;
  requested: string[];
  input_tokens?: number;
  output_tokens?: number;
}

type EventOf<K extends string, D> = { seq: number; at: string; kind: K; data: D };

export type TraceEvent =
  | EventOf<"alert", Alert>
  | EventOf<"model_turn", ModelTurnData>
  | EventOf<"tool_call", ToolCallData>
  | EventOf<"nudge", { message: string }>
  | EventOf<"diagnosis", { diagnosis: Diagnosis }>
  | EventOf<"diagnosis_invalid", { feedback: string }>
  | EventOf<"approval_requested", ApprovalRequest>
  | EventOf<
      "decision",
      { decision: "approve" | "reject"; reviewer: string; comment: string | null }
    >
  | EventOf<"action", ActionResult>
  | EventOf<"finished", { outcome: string }>
  | EventOf<"note", { message: string }>
  | EventOf<"error", { message: string }>;

export interface InvestigationDetail extends InvestigationSummary {
  started_at: string | null;
  diagnosis: Diagnosis | null;
  approval_request: ApprovalRequest | null;
  approval: Approval | null;
  action_result: ActionResult | null;
  usage: Usage;
  time_to_diagnosis_s: number | null;
  error: string | null;
  trace: TraceEvent[];
  // OpenTelemetry trace id of this investigation (paste it into the trace backend's lookup).
  // null until the run has started, and when it was started by an API without tracing support.
  trace_id: string | null;
}

export interface ServiceConfig {
  backend: string;
  model: ModelInfo;
  models: ModelInfo[];
  model_error: string | null;
  demo_enabled: boolean;
  services: string[];
  auth_required?: boolean;
}

export type Role = "viewer" | "operator" | "approver";

/** GET /me: who the saved API key belongs to. Without keys the API is open to everyone. */
export interface Me {
  name: string | null;
  role: Role;
  authenticated: boolean;
}

export interface ParamSchema {
  type?: "integer" | "number";
  title?: string;
  default?: number;
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
}

export interface FaultType {
  type: string;
  category: string;
  description: string;
  targets: string[];
  params: Record<string, ParamSchema>;
}

export interface FaultRecord {
  id: string;
  type: string;
  target: string;
  params: Record<string, number>;
  ground_truth: { service: string; category: string };
  injected_at: string;
  deploy_id: string | null;
  resolved_at: string | null;
  resolved_by: string | null;
  active: boolean;
}

export interface RunMeta {
  run_id: string;
  started_at: string;
  finished_at: string | null;
  environment: string;
  model: string;
  approval: string;
  repeats: number;
  max_turns: number | null;
  commit: string | null;
}

export type BenchmarkSummary = Partial<{
  scenarios: number;
  errors: number;
  root_cause_accuracy: number | null;
  service_accuracy: number | null;
  category_accuracy: number | null;
  action_accuracy: number | null;
  tool_call_precision: number | null;
  evidence_recall: number | null;
  mean_steps: number | null;
  mean_tool_calls: number | null;
  mean_time_to_diagnosis_s: number | null;
  median_time_to_diagnosis_s: number | null;
  max_time_to_diagnosis_s: number | null;
  mean_input_tokens: number | null;
  mean_output_tokens: number | null;
  mean_cost_usd: number | null;
  total_cost_usd: number | null;
  policy_violations: number;
  unapproved_writes: number;
  actions_executed: number;
  remediations_verified: number;
}>;

export interface BenchmarkRun {
  id: string;
  run: RunMeta;
  model: ModelInfo;
  environment_note: string;
  reportable: boolean;
  summary: BenchmarkSummary;
}

export interface ScenarioScore {
  root_cause_correct: boolean;
  service_correct?: boolean;
  category_correct?: boolean;
  action_correct: boolean;
  tool_calls?: number;
  tool_call_precision?: number;
  steps?: number;
  time_to_diagnosis_s?: number | null;
  input_tokens?: number;
  output_tokens?: number;
  cost_usd?: number | null;
  action_executed?: boolean;
  remediated?: boolean | null;
}

export interface BenchmarkResult {
  scenario: string;
  expected: string;
  repeat?: number;
  error?: string | null;
  score: ScenarioScore;
  investigation: {
    diagnosis?: Diagnosis | null;
    outcome?: string;
    tool_calls?: ToolCallData[];
  };
}

export interface BenchmarkRunDetail extends BenchmarkRun {
  results: BenchmarkResult[];
}
