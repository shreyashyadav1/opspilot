import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import { AppHeader } from "@/components/AppHeader";

import { b612, intelOneMono } from "./fonts";
import "./globals.css";
import styles from "./layout.module.css";

export const metadata: Metadata = {
  title: { default: "OpsPilot", template: "%s | OpsPilot" },
  description:
    "Review the on-call agent’s investigations, approve or reject its proposed actions, and browse benchmark results.",
  applicationName: "OpsPilot",
};

export const viewport: Viewport = {
  // The page background (--night): the dashboard is dark only.
  themeColor: "#1a1618",
  colorScheme: "dark",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${b612.variable} ${intelOneMono.variable}`}>
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
