import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import { AppHeader } from "@/components/AppHeader";

import { mono, sans } from "./fonts";
import "./globals.css";
import styles from "./layout.module.css";

export const metadata: Metadata = {
  title: { default: "OpsPilot", template: "%s | OpsPilot" },
  description:
    "Review the on-call agent's investigations, approve or reject its proposed actions, and browse benchmark results.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#172230" },
  ],
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable}`}>
      <body>
        <a href="#main" className={styles.skip}>
          Skip to content
        </a>
        <AppHeader />
        <main id="main" className={styles.main} tabIndex={-1}>
          {children}
        </main>
      </body>
    </html>
  );
}
