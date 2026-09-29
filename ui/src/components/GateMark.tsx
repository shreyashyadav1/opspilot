/** Two posts and a barrier: the approval gate the whole product is built around. */
export function GateMark({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      width="22"
      height="22"
      aria-hidden="true"
      focusable="false"
    >
      <rect x="3" y="3" width="3" height="18" rx="1" fill="currentColor" />
      <rect x="18" y="3" width="3" height="18" rx="1" fill="currentColor" />
      <rect x="6" y="10" width="12" height="4" fill="var(--gate-bar)" />
    </svg>
  );
}
