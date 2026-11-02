/**
 * W2 R6 — the at-bottom / unseen arithmetic, driven through a fake IntersectionObserver.
 * Guarantees: (1) unseen counts only rows that arrived after the reader left, (2) it is 0
 * whenever the reader is at the bottom, (3) following happens only while at the bottom.
 */
import { act, render } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useStickToBottom } from "./useStickToBottom";

let fire: (isIntersecting: boolean) => void = () => {};
vi.stubGlobal(
  "IntersectionObserver",
  class {
    constructor(private cb: (e: { isIntersecting: boolean }[]) => void) {
      fire = (v) => this.cb([{ isIntersecting: v }]);
    }
    observe() {}
    disconnect() {}
  }
);
afterEach(() => (fire = () => {}));

let latest: ReturnType<typeof useStickToBottom>;
function Probe({ count }: { count: number }) {
  const { viewportRef, sentinelRef, atBottom, unseen, scrollToBottom } = useStickToBottom(count);
  useEffect(() => {
    latest = { viewportRef, sentinelRef, atBottom, unseen, scrollToBottom };
  });
  return (
    <div ref={viewportRef}>
      <div ref={sentinelRef} />
    </div>
  );
}
const setup = (count: number) => {
  const r = render(<Probe count={count} />);
  const viewport = r.container.firstElementChild as HTMLElement;
  Object.defineProperty(viewport, "scrollHeight", { value: 999, configurable: true });
  return { ...r, viewport, more: (n: number) => r.rerender(<Probe count={n} />) };
};

describe("useStickToBottom", () => {
  it("starts at the bottom with nothing unseen", () => {
    setup(3);
    expect(latest.atBottom).toBe(true);
    expect(latest.unseen).toBe(0);
  });

  it("counts only rows that arrived after the reader scrolled away", () => {
    const { more } = setup(5);
    act(() => fire(false));
    more(8);
    expect(latest.atBottom).toBe(false);
    expect(latest.unseen).toBe(3);
  });

  it("returning to the bottom clears the count; leaving again restarts it from there", () => {
    const { more } = setup(5);
    act(() => fire(false));
    more(8);
    act(() => fire(true));
    expect(latest.unseen).toBe(0);
    act(() => fire(false));
    more(9);
    expect(latest.unseen).toBe(1);
  });

  it("follows new rows only while at the bottom", () => {
    const { more, viewport } = setup(1);
    more(2);
    expect(viewport.scrollTop).toBe(999);
    act(() => fire(false));
    viewport.scrollTop = 10;
    more(3);
    expect(viewport.scrollTop).toBe(10);
  });
});
