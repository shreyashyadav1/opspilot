import { AlertTriangle, Info, OctagonAlert } from "lucide-react";
import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";

import styles from "./ui.module.css";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "quiet";
  size?: "regular" | "large";
};

export function Button({
  variant = "secondary",
  size = "regular",
  className,
  type = "button",
  ...props
}: ButtonProps) {
  const classes = [
    styles.button,
    styles[variant],
    size === "large" ? styles.large : "",
    className ?? "",
  ];
  return <button type={type} className={classes.join(" ").trim()} {...props} />;
}

export function Panel({
  title,
  intro,
  action,
  headingLevel = 2,
  variant = "default",
  className,
  children,
  ...rest
}: {
  title?: ReactNode;
  intro?: ReactNode;
  action?: ReactNode;
  headingLevel?: 2 | 3;
  /** "harness" marks tools that stage the demo rather than operate it. */
  variant?: "default" | "harness";
  className?: string;
  children: ReactNode;
} & Omit<HTMLAttributes<HTMLElement>, "title">) {
  const Heading = headingLevel === 2 ? "h2" : "h3";
  const classes = [styles.panel, variant === "harness" ? styles.harness : "", className ?? ""];
  return (
    <section className={classes.join(" ").trim()} {...rest}>
      {title ? (
        <div className={styles.panelHeader}>
          <div>
            <Heading>{title}</Heading>
            {intro ? <p className={styles.panelIntro}>{intro}</p> : null}
          </div>
          {action}
        </div>
      ) : null}
      {children}
    </section>
  );
}

const NOTICE_ICONS = { info: Info, danger: OctagonAlert, attention: AlertTriangle };

export function Notice({
  tone = "info",
  children,
  role,
}: {
  tone?: "info" | "danger" | "attention";
  children: ReactNode;
  role?: "alert" | "status";
}) {
  const Icon = NOTICE_ICONS[tone];
  return (
    <div className={`${styles.notice} ${styles[tone]}`} role={role}>
      <Icon size={18} aria-hidden="true" className={styles.noticeIcon} />
      <div className={styles.noticeBody}>{children}</div>
    </div>
  );
}

export function EmptyState({
  title,
  headingLevel = 2,
  children,
}: {
  title: string;
  headingLevel?: 1 | 2 | 3;
  children: ReactNode;
}) {
  const Heading = `h${headingLevel}` as const;
  return (
    <div className={styles.empty}>
      <Heading className={styles.emptyTitle}>{title}</Heading>
      {children}
    </div>
  );
}

export function Skeleton({ width = "100%" }: { width?: string }) {
  return <span className={styles.skeleton} style={{ width }} aria-hidden="true" />;
}

export const uiStyles = styles;
