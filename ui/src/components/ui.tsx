import { AlertTriangle, Info } from "lucide-react";
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
  className,
  children,
  ...rest
}: {
  title?: ReactNode;
  intro?: ReactNode;
  action?: ReactNode;
  headingLevel?: 2 | 3;
  className?: string;
  children: ReactNode;
} & Omit<HTMLAttributes<HTMLElement>, "title">) {
  const Heading = headingLevel === 2 ? "h2" : "h3";
  return (
    <section className={[styles.panel, className ?? ""].join(" ").trim()} {...rest}>
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

export function Notice({
  tone = "info",
  children,
  role,
}: {
  tone?: "info" | "danger" | "attention";
  children: ReactNode;
  role?: "alert" | "status";
}) {
  const Icon = tone === "info" ? Info : AlertTriangle;
  return (
    <div className={`${styles.notice} ${styles[tone]}`} role={role}>
      <Icon size={16} aria-hidden="true" />
      <div className={styles.noticeBody}>{children}</div>
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className={styles.empty}>
      <h3>{title}</h3>
      {children}
    </div>
  );
}

export function Skeleton({ width = "100%" }: { width?: string }) {
  return <span className={styles.skeleton} style={{ width }} aria-hidden="true" />;
}

export const uiStyles = styles;
