/** Pure scroll arithmetic for the conversation timeline (no DOM, no React). */

/** How far the viewport is from its end, in px (0 means exactly at the bottom). */
export function distanceFromBottom(el: {
  scrollHeight: number;
  scrollTop: number;
  clientHeight: number;
}): number {
  return el.scrollHeight - el.scrollTop - el.clientHeight;
}

/** True when the viewport is within *thresholdPx* of its end. */
export function isNearBottom(
  el: { scrollHeight: number; scrollTop: number; clientHeight: number },
  thresholdPx: number
): boolean {
  return distanceFromBottom(el) <= thresholdPx;
}

/** Events that arrived while the reader was scrolled up. */
export function unseenCount(total: number, seenAtBottom: number): number {
  return Math.max(0, total - seenAtBottom);
}
