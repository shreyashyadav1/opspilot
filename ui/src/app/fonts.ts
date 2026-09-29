import localFont from "next/font/local";

// Atkinson Hyperlegible was drawn for low-vision readers: 1/l/I and 0/O never look alike.
// That matters when an on-call engineer compares version numbers and IDs at 3 a.m.
export const sans = localFont({
  src: "../../node_modules/@fontsource-variable/atkinson-hyperlegible-next/files/atkinson-hyperlegible-next-latin-wght-normal.woff2",
  weight: "200 800",
  style: "normal",
  display: "swap",
  variable: "--font-sans",
});

export const mono = localFont({
  src: "../../node_modules/@fontsource-variable/atkinson-hyperlegible-mono/files/atkinson-hyperlegible-mono-latin-wght-normal.woff2",
  weight: "200 800",
  style: "normal",
  display: "swap",
  variable: "--font-mono",
});
