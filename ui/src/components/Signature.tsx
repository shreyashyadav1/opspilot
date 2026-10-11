import { Fragment } from "react";

import { formatArg } from "@/lib/format";

import styles from "./Signature.module.css";

/** A tool call as code, `tool(key=value, ...)`, that wraps between arguments. */
export function Signature({ tool, args }: { tool: string; args: Record<string, unknown> }) {
  const entries = Object.entries(args);
  return (
    <code className={styles.signature} translate="no">
      {tool}(
      {entries.map(([key, value], index) => (
        <Fragment key={key}>
          <span className={styles.arg}>
            {key}={formatArg(value)}
            {index < entries.length - 1 ? "," : ""}
          </span>
          {index < entries.length - 1 ? " " : ""}
        </Fragment>
      ))}
      )
    </code>
  );
}
