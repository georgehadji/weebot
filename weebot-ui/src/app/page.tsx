"use client";

/**
 * Home — the mission center itself, not a marketing brochure.
 *
 * The previous version sold "58+ models" and feature bullets to its own
 * operator every time they opened the app; it took two navigations
 * (Start New Session → fill a form) before a single message could be
 * sent. This renders a usable composer with zero clicks.
 */

import { ConsoleShell } from "@/components/shell/ConsoleShell";
import { ConversationPane } from "@/components/conversation/ConversationPane";

export default function Home() {
  return (
    <ConsoleShell title="New conversation">
      <ConversationPane
        sessionId={null}
        status="none"
        // A hard navigation is deliberate: Next's router can be unavailable
        // during a Turbopack hot-reload while the first session is created.
        // eslint-disable-next-line @next/next/no-location-assign-relative-destination
        onSessionCreated={(id) => window.location.assign(`/sessions/${id}`)}
      />
    </ConsoleShell>
  );
}
