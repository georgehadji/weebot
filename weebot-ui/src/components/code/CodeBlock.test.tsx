import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AnnouncerProvider } from "@/providers/AnnouncerProvider";
import { CodeBlock } from "./CodeBlock";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const ui = (props: Partial<React.ComponentProps<typeof CodeBlock>> = {}) => (
  <AnnouncerProvider>
    <CodeBlock code="print('hi')" {...props} />
  </AnnouncerProvider>
);
const live = () => document.querySelector("[aria-live='polite']")!.textContent!.replace(/​/g, "");

function stubClipboard(writeText: () => Promise<void>) {
  vi.stubGlobal("navigator", { clipboard: { writeText } });
}

describe("CodeBlock", () => {
  it("shows Copy even without a filename, and copies then announces it", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    stubClipboard(writeText);
    render(ui());
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Copy" })));
    expect(writeText).toHaveBeenCalledWith("print('hi')");
    expect(screen.getByRole("button", { name: "Copied" })).toBeTruthy();
    expect(live()).toBe("Copied");
  });

  it("says so when the clipboard is refused, instead of throwing", async () => {
    stubClipboard(() => Promise.reject(new Error("denied")));
    render(ui());
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Copy" })));
    expect(screen.getByRole("button", { name: "Copy failed" })).toBeTruthy();
    expect(live()).toMatch(/Couldn’t copy/);
  });

  it("falls back when there is no Clipboard API at all", async () => {
    vi.stubGlobal("navigator", {});
    render(ui());
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Copy" })));
    expect(screen.getByRole("button", { name: "Copy failed" })).toBeTruthy();
  });

  it("resets the label after 2 s and clears the timer on unmount", async () => {
    vi.useFakeTimers();
    stubClipboard(() => Promise.resolve());
    const { unmount } = render(ui());
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Copy" })));
    act(() => void vi.advanceTimersByTime(2000));
    expect(screen.getByRole("button", { name: "Copy" })).toBeTruthy();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Copy" })));
    expect(vi.getTimerCount()).toBeGreaterThan(0);
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("makes the code a labelled, focusable, untranslated region with decorative icons", () => {
    const { container } = render(ui({ filename: "app.py" }));
    const region = screen.getByRole("region", { name: "Code: app.py" });
    expect(region.getAttribute("tabindex")).toBe("0");
    expect(region.getAttribute("translate")).toBe("no");
    expect(screen.getByText("app.py").getAttribute("translate")).toBe("no");
    expect(container.querySelectorAll("button svg[aria-hidden='true']")).toHaveLength(1);
    expect(container.innerHTML).not.toMatch(/#[0-9a-f]{6}/i);
  });
});
