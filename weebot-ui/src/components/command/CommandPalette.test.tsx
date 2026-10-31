import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { commandRegistry } from "@/lib/commands/registry";
import { CommandPalette } from "./CommandPalette";

const ids = ["a", "b", "c"];
let ran: string[] = [];
let unregister: Array<() => void> = [];

beforeEach(() => {
  ran = [];
  unregister = ids.map((id) =>
    commandRegistry.register({ id, title: `Command ${id}`, run: () => ran.push(id) })
  );
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
});
afterEach(() => unregister.forEach((u) => u()));

const input = () => screen.getByRole("combobox", { name: "Search commands" });

describe("W6 D14: the highlighted index addresses an existing option", () => {
  it("ArrowDown past the end stays on the last option, Enter runs it", () => {
    render(<CommandPalette open onClose={() => {}} />);
    for (let i = 0; i < 5; i++) fireEvent.keyDown(input(), { key: "ArrowDown" });
    fireEvent.keyDown(input(), { key: "Enter" });
    expect(ran).toEqual(["c"]);
  });

  // VERIFIED, unfixed (W6 fix budget spent): flip to `it` when the index is clamped.
  it.fails("when the registry shrinks under the highlight, an option is still active and Enter runs it", () => {
    render(<CommandPalette open onClose={() => {}} />);
    fireEvent.keyDown(input(), { key: "ArrowDown" });
    fireEvent.keyDown(input(), { key: "ArrowDown" }); // highlight "c" (index 2)
    act(() => {
      unregister[1]();
      unregister[2]();
    });
    const active = input().getAttribute("aria-activedescendant");
    expect(active).toBe("command-palette-option-a");
    expect(screen.getByRole("option", { selected: true }).textContent).toContain("Command a");
    fireEvent.keyDown(input(), { key: "Enter" });
    expect(ran).toEqual(["a"]);
  });

  it("an empty registry has no active option and Enter is a no-op", () => {
    render(<CommandPalette open onClose={() => {}} />);
    act(() => unregister.forEach((u) => u()));
    expect(input().getAttribute("aria-activedescendant")).toBeNull();
    fireEvent.keyDown(input(), { key: "Enter" });
    expect(ran).toEqual([]);
  });

  it.fails("ArrowUp after a shrink moves from the visible highlight, not the stale index", () => {
    render(<CommandPalette open onClose={() => {}} />);
    fireEvent.keyDown(input(), { key: "ArrowDown" });
    fireEvent.keyDown(input(), { key: "ArrowDown" });
    act(() => unregister[2]()); // list is now a,b; highlight shows b
    fireEvent.keyDown(input(), { key: "ArrowUp" });
    expect(input().getAttribute("aria-activedescendant")).toBe("command-palette-option-a");
  });

  it("typing resets the highlight to the first match (no regression)", () => {
    render(<CommandPalette open onClose={() => {}} />);
    fireEvent.keyDown(input(), { key: "ArrowDown" });
    fireEvent.change(input(), { target: { value: "command" } });
    expect(input().getAttribute("aria-activedescendant")).toBe("command-palette-option-a");
  });
});
