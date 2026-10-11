import localFont from "next/font/local";

// B612 was drawn for Airbus cockpit displays: read at a glance, under stress, in a dark cockpit.
// That is the on-call engineer paged at 3 a.m., deciding whether the agent may change a service.
// It ships in two weights, so hierarchy comes from size and contrast rather than in-between weights.
export const sans = localFont({
  src: [
    {
      path: "../../node_modules/@fontsource/b612/files/b612-latin-400-normal.woff2",
      weight: "400",
      style: "normal",
    },
    {
      path: "../../node_modules/@fontsource/b612/files/b612-latin-700-normal.woff2",
      weight: "700",
      style: "normal",
    },
  ],
  display: "swap",
  variable: "--font-sans",
  fallback: ["Segoe UI", "system-ui", "sans-serif"],
});

// Intel One Mono, designed with low-vision developers, for what is literally code: tool calls,
// versions, ids, config keys and log lines. Slashed zero, and punctuation centred in its cell, so
// "1.8.4" and "http://payments:8080" read as written.
export const mono = localFont({
  src: "../../node_modules/@fontsource-variable/intel-one-mono/files/intel-one-mono-latin-wght-normal.woff2",
  weight: "300 700",
  style: "normal",
  display: "swap",
  variable: "--font-mono",
  fallback: ["ui-monospace", "SF Mono", "Menlo", "monospace"],
});
