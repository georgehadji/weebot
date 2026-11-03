// Times render in the reader's zone, so pin it: a test that asserts a clock time reads the same on a
// developer machine and in CI.
process.env.TZ = "UTC";

// jsdom has no matchMedia, and `useMediaQuery` (reduced motion, desktop breakpoint) needs one.
// Tests that care about a specific query stub their own; this is the "nothing matches" default.
if (typeof window !== "undefined" && typeof window.matchMedia !== "function") {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList;
}
