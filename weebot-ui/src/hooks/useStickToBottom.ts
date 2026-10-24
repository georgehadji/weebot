"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { isNearBottom, unseenCount } from "@/lib/scroll";

/**
 * Keep a scrolling timeline pinned to its newest row — unless the reader scrolled up.
 *
 * "At the bottom" is whether a sentinel after the last row is (nearly) in view, observed with an
 * IntersectionObserver: unlike a scroll handler it also notices content that grows without a
 * scroll (a tool row expanding, a late image). While the reader is scrolled up, `unseen` counts
 * the rows that arrived since they left, for a "Jump to latest" pill.
 */
export function useStickToBottom(itemCount: number, thresholdPx = 80) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const atBottomRef = useRef(true);
  const itemCountRef = useRef(itemCount);
  // `leftAt` is the row count at the moment the reader scrolled away (only used when !atBottom).
  const [view, setView] = useState({ atBottom: true, leftAt: itemCount });

  useEffect(() => {
    itemCountRef.current = itemCount;
  }, [itemCount]);

  useEffect(() => {
    const viewport = viewportRef.current;
    const sentinel = sentinelRef.current;
    if (!viewport || !sentinel) return;
    const update = (near: boolean) => {
      atBottomRef.current = near;
      setView((prev) =>
        prev.atBottom === near ? prev : { atBottom: near, leftAt: itemCountRef.current }
      );
    };
    if (typeof IntersectionObserver === "undefined") {
      const onScroll = () => update(isNearBottom(viewport, thresholdPx));
      viewport.addEventListener("scroll", onScroll, { passive: true });
      return () => viewport.removeEventListener("scroll", onScroll);
    }
    const observer = new IntersectionObserver(([entry]) => update(entry.isIntersecting), {
      root: viewport,
      rootMargin: `0px 0px ${thresholdPx}px 0px`,
    });
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [thresholdPx]);

  // Follow new rows only while the reader is at the bottom.
  useEffect(() => {
    const viewport = viewportRef.current;
    if (viewport && atBottomRef.current) viewport.scrollTop = viewport.scrollHeight;
  }, [itemCount]);

  const scrollToBottom = useCallback(() => {
    const viewport = viewportRef.current;
    if (viewport) viewport.scrollTop = viewport.scrollHeight;
  }, []);

  return {
    viewportRef,
    sentinelRef,
    atBottom: view.atBottom,
    unseen: view.atBottom ? 0 : unseenCount(itemCount, view.leftAt),
    scrollToBottom,
  };
}
