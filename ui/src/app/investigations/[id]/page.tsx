import type { Metadata } from "next";

import { InvestigationView } from "@/components/InvestigationView";

export const metadata: Metadata = { title: "Investigation" };

export default async function InvestigationPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <InvestigationView investigationId={decodeURIComponent(id)} />;
}
