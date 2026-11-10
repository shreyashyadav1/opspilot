"use client";

import { AlertTriangle } from "lucide-react";

import { ApiError } from "@/lib/api";
import { useConfig } from "@/lib/hooks";

import { ModelBadge } from "./ModelBadge";
import styles from "./AppHeader.module.css";

export function ModelIndicator() {
  const { data, error } = useConfig();
  // 401: the API wants a key, which the sign-in field beside this asks for.
  if (error instanceof ApiError && error.status === 401) {
    return <p className={styles.model} aria-hidden="true" />;
  }
  if (error) {
    return (
      <p className={styles.model} role="status">
        <AlertTriangle size={16} aria-hidden="true" className={styles.warn} />
        <span>Agent API unreachable. Start it with make api-dev.</span>
      </p>
    );
  }
  if (!data) return <p className={styles.model} aria-hidden="true" />;
  return (
    <div className={styles.model} title={data.model_error ?? data.model.description}>
      <span className={styles.modelLabel}>Default model</span>
      <span className={styles.modelName}>{data.model.label}</span>
      <ModelBadge model={data.model} />
      {data.model_error ? (
        <AlertTriangle size={16} className={styles.warn} aria-label={data.model_error} />
      ) : null}
    </div>
  );
}
