import { STATUS, type Tone } from "@/lib/format";
import type { Status } from "@/lib/types";

import { GateMark } from "./GateMark";
import styles from "./StatusBadge.module.css";

/**
 * Shape-coded state glyphs, the way annunciators pair a shape with a color: a ring for work in
 * progress, the gate for a held proposal, a filled disc for healthy, a triangle for degraded, a
 * square for failing and a struck circle for settled-and-not-done. The shape alone tells the
 * states apart, without the color.
 */
function Glyph({ tone, spinning }: { tone: Tone; spinning: boolean }) {
  const common = {
    viewBox: "0 0 16 16",
    width: 14,
    height: 14,
    "aria-hidden": true,
    focusable: false,
    className: spinning ? styles.spin : undefined,
  } as const;
  switch (tone) {
    case "active":
      return spinning ? (
        <svg {...common}>
          <path
            d="M8 2.5a5.5 5.5 0 1 1-5.5 5.5"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
          />
        </svg>
      ) : (
        <svg {...common}>
          <circle cx="8" cy="8" r="5.25" fill="none" stroke="currentColor" strokeWidth="1.75" />
        </svg>
      );
    case "healthy":
      return (
        <svg {...common}>
          <circle cx="8" cy="8" r="5.5" fill="currentColor" />
        </svg>
      );
    case "degraded":
      return (
        <svg {...common}>
          <path
            d="M8 2.25 14 13H2Z"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.75"
            strokeLinejoin="round"
          />
        </svg>
      );
    case "failing":
      return (
        <svg {...common}>
          <rect x="2.75" y="2.75" width="10.5" height="10.5" rx="1" fill="currentColor" />
        </svg>
      );
    default:
      return (
        <svg {...common}>
          <circle cx="8" cy="8" r="5.25" fill="none" stroke="currentColor" strokeWidth="1.75" />
          <path d="M4.5 11.5 11.5 4.5" stroke="currentColor" strokeWidth="1.75" />
        </svg>
      );
  }
}

const SPINNING = new Set<Status>(["running", "executing"]);

export function StatusBadge({
  status,
  size = "regular",
}: {
  status: Status;
  size?: "regular" | "large";
}) {
  const { label, tone, hint } = STATUS[status];
  const className = [styles.badge, styles[tone], size === "large" ? styles.large : ""].join(" ");
  return (
    <span className={className} title={hint} data-status={status}>
      {status === "awaiting_approval" ? (
        <GateMark className={styles.gate} />
      ) : (
        <Glyph tone={tone} spinning={SPINNING.has(status)} />
      )}
      {label}
    </span>
  );
}
