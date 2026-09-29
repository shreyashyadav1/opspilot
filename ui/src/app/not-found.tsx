import Link from "next/link";

import { EmptyState } from "@/components/ui";

export default function NotFound() {
  return (
    <EmptyState title="This page does not exist">
      <p>
        Go back to the <Link href="/">incident list</Link>.
      </p>
    </EmptyState>
  );
}
