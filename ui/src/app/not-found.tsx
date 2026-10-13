import Link from "next/link";

import { EmptyState } from "@/components/ui";

export default function NotFound() {
  return (
    <EmptyState title="This page does not exist" headingLevel={1}>
      <p>
        Go back to the <Link href="/">incident list</Link>, or open the{" "}
        <Link href="/benchmarks">benchmark runs</Link>.
      </p>
    </EmptyState>
  );
}
