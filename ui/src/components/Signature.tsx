import { Fragment } from "react";

import { formatArg } from "@/lib/format";

import styles from "./Signature.module.css";

/**
 * A tool call as code, `tool(key=value, ...)`, that wraps between arguments. Each argument keeps
 * its separator, and the last keeps the closing parenthesis, so a line never starts with "," or ")".
 */
export function Signature({ tool, args }: { tool: string; args: Record<string, unknown> }) {
  const entries = Object.entries(args);
  if (entries.length === 0) {
    return (
      <code className={styles.signature} translate="no">
        {tool}()
      </code>
    );
  }
  return (
    <code className={styles.signature} translate="no">
      {tool}(
      {entries.map(([key, value], index) => {
        const last = index === entries.length - 1;
        return (
          <Fragment key={key}>
            <span className={styles.arg}>
              {key}={formatArg(value)}
              {last ? ")" : ","}
            </span>
            {last ? "" : " "}
          </Fragment>
        );
      })}
    </code>
  );
}
