"use client";

import { CheckCircle2, CircleAlert } from "lucide-react";
import { useId, useState, type FormEvent } from "react";
import useSWR from "swr";

import { ApiError, api } from "@/lib/api";
import { categoryLabel, clockTime, faultLabel } from "@/lib/format";
import { useConfig } from "@/lib/hooks";
import type { FaultRecord, FaultType, ParamSchema } from "@/lib/types";

import { Button, Notice, Panel, Skeleton, uiStyles } from "./ui";
import styles from "./DemoFaultPanel.module.css";

const PARAM_LABELS: Record<string, string> = {
  delay_ms: "Delay (ms)",
  jitter_ms: "Jitter (ms)",
  error_rate: "Share of failing requests (0 to 1)",
};

const RESOLVED_BY: Record<string, string> = {
  rollback: "Resolved by a rollback",
  cleared: "Cleared",
  reset: "Cleared by a reset",
};

const INTRO =
  "Stages an incident through the control plane’s chaos API. The agent never sees this API " +
  "or the injected fault; it only sees the symptoms.";

export function DemoFaultPanel() {
  const { data: config, error } = useConfig();
  if (error) {
    return (
      <Panel title="Inject a demo fault" intro={INTRO} variant="harness">
        <Notice>
          <p>
            The demo controls come from the agent API, which is not answering. Start it with make
            api-dev, then reload this page.
          </p>
        </Notice>
      </Panel>
    );
  }
  if (!config) {
    return (
      <Panel title="Inject a demo fault" intro={INTRO} variant="harness">
        <Skeleton width="80%" />
      </Panel>
    );
  }
  if (!config.demo_enabled) {
    return (
      <Panel title="Inject a demo fault" intro={INTRO} variant="harness">
        <Notice>
          <p>
            Fault injection is off. Set <code>OPSPILOT_CHAOS_URL</code> on the agent API to the
            control plane (for example <code>http://localhost:8190</code>) and restart it.
          </p>
        </Notice>
      </Panel>
    );
  }
  return <DemoControls />;
}

function paramStep(schema: ParamSchema): string {
  return schema.type === "integer" ? "1" : "0.05";
}

function defaults(fault: FaultType | undefined): Record<string, string> {
  if (!fault) return {};
  return Object.fromEntries(
    Object.entries(fault.params).map(([name, schema]) => [name, String(schema.default ?? "")]),
  );
}

function DemoControls() {
  const ids = useId();
  const catalog = useSWR("demo-catalog", api.catalog, { revalidateOnFocus: false });
  const faults = useSWR("demo-faults", api.faults, { refreshInterval: 3000 });
  const types = catalog.data?.fault_types ?? [];

  const [typeName, setTypeName] = useState("");
  const [target, setTarget] = useState("");
  const [params, setParams] = useState<Record<string, string> | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "info" | "danger"; text: string } | null>(null);

  const selected = types.find((t) => t.type === typeName) ?? types[0];
  const effectiveTarget =
    selected && selected.targets.includes(target) ? target : (selected?.targets[0] ?? "");
  const values = params ?? defaults(selected);

  async function run(action: () => Promise<string>) {
    setBusy(true);
    setMessage(null);
    try {
      setMessage({ tone: "info", text: await action() });
      await faults.mutate();
    } catch (exc) {
      setMessage({
        tone: "danger",
        text: exc instanceof ApiError ? exc.message : String(exc),
      });
    } finally {
      setBusy(false);
    }
  }

  function onInject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected) return;
    const numeric: Record<string, number> = {};
    for (const [name, raw] of Object.entries(values)) {
      if (raw.trim() !== "") numeric[name] = Number(raw);
    }
    void run(async () => {
      const record = await api.inject({
        type: selected.type,
        target: effectiveTarget,
        params: numeric,
      });
      return (
        `Injected ${faultLabel(record.type).toLowerCase()} into ${record.target} (${record.id}). ` +
        "Symptoms reach metrics and logs in about a minute; then start an investigation."
      );
    });
  }

  if (catalog.error) {
    return (
      <Panel title="Inject a demo fault" intro={INTRO} variant="harness">
        <Notice tone="danger" role="alert">
          <p>Could not load the fault catalog: {catalog.error.message}</p>
          <p>Check that the control plane is running (make up) and reload this page.</p>
        </Notice>
      </Panel>
    );
  }

  const records = [...(faults.data?.faults ?? [])].reverse();
  return (
    <Panel title="Inject a demo fault" intro={INTRO} variant="harness">
      {!selected ? (
        <Skeleton width="80%" />
      ) : (
        <form className={styles.form} onSubmit={onInject}>
          <div className={uiStyles.field}>
            <label htmlFor={`${ids}-type`} className={uiStyles.label}>
              Fault
            </label>
            <select
              id={`${ids}-type`}
              name="type"
              className={uiStyles.input}
              value={selected.type}
              onChange={(event) => {
                setTypeName(event.target.value);
                setParams(null);
              }}
              aria-describedby={`${ids}-type-hint`}
            >
              {types.map((t) => (
                <option key={t.type} value={t.type}>
                  {faultLabel(t.type)}
                </option>
              ))}
            </select>
            <span id={`${ids}-type-hint`} className={uiStyles.hint}>
              {selected.description}
            </span>
          </div>
          <div className={uiStyles.field}>
            <label htmlFor={`${ids}-target`} className={uiStyles.label}>
              Target service
            </label>
            <select
              id={`${ids}-target`}
              name="target"
              className={uiStyles.input}
              value={effectiveTarget}
              onChange={(event) => setTarget(event.target.value)}
            >
              {selected.targets.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </div>
          {Object.entries(selected.params).map(([name, schema]) => (
            <div className={uiStyles.field} key={name}>
              <label htmlFor={`${ids}-${name}`} className={uiStyles.label}>
                {PARAM_LABELS[name] ?? schema.title ?? name}
              </label>
              <input
                id={`${ids}-${name}`}
                name={name}
                autoComplete="off"
                className={uiStyles.input}
                type="number"
                step={paramStep(schema)}
                min={schema.minimum ?? schema.exclusiveMinimum}
                max={schema.maximum}
                value={values[name] ?? ""}
                onChange={(event) => setParams({ ...values, [name]: event.target.value })}
              />
            </div>
          ))}
          <div className={styles.actions}>
            <Button type="submit" variant="secondary" disabled={busy}>
              Inject fault
            </Button>
            <Button
              variant="quiet"
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  const result = await api.resetDemo();
                  const n = result.resolved_faults;
                  return `Demo system reset: ${n} active ${n === 1 ? "fault" : "faults"} cleared.`;
                })
              }
            >
              Reset demo system
            </Button>
          </div>
        </form>
      )}

      <div aria-live="polite" className={styles.message}>
        {message ? (
          <Notice tone={message.tone}>
            <p>{message.text}</p>
          </Notice>
        ) : null}
      </div>

      <h3 className={styles.listTitle}>Injected faults</h3>
      {records.length === 0 ? (
        <p className={styles.none}>None since the last reset of the control plane.</p>
      ) : (
        <ul className={styles.faults}>
          {records.slice(0, 6).map((record) => (
            <FaultRow
              key={record.id}
              record={record}
              busy={busy}
              onClear={() =>
                void run(async () => {
                  const cleared = await api.clearFault(record.id);
                  return `Cleared ${cleared.id}.`;
                })
              }
            />
          ))}
        </ul>
      )}
    </Panel>
  );
}

function FaultRow({
  record,
  busy,
  onClear,
}: {
  record: FaultRecord;
  busy: boolean;
  onClear: () => void;
}) {
  return (
    <li className={`${styles.fault} ${record.active ? styles.active : ""}`}>
      <div>
        <p className={styles.faultTitle}>
          {faultLabel(record.type)} in {record.target}
        </p>
        <p className={styles.faultMeta}>
          <span className="numeric">{record.id}</span>
          <span>Injected {clockTime(record.injected_at)}</span>
          <span>
            Ground truth: {record.ground_truth.service},{" "}
            {categoryLabel(record.ground_truth.category)}
          </span>
        </p>
      </div>
      {record.active ? (
        <div className={styles.faultState}>
          <span className={styles.activeLabel}>
            <CircleAlert size={14} aria-hidden="true" />
            Active
          </span>
          <Button
            variant="quiet"
            onClick={onClear}
            disabled={busy}
            aria-label={`Clear ${record.id}`}
          >
            Clear
          </Button>
        </div>
      ) : (
        <p className={styles.resolved}>
          <CheckCircle2 size={14} aria-hidden="true" className={styles.resolvedIcon} />
          {RESOLVED_BY[record.resolved_by ?? ""] ?? "Resolved"}
          {record.resolved_at ? ` at ${clockTime(record.resolved_at)}` : ""}
        </p>
      )}
    </li>
  );
}
