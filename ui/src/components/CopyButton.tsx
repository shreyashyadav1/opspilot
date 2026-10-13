"use client";

import { Check, Copy } from "lucide-react";
import { useEffect, useState } from "react";

import styles from "./CopyButton.module.css";

/** Copies a value (a trace id, say) to paste into another tool. */
export function CopyButton({ value, label }: { value: string; label: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");

  useEffect(() => {
    if (state === "idle") return;
    const timer = setTimeout(() => setState("idle"), 2000);
    return () => clearTimeout(timer);
  }, [state]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setState("copied");
    } catch {
      setState("failed");
    }
  }

  return (
    <>
      <button
        type="button"
        className={styles.button}
        onClick={() => void copy()}
        aria-label={label}
      >
        {state === "copied" ? (
          <Check size={14} aria-hidden="true" />
        ) : (
          <Copy size={14} aria-hidden="true" />
        )}
        <span aria-hidden="true">{state === "copied" ? "Copied" : "Copy"}</span>
      </button>
      <span className="visually-hidden" aria-live="polite">
        {state === "copied" ? "Copied." : state === "failed" ? "Copy failed; select the text." : ""}
      </span>
    </>
  );
}
