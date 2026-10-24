import { describe, expect, it } from "vitest";
import { distanceFromBottom, isNearBottom, unseenCount } from "./scroll";

const box = (scrollHeight: number, scrollTop: number, clientHeight: number) => ({
  scrollHeight,
  scrollTop,
  clientHeight,
});

describe("scroll arithmetic", () => {
  it("is 0 at the very bottom", () => {
    expect(distanceFromBottom(box(1000, 600, 400))).toBe(0);
  });
  it("counts the pixels left to scroll", () => {
    expect(distanceFromBottom(box(1000, 300, 400))).toBe(300);
  });
  it("treats the threshold as inclusive", () => {
    expect(isNearBottom(box(1000, 520, 400), 80)).toBe(true);
    expect(isNearBottom(box(1000, 519, 400), 80)).toBe(false);
  });
  it("content shorter than the viewport is always at the bottom", () => {
    expect(isNearBottom(box(200, 0, 400), 80)).toBe(true);
  });
  it("counts unseen events and never goes negative", () => {
    expect(unseenCount(12, 9)).toBe(3);
    expect(unseenCount(5, 9)).toBe(0);
  });
});
