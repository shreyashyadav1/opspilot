import styles from "./JsonBlock.module.css";

export function JsonBlock({ value, label }: { value: unknown; label: string }) {
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return (
    // Focusable so keyboard users can scroll long output.
    <pre className={styles.block} tabIndex={0} aria-label={label}>
      <code>{text}</code>
    </pre>
  );
}
