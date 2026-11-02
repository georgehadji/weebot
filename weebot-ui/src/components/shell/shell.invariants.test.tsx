/**
 * W6 shell invariants, restated as properties (parents for W7's primitive contracts):
 *   P1 exactly one <main>, and the skip link is the first tab stop and targets it
 *   P2 exactly one <h1> per route: the app bar's (slot) XOR the page's own
 *   P3 a keyboard shortcut shown in the palette is a shortcut that exists
 *   P4 activating a link inside a modal sheet/menu dismisses it, even to the current path
 *   P5 closing a sheet returns focus to what opened it
 *   P6 slots belong to the mounted page: the outgoing page's clear never erases the incoming page's fill
 */
import { act, fireEvent, render, screen } from "@testing-library/react";
import type { ComponentProps, ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useShellSlots } from "@/hooks/useShellSlots";
import { ShellProvider } from "@/providers/ShellProvider";
import { ThemeProvider } from "@/providers/ThemeProvider";
import RouteError from "@/app/error";
import { AppShell } from "./AppShell";
import { ConsoleShell } from "./ConsoleShell";

const push = vi.fn();
let pathname = "/";
vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: ComponentProps<"a">) => (
    <a
      href={href}
      {...props}
      onClick={(e) => {
        e.preventDefault(); // jsdom cannot navigate; the router is mocked
        props.onClick?.(e);
      }}
    >
      {children}
    </a>
  ),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  usePathname: () => pathname,
}));
vi.mock("@/components/shell/SessionRail", () => ({
  SessionRail: () => (
    <nav aria-label="Sessions">
      <a href="#session-one" onClick={(e) => e.preventDefault()}>
        Session one
      </a>
    </nav>
  ),
}));
vi.mock("@/components/dock/Dock", () => ({ MissionDock: () => <div>dock</div> }));

let desktop = false;
beforeEach(() => {
  pathname = "/";
  push.mockReset();
  desktop = false;
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
  vi.stubGlobal("matchMedia", (query: string) => ({
    media: query,
    get matches() {
      return desktop;
    },
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
});
afterEach(() => vi.unstubAllGlobals());

function Page({ title, h1 }: { title?: string; h1?: string }) {
  useShellSlots({ title });
  return h1 ? <h1>{h1}</h1> : <p>page body</p>;
}

const Frame = ({ children }: { children: ReactNode }) => (
  <ThemeProvider>
    <ShellProvider>
      <AppShell>{children}</AppShell>
    </ShellProvider>
  </ThemeProvider>
);
const renderShell = (children: ReactNode) => render(<Frame>{children}</Frame>);

const renderConsole = () =>
  render(
    <ShellProvider>
      <ConsoleShell>
        <p>content</p>
      </ConsoleShell>
    </ShellProvider>
  );

describe("P1/P2: landmarks", () => {
  it("one <main>; the skip link is the first tab stop and targets it", () => {
    renderShell(<Page title="Hello" />);
    expect(screen.getAllByRole("main")).toHaveLength(1);
    const main = screen.getByRole("main");
    const skip = screen.getByText("Skip to content") as HTMLAnchorElement;
    expect(skip.getAttribute("href")).toBe(`#${main.id}`);
    expect(main.getAttribute("tabindex")).toBe("-1");
    const focusable = document.body.querySelectorAll<HTMLElement>("a[href],button,input");
    expect(focusable[0]).toBe(skip);
  });

  it("a page that names itself through the slot yields exactly one h1, the bar's", () => {
    renderShell(<Page title="New conversation" />);
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("New conversation");
  });

  it("a page with its own h1 and no slot title yields exactly one h1", () => {
    renderShell(<Page h1="Ops Console" />);
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  });

  it("the route error boundary keeps the one-h1 invariant", () => {
    renderShell(<RouteError error={new Error("boom")} reset={() => {}} />);
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getAllByRole("main")).toHaveLength(1);
  });

  it("the route error boundary's retry calls reset (no regression)", () => {
    const reset = vi.fn();
    renderShell(<RouteError error={new Error("boom")} reset={reset} />);
    fireEvent.click(screen.getByText("Try again"));
    expect(reset).toHaveBeenCalledTimes(1);
  });
});

describe("P3: shortcuts shown are shortcuts that exist", () => {
  it("every shortcut label in the palette fires its command", () => {
    renderShell(<Page title="x" />);
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const labelled = screen.getAllByRole("option").filter((o) => /⌘[A-Z]/.test(o.textContent ?? ""));
    for (const option of labelled) {
      const key = /⌘([A-Z])/.exec(option.textContent ?? "")![1].toLowerCase();
      fireEvent.keyDown(window, { key, metaKey: true });
      expect(push, `${option.textContent} advertises a shortcut with no handler`).toHaveBeenCalled();
      push.mockReset();
    }
  });

  it("Ctrl/Cmd+K toggles the palette (no regression)", () => {
    renderShell(<Page title="x" />);
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    expect(screen.getByRole("combobox")).toBeTruthy();
    fireEvent.keyDown(window, { key: "K", ctrlKey: true });
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("palette: choosing a command runs it and closes the palette", () => {
    renderShell(<Page title="x" />);
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    fireEvent.click(screen.getByText("Go to Ops"));
    expect(push).toHaveBeenCalledWith("/ops");
    expect(screen.queryByRole("combobox")).toBeNull();
  });
});

describe("P4: a link inside a modal dismisses it, even to the current path", () => {
  it("the menu closes when the operator picks the page they are already on", () => {
    pathname = "/ops";
    renderShell(<Page title="x" />);
    fireEvent.click(screen.getByLabelText("Open menu"));
    const dialog = screen.getByRole("dialog");
    fireEvent.click(dialog.querySelector('a[href="/ops"]')!);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("New session from the menu at '/' closes it", () => {
    renderShell(<Page title="x" />);
    fireEvent.click(screen.getByLabelText("Open menu"));
    fireEvent.click(screen.getByRole("dialog").querySelector('a[href="/"]')!);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("the menu's theme toggle does not close it (no regression)", () => {
    renderShell(<Page title="x" />);
    fireEvent.click(screen.getByLabelText("Open menu"));
    fireEvent.click(screen.getByRole("dialog").querySelector("button:not([aria-label])")!);
    expect(screen.getByRole("dialog")).toBeTruthy();
  });

  it("the rail sheet closes when a rail link is activated at the same path", () => {
    pathname = "/sessions/s1";
    renderConsole();
    fireEvent.click(screen.getByText("Sessions"));
    expect(screen.getByRole("dialog", { name: "Sessions" })).toBeTruthy();
    fireEvent.click(screen.getByText("Session one"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("clicking inside the sheet away from any link leaves it open (no regression)", () => {
    renderConsole();
    fireEvent.click(screen.getByText("Sessions"));
    fireEvent.click(screen.getByRole("navigation", { name: "Sessions" }));
    expect(screen.getByRole("dialog", { name: "Sessions" })).toBeTruthy();
  });
});

describe("P5: focus returns to what opened the sheet", () => {
  it("closing the rail sheet with its Close button restores focus to the opener", async () => {
    renderConsole();
    const opener = screen.getByRole("button", { name: /Sessions/ });
    opener.focus();
    fireEvent.click(opener);
    fireEvent.click(screen.getByLabelText("Close panel"));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(opener);
  });
});

describe("P6: slots belong to the mounted page", () => {
  const swap = (a: boolean) => (a ? <Page key="a" title="A" /> : <Page key="b" title="B" />);

  it("swapping pages in one commit leaves the incoming page's title", () => {
    const { rerender } = renderShell(swap(true));
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("A");
    rerender(<Frame>{swap(false)}</Frame>);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("B");
  });

  it("unmounting the page clears its title (no stale h1)", () => {
    const { rerender } = renderShell(<Page title="A" />);
    rerender(
      <Frame>
        <p>other</p>
      </Frame>
    );
    expect(screen.queryByRole("heading", { level: 1 })).toBeNull();
  });
});
