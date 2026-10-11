"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { actionLabel, categoryLabel, percent, relativeTime } from "@/lib/format";
import { useInvestigations } from "@/lib/hooks";
import type { InvestigationSummary, ProposedActionBrief } from "@/lib/types";

import { StatusBadge } from "./StatusBadge";
import { EmptyState, Notice, Skeleton } from "./ui";
import styles from "./IncidentList.module.css";

/** Re-render relative times every 30 s without refetching. */
function useNow(intervalMs = 30_000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);
  return now;
}

/** What the agent wants to do, in a few words, for the rows waiting on a decision. */
function proposal(action: ProposedActionBrief): string {
  switch (action.type) {
    case "rollback_deploy":
      return `Proposes rolling back ${action.target_service}`;
    case "restart_service":
      return `Proposes restarting ${action.target_service}`;
    default:
      return `Proposes: ${actionLabel(action.type).toLowerCase()} (${action.target_service})`;
  }
}

function Row({ item, now }: { item: InvestigationSummary; now: number }) {
  const pending = item.status === "awaiting_approval";
  return (
    <li className={`${styles.row} ${pending ? styles.pending : ""}`}>
      <div className={styles.status}>
        <StatusBadge status={item.status} />
      </div>
      <div className={styles.alert}>
        <Link href={`/investigations/${item.id}`} className={styles.link}>
          {item.alert.title}
        </Link>
        <p className={styles.meta}>
          <span>
            {item.alert.service ? `Fired on ${item.alert.service}` : "Service not specified"}
          </span>
          <span className={styles.id}>{item.id}</span>
        </p>
      </div>
      <div className={styles.cause}>
        {item.root_cause_service ? (
          <>
            <span className={styles.service}>{item.root_cause_service}</span>
            <span className={styles.category}>{categoryLabel(item.category)}</span>
          </>
        ) : (
          <span className={styles.muted}>Not diagnosed yet</span>
        )}
      </div>
      <div className={styles.time}>
        <time dateTime={item.created_at} className="numeric">
          {relativeTime(item.created_at, now)}
        </time>
      </div>
      {pending && item.proposed_action ? (
        <p className={styles.proposal}>
          {proposal(item.proposed_action)}
          {item.confidence !== null ? `, ${percent(item.confidence)} confident.` : "."}
        </p>
      ) : null}
    </li>
  );
}

function Rows({
  items,
  now,
  label,
}: {
  items: InvestigationSummary[];
  now: number;
  label: string;
}) {
  return (
    <ul className={styles.list} aria-label={label}>
      {items.map((item) => (
        <Row key={item.id} item={item} now={now} />
      ))}
    </ul>
  );
}

export function IncidentList() {
  const { data, error, isLoading } = useInvestigations();
  const now = useNow();

  if (error && !data) {
    return (
      <Notice tone="danger" role="alert">
        <p>Could not load investigations: {error.message}</p>
        <p>The dashboard reads them from the agent API. Start it with make api-dev.</p>
      </Notice>
    );
  }
  if (isLoading || !data) {
    return (
      <div className={styles.loading} aria-busy="true" aria-label="Loading investigations">
        <Skeleton width="70%" />
        <Skeleton width="85%" />
        <Skeleton width="60%" />
      </div>
    );
  }

  const items = data.investigations;
  if (items.length === 0) {
    return (
      <EmptyState title="No investigations yet">
        <p>
          Start one from an alert with the form on this page. To see the whole loop, inject a demo
          fault first, wait about a minute for symptoms, then investigate the alert it causes.
        </p>
      </EmptyState>
    );
  }

  const pending = items.filter((item) => item.status === "awaiting_approval");
  const rest = items.filter((item) => item.status !== "awaiting_approval");
  return (
    <div className={styles.groups}>
      {pending.length > 0 ? (
        <section aria-labelledby="needs-decision">
          <h2 id="needs-decision" className={styles.groupTitle}>
            Waiting for your decision <span className={styles.count}>{pending.length}</span>
          </h2>
          <Rows items={pending} now={now} label="Waiting for your decision" />
        </section>
      ) : null}
      <section aria-labelledby="all-investigations">
        <h2 id="all-investigations" className={styles.groupTitle}>
          {pending.length > 0 ? "Everything else" : "All investigations"}
          <span className={styles.count}>{rest.length}</span>
        </h2>
        {rest.length > 0 ? (
          <>
            <div className={styles.head} aria-hidden="true">
              <span>Status</span>
              <span>Alert</span>
              <span>Root cause</span>
              <span className={styles.headTime}>Started</span>
            </div>
            <Rows items={rest} now={now} label="Investigations" />
          </>
        ) : (
          <p className={styles.muted}>Nothing else yet.</p>
        )}
      </section>
    </div>
  );
}
