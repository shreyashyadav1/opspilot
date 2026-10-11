"use client";

import { ChevronLeft } from "lucide-react";
import Link from "next/link";
import { useEffect } from "react";
import { useSWRConfig } from "swr";

import { clockTime, dateTime } from "@/lib/format";
import { useInvestigation } from "@/lib/hooks";
import { gateState } from "@/lib/timeline";

import { CopyButton } from "./CopyButton";
import { DecisionPanel } from "./DecisionPanel";
import { DiagnosisPanel } from "./DiagnosisPanel";
import { ModelBadge } from "./ModelBadge";
import { StatusBadge } from "./StatusBadge";
import { Timeline } from "./Timeline";
import { Notice, Skeleton } from "./ui";
import styles from "./InvestigationView.module.css";

export function InvestigationView({ investigationId }: { investigationId: string }) {
  const { data, error, live, accept } = useInvestigation(investigationId);
  const { mutate } = useSWRConfig();
  const status = data?.status;

  // Keep the incident list in step when this page sees a status change.
  useEffect(() => {
    if (status) void mutate("investigations");
  }, [status, mutate]);

  useEffect(() => {
    if (data) document.title = `${data.alert.title} | OpsPilot`;
  }, [data]);

  if (!data) {
    return (
      <div className={styles.page}>
        <BackLink />
        {error ? (
          <Notice tone="danger" role="alert">
            {error.status === 404 ? (
              <p>
                There is no investigation {investigationId}. It may belong to another agent API;
                pick one from the incident list.
              </p>
            ) : (
              <>
                <p>
                  Could not load {investigationId}: {error.message}
                </p>
                <p>Check that the agent API is running (make api-dev), then reload this page.</p>
              </>
            )}
          </Notice>
        ) : (
          <div className={styles.loading} aria-busy="true" aria-label="Loading investigation">
            <Skeleton width="50%" />
            <Skeleton width="30%" />
          </div>
        )}
      </div>
    );
  }

  // When an action is held at (or went through) the approval gate, the decision takes the
  // right-hand column and the diagnosis heads the evidence trail; otherwise the diagnosis is the
  // verdict.
  const decided = Boolean(data.approval_request && gateState(data));

  return (
    <div className={styles.page}>
      <BackLink />
      <header className={styles.header}>
        <div className={styles.titleRow}>
          <h1>{data.alert.title}</h1>
          <StatusBadge status={data.status} size="large" />
        </div>
        <dl className={styles.facts}>
          <div>
            <dt>Fired on</dt>
            <dd>{data.alert.service ?? "Not specified"}</dd>
          </div>
          <div>
            <dt>Started</dt>
            <dd>
              <time
                dateTime={data.created_at}
                title={dateTime(data.created_at)}
                className="numeric"
              >
                {clockTime(data.created_at)}
              </time>
            </dd>
          </div>
          <div className={styles.wide}>
            <dt>Model</dt>
            <dd className={styles.model}>
              {data.model.label} <ModelBadge model={data.model} />
            </dd>
          </div>
          <div>
            <dt>ID</dt>
            <dd className={styles.code} translate="no">
              {data.id}
            </dd>
          </div>
          {data.trace_id ? (
            <div className={styles.wide}>
              <dt>Trace</dt>
              <dd className={styles.traceValue}>
                <code title="Look this up in the trace backend" translate="no">
                  {data.trace_id}
                </code>
                <CopyButton value={data.trace_id} label="Copy the trace id" />
              </dd>
            </div>
          ) : null}
        </dl>
        {live ? (
          <p className={styles.live}>
            <span className={styles.liveDot} aria-hidden="true" />
            Live updates
          </p>
        ) : null}
      </header>

      <div className={`${styles.columns} ${decided ? styles.withDecision : styles.withVerdict}`}>
        {decided ? (
          <>
            <div className={styles.side}>
              <DecisionPanel investigation={data} onDecided={accept} />
            </div>
            <div className={styles.diagnosis}>
              <DiagnosisPanel investigation={data} />
            </div>
          </>
        ) : (
          <div className={`${styles.side} ${styles.verdict}`}>
            <DiagnosisPanel investigation={data} />
          </div>
        )}
        <div className={styles.trail}>
          <Timeline investigation={data} />
        </div>
      </div>
    </div>
  );
}

function BackLink() {
  return (
    <Link href="/" className={styles.back}>
      <ChevronLeft size={16} aria-hidden="true" />
      All incidents
    </Link>
  );
}
