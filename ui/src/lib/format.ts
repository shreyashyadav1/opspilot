import type { Status } from "./types";

export type Tone = "active" | "attention" | "success" | "info" | "neutral" | "danger";

export const STATUS: Record<Status, { label: string; tone: Tone; hint: string }> = {
  queued: { label: "Queued", tone: "active", hint: "Waiting for a free investigation slot." },
  running: { label: "Investigating", tone: "active", hint: "The agent is calling tools." },
  awaiting_approval: {
    label: "Needs approval",
    tone: "attention",
    hint: "The proposed action runs only after someone approves it.",
  },
  executing: { label: "Executing", tone: "active", hint: "The approved action is running." },
  executed: { label: "Executed", tone: "success", hint: "The approved action ran." },
  action_failed: {
    label: "Execution failed",
    tone: "danger",
    hint: "The approved action was attempted and failed.",
  },
  rejected: { label: "Rejected", tone: "neutral", hint: "The proposed action was not executed." },
  advisory: {
    label: "Diagnosed",
    tone: "info",
    hint: "Diagnosis with a recommendation for the operator.",
  },
  no_diagnosis: {
    label: "No diagnosis",
    tone: "danger",
    hint: "The agent ran out of turns without a valid diagnosis.",
  },
  failed: { label: "Error", tone: "danger", hint: "The investigation stopped with an error." },
};

const CATEGORY: Record<string, string> = {
  latency: "Latency",
  error_rate: "Error rate",
  resource_exhaustion: "Resource exhaustion",
  bad_deploy: "Bad deploy",
  dependency_outage: "Dependency outage",
};

const ACTION: Record<string, string> = {
  rollback_deploy: "Roll back the latest deploy",
  restart_service: "Restart the service",
  escalate: "Escalate to the owning team",
  none: "No action",
};

const FAULT: Record<string, string> = {
  latency_spike: "Latency spike",
  error_spike: "Error spike",
  db_pool_exhaustion: "Database pool exhaustion",
  bad_config_deploy: "Bad config deploy",
  dependency_outage: "Dependency outage",
};

export const categoryLabel = (value: string | null | undefined): string =>
  value ? (CATEGORY[value] ?? value.replaceAll("_", " ")) : "Unknown";

export const actionLabel = (value: string | null | undefined): string =>
  value ? (ACTION[value] ?? value.replaceAll("_", " ")) : "None";

export const faultLabel = (value: string): string => FAULT[value] ?? value.replaceAll("_", " ");

export function percent(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "n/a";
  return `${(value * 100).toFixed(digits)}%`;
}

export function number(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "n/a";
  return value.toFixed(digits);
}

/** A cost in USD, with enough precision to show sub-cent amounts; "n/a" when unpriced. */
export function money(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "n/a";
  return `$${value.toFixed(value > 0 && value < 0.01 ? 4 : 2)}`;
}

export function clockTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

export function dateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

/** "just now", "4 min ago", "3 h ago", or a date for anything older than a day. */
export function relativeTime(iso: string, now: number = Date.now()): string {
  const seconds = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (seconds < 45) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return dateTime(iso);
}

/** Seconds between two timestamps, formatted as an offset: "+0.4 s", "+12 s". */
export function offset(fromIso: string, toIso: string): string {
  const seconds = (new Date(toIso).getTime() - new Date(fromIso).getTime()) / 1000;
  if (seconds < 10) return `+${seconds.toFixed(1)} s`;
  if (seconds < 120) return `+${Math.round(seconds)} s`;
  return `+${Math.round(seconds / 60)} min`;
}

export function formatArg(value: unknown): string {
  if (typeof value === "string") return JSON.stringify(value);
  if (value === null || value === undefined) return "null";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** A tool call as a function signature: query_metric(service="orders", metric="up"). */
export function signature(tool: string, args: Record<string, unknown>): string {
  const parts = Object.entries(args).map(([key, value]) => `${key}=${formatArg(value)}`);
  return `${tool}(${parts.join(", ")})`;
}
