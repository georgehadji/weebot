"use client";

/**
 * Home — the mission center itself, not a marketing brochure.
 *
 * The previous version sold "58+ models" and feature bullets to its own
 * operator every time they opened the app; it took two navigations
 * (Start New Session → fill a form) before a single message could be
 * sent. This renders a usable composer with zero clicks.
 */

import { useRouter } from "next/navigation";
import { ConsoleShell } from "@/components/shell/ConsoleShell";
import { ConversationPane } from "@/components/conversation/ConversationPane";

export default function Home() {
  const router = useRouter();

  return (
    <ConsoleShell title="New conversation">
      <ConversationPane
        sessionId={null}
        status="none"
        onSessionCreated={(id) => router.push(`/sessions/${id}`)}
      />
    </ConsoleShell>
  );
}
