import {
  Ban,
  CheckCircle2,
  CircleAlert,
  CircleHelp,
  Clock,
  Lightbulb,
  LoaderCircle,
  OctagonX,
  PlayCircle,
  type LucideIcon,
} from "lucide-react";

import { STATUS } from "@/lib/format";
import type { Status } from "@/lib/types";

import { GateMark } from "./GateMark";
import styles from "./StatusBadge.module.css";

const ICONS: Record<Exclude<Status, "awaiting_approval">, LucideIcon> = {
  queued: Clock,
  running: LoaderCircle,
  executing: PlayCircle,
  executed: CheckCircle2,
  action_failed: OctagonX,
  rejected: Ban,
  advisory: Lightbulb,
  no_diagnosis: CircleHelp,
  failed: CircleAlert,
};

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
  let icon;
  if (status === "awaiting_approval") {
    icon = <GateMark className={styles.gate} />;
  } else {
    const Icon = ICONS[status];
    icon = (
      <Icon
        size={size === "large" ? 16 : 14}
        aria-hidden="true"
        className={SPINNING.has(status) ? styles.spin : undefined}
      />
    );
  }
  return (
    <span className={className} title={hint} data-status={status}>
      {icon}
      {label}
    </span>
  );
}
