"use client";

import { useRouter } from "next/navigation";
import { useId, useState, type FormEvent } from "react";
import { useSWRConfig } from "swr";

import { ApiError, api } from "@/lib/api";
import { useConfig } from "@/lib/hooks";

import { Button, Notice, Panel, uiStyles } from "./ui";
import styles from "./StartInvestigationForm.module.css";

export const PRESETS = [
  {
    title: "Checkout error rate above SLO",
    details: "POST /checkout 5xx rate is above the 2% SLO.",
  },
  {
    title: "Checkout p95 latency above SLO",
    details: "POST /checkout p95 latency is above the 800 ms SLO.",
  },
] as const;

const SERVICES = ["storefront", "orders", "payments"];

export function StartInvestigationForm() {
  const router = useRouter();
  const { mutate } = useSWRConfig();
  const { data: config } = useConfig();
  const ids = useId();
  const [alert, setAlert] = useState<string>(PRESETS[0].title);
  const [details, setDetails] = useState<string>(PRESETS[0].details);
  const [service, setService] = useState("storefront");
  const [firing, setFiring] = useState("");
  const [model, setModel] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const models = config?.models ?? [];
  const chosen = model || config?.model.spec || "";
  const blocked = Boolean(config?.model_error) && chosen === config?.model.spec;

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const title = alert.trim();
    if (title.length < 3) {
      setError("Describe the alert in at least 3 characters.");
      return;
    }
    const minutes = firing.trim() ? Number(firing) : null;
    if (minutes !== null && (!Number.isInteger(minutes) || minutes < 1 || minutes > 240)) {
      setError("Firing time must be a whole number of minutes between 1 and 240.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const created = await api.start({
        alert: title,
        service: service || null,
        details: details.trim() || null,
        firing_minutes: minutes,
        model: model || null,
      });
      await mutate("investigations");
      router.push(`/investigations/${created.id}`);
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "The investigation could not be started.");
      setSubmitting(false);
    }
  }

  return (
    <Panel
      title="Start an investigation"
      intro="Describe the alert as it fired. The agent investigates with read-only tools."
    >
      <form
        className={styles.form}
        onSubmit={onSubmit}
        noValidate
        aria-describedby={error ? `${ids}-error` : undefined}
      >
        <div className={uiStyles.field}>
          <label htmlFor={`${ids}-alert`} className={uiStyles.label}>
            Alert
          </label>
          <input
            id={`${ids}-alert`}
            className={uiStyles.input}
            value={alert}
            onChange={(event) => setAlert(event.target.value)}
            maxLength={200}
            required
            aria-invalid={error?.startsWith("Describe") ? true : undefined}
          />
          <div className={styles.presets} role="group" aria-label="Common alerts">
            {PRESETS.map((preset) => (
              <button
                key={preset.title}
                type="button"
                className={styles.preset}
                aria-pressed={alert === preset.title}
                onClick={() => {
                  setAlert(preset.title);
                  setDetails(preset.details);
                }}
              >
                {preset.title}
              </button>
            ))}
          </div>
        </div>

        <div className={styles.pair}>
          <div className={uiStyles.field}>
            <label htmlFor={`${ids}-service`} className={uiStyles.label}>
              Fired on
            </label>
            <select
              id={`${ids}-service`}
              className={uiStyles.input}
              value={service}
              onChange={(event) => setService(event.target.value)}
            >
              {(config?.services ?? SERVICES).map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
              <option value="">Not specified</option>
            </select>
          </div>
          <div className={uiStyles.field}>
            <label htmlFor={`${ids}-firing`} className={uiStyles.label}>
              Firing for (min)
            </label>
            <input
              id={`${ids}-firing`}
              className={uiStyles.input}
              inputMode="numeric"
              placeholder="Optional"
              value={firing}
              onChange={(event) => setFiring(event.target.value)}
              aria-describedby={`${ids}-firing-hint`}
            />
            <span id={`${ids}-firing-hint`} className={uiStyles.hint}>
              Narrows the log search window.
            </span>
          </div>
        </div>

        <div className={uiStyles.field}>
          <label htmlFor={`${ids}-details`} className={uiStyles.label}>
            Details <span className={styles.optional}>(optional)</span>
          </label>
          <textarea
            id={`${ids}-details`}
            className={uiStyles.input}
            value={details}
            onChange={(event) => setDetails(event.target.value)}
            maxLength={1000}
            rows={2}
          />
        </div>

        {models.length > 1 ? (
          <div className={uiStyles.field}>
            <label htmlFor={`${ids}-model`} className={uiStyles.label}>
              Model
            </label>
            <select
              id={`${ids}-model`}
              className={uiStyles.input}
              value={chosen}
              onChange={(event) => setModel(event.target.value)}
            >
              {models.map((option) => (
                <option key={option.spec} value={option.spec}>
                  {option.label} ({option.kind === "baseline" ? "rule-based baseline" : "LLM"})
                </option>
              ))}
            </select>
          </div>
        ) : null}

        {blocked ? (
          <Notice tone="attention">
            <p>The configured model cannot run: {config?.model_error}</p>
            {models.length > 1 ? <p>Pick the rule-based playbook above to try the flow.</p> : null}
          </Notice>
        ) : null}

        {error ? (
          <div id={`${ids}-error`}>
            <Notice tone="danger" role="alert">
              <p>{error}</p>
            </Notice>
          </div>
        ) : null}

        <Button type="submit" variant="primary" size="large" disabled={submitting || blocked}>
          {submitting ? "Starting..." : "Start investigation"}
        </Button>
      </form>
    </Panel>
  );
}
