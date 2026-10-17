"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { AccessKey } from "./AccessKey";
import { GateMark } from "./GateMark";
import { ModelIndicator } from "./ModelIndicator";
import styles from "./AppHeader.module.css";

const NAV = [
  {
    href: "/",
    label: "Incidents",
    match: (path: string) => path === "/" || path.startsWith("/investigations"),
  },
  {
    href: "/benchmarks",
    label: "Benchmark",
    match: (path: string) => path.startsWith("/benchmarks"),
  },
];

export function AppHeader() {
  const pathname = usePathname() ?? "/";
  return (
    <header className={styles.header}>
      <div className={styles.inner}>
        <Link href="/" className={styles.brand}>
          <GateMark className={styles.mark} />
          <span>OpsPilot</span>
        </Link>
        <nav aria-label="Main" className={styles.nav}>
          <ul>
            {NAV.map((item) => {
              const current = item.match(pathname);
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    className={current ? styles.current : undefined}
                    aria-current={current ? "page" : undefined}
                  >
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
        <ModelIndicator />
        <AccessKey />
      </div>
    </header>
  );
}
