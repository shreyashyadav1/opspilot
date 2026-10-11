// What an approved rollback changes, in the operator's terms: service, versions and the config
// it puts back. Read from the agent's own evidence (its deploy-history and health tool calls) and,
// once the rollback ran, from what the tool reported back. Nothing here is guessed: when the
// evidence does not say, the fields stay null and the UI says so.

import type { InvestigationDetail, TraceEvent } from "./types";

type ToolCall = Extract<TraceEvent, { kind: "tool_call" }>;

export interface DeployRecord {
  id?: string;
  service: string;
  kind: string;
  version: string;
  previous_version?: string | null;
  deployed_at: string;
  author?: string;
  change_summary?: string;
  config_diff?: Record<string, { from?: unknown; to?: unknown }>;
}

/** One config key a rollback puts back: its value before and after the rollback. */
export interface ConfigChange {
  key: string;
  before: unknown;
  after: unknown;
}

export interface RollbackPlan {
  service: string;
  /** The version running when the agent looked (or, once executed, the one rolled back). */
  from: string | null;
  /** The version a rollback returns to (or, once executed, the one now running). */
  to: string | null;
  /** The deploy the rollback undoes, as the agent read it. */
  undoes: DeployRecord | null;
  config: ConfigChange[];
  /** The trace seq of the tool call the versions were read from, to link the evidence. */
  sourceSeq: number | null;
  /** True when the versions come from the executed rollback rather than from the evidence. */
  confirmed: boolean;
}

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

function asDeploy(value: unknown): DeployRecord | null {
  if (!isObject(value)) return null;
  const { service, version, deployed_at: deployedAt, kind } = value;
  if (typeof service !== "string" || typeof version !== "string") return null;
  if (typeof deployedAt !== "string") return null;
  return {
    id: typeof value.id === "string" ? value.id : undefined,
    service,
    kind: typeof kind === "string" ? kind : "deploy",
    version,
    previous_version: typeof value.previous_version === "string" ? value.previous_version : null,
    deployed_at: deployedAt,
    author: typeof value.author === "string" ? value.author : undefined,
    change_summary: typeof value.change_summary === "string" ? value.change_summary : undefined,
    config_diff: isObject(value.config_diff)
      ? (value.config_diff as DeployRecord["config_diff"])
      : undefined,
  };
}

function diffEntries(
  diff: DeployRecord["config_diff"],
  direction: "undo" | "as-recorded",
): ConfigChange[] {
  if (!diff) return [];
  return Object.entries(diff).map(([key, change]) =>
    direction === "undo"
      ? { key, before: change?.to, after: change?.from }
      : { key, before: change?.from, after: change?.to },
  );
}

const toolCalls = (trace: TraceEvent[], tool: string) =>
  trace.filter(
    (event): event is ToolCall => event.kind === "tool_call" && event.data.tool === tool,
  );

/** The latest successful deploy-history read that mentions the service. */
function deployHistory(trace: TraceEvent[], service: string) {
  for (const call of toolCalls(trace, "get_recent_deploys").reverse()) {
    if (!call.data.ok || !isObject(call.data.output)) continue;
    const deploys = call.data.output.deploys;
    if (!Array.isArray(deploys)) continue;
    const events = deploys
      .map(asDeploy)
      .filter((event): event is DeployRecord => event !== null && event.service === service)
      .sort((a, b) => Date.parse(b.deployed_at) - Date.parse(a.deployed_at));
    if (events.length > 0) return { call, events };
  }
  return null;
}

/** The running version of the service according to the latest health check that reported it. */
function healthVersion(trace: TraceEvent[], service: string) {
  for (const call of toolCalls(trace, "get_service_health").reverse()) {
    if (!call.data.ok || !isObject(call.data.output)) continue;
    const services = call.data.output.services;
    if (!Array.isArray(services)) continue;
    const entry = services.find((item) => isObject(item) && item.service === service);
    if (isObject(entry) && typeof entry.version === "string") {
      return { call, version: entry.version };
    }
  }
  return null;
}

/**
 * The rollback the approval gate is holding, or the one that ran. Mirrors the control plane: a
 * rollback returns the service to the version its running deploy replaced.
 */
export function rollbackPlan(investigation: InvestigationDetail): RollbackPlan | null {
  const request = investigation.approval_request;
  if (!request || request.tool !== "rollback_deploy") return null;
  const service = request.action.target_service;

  const plan: RollbackPlan = {
    service,
    from: null,
    to: null,
    undoes: null,
    config: [],
    sourceSeq: null,
    confirmed: false,
  };

  const history = deployHistory(investigation.trace, service);
  if (history) {
    const [current] = history.events;
    const running = history.events.find(
      (event) => event.kind === "deploy" && event.version === current?.version,
    );
    plan.from = current?.version ?? null;
    plan.to = running?.previous_version ?? null;
    plan.undoes = running ?? null;
    plan.config = diffEntries(running?.config_diff, "undo");
    plan.sourceSeq = history.call.seq;
  } else {
    const health = healthVersion(investigation.trace, service);
    if (health) {
      plan.from = health.version;
      plan.sourceSeq = health.call.seq;
    }
  }

  // Once the rollback ran, the tool's own record of it is the authority.
  const result = investigation.action_result;
  if (result?.ok && isObject(result.output)) {
    const event = asDeploy(result.output.event);
    if (event && event.kind === "rollback" && event.service === service) {
      plan.from = event.previous_version ?? plan.from;
      plan.to = event.version;
      plan.config = event.config_diff ? diffEntries(event.config_diff, "as-recorded") : plan.config;
      plan.confirmed = true;
    }
  }
  return plan;
}

/** A config value as it was recorded, for display. */
export function configValue(value: unknown): string {
  if (value === undefined) return "not set";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}
