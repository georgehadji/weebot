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
