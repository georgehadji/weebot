"use client";

/**
 * AnnouncerProvider — one visually hidden live region for coarse, meaningful updates.
 *
 * A Mediator between the event stream and assistive technology: producers call
 * `useAnnounce()(text)`; nothing else on the page is a live region, so a busy stream does not
 * turn into a wall of speech.
 */

import { createContext, useCallback, useContext, useState } from "react";

type Announce = (text: string) => void;

const AnnouncerContext = createContext<Announce>(() => {});

export function AnnouncerProvider({ children }: { children: React.ReactNode }) {
  const [message, setMessage] = useState({ text: "", n: 0 });
  const announce = useCallback<Announce>(
    (text) => setMessage((prev) => ({ text, n: prev.n + 1 })),
    []
  );

  return (
    <AnnouncerContext.Provider value={announce}>
      {children}
      {/* The trailing zero-width space lets the same sentence be announced twice in a row. */}
      <div role="status" aria-live="polite" aria-atomic="true" className="sr-only">
        {message.text}
        {message.n % 2 ? "​" : ""}
      </div>
    </AnnouncerContext.Provider>
  );
}

export function useAnnounce(): Announce {
  return useContext(AnnouncerContext);
}
