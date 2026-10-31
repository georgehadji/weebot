import { describe, expect, it } from "vitest";
import { canSubmit, composerReducer, initialComposerState } from "./composer";

describe("composer state machine", () => {
  it("submit moves the text out of the box and into sending", () => {
    const s = composerReducer(initialComposerState("hello"), { type: "submit" });
    expect(s).toEqual({ draft: "", phase: "sending", error: null });
  });

  it("ignores a submit with nothing but whitespace, or while already sending", () => {
    const empty = initialComposerState("   ");
    expect(composerReducer(empty, { type: "submit" })).toBe(empty);
    const sending = { draft: "next", phase: "sending" as const, error: null };
    expect(canSubmit(sending)).toBe(false);
    expect(composerReducer(sending, { type: "submit" })).toBe(sending);
  });

  it("the user can keep typing while a send is in flight", () => {
    let s = composerReducer(initialComposerState("one"), { type: "submit" });
    s = composerReducer(s, { type: "edit", draft: "two" });
    expect(s).toMatchObject({ draft: "two", phase: "sending" });
    s = composerReducer(s, { type: "sent" });
    expect(s).toMatchObject({ draft: "two", phase: "idle" });
  });

  it("a failure returns the text when the box is empty", () => {
    let s = composerReducer(initialComposerState("one"), { type: "submit" });
    s = composerReducer(s, { type: "failed", error: "offline", text: "one" });
    expect(s).toEqual({ draft: "one", phase: "failed", error: "offline" });
    expect(canSubmit(s)).toBe(true);
  });

  it("a failure never overwrites something newer the user typed", () => {
    let s = composerReducer(initialComposerState("one"), { type: "submit" });
    s = composerReducer(s, { type: "edit", draft: "newer" });
    s = composerReducer(s, { type: "failed", error: "offline", text: "one" });
    expect(s.draft).toBe("newer");
  });

  it("retrying clears the error", () => {
    let s = composerReducer(initialComposerState("one"), { type: "submit" });
    s = composerReducer(s, { type: "failed", error: "offline", text: "one" });
    s = composerReducer(s, { type: "submit" });
    expect(s).toMatchObject({ phase: "sending", error: null });
  });
});

describe("retry (W3)", () => {
  it("a retry moves a failed composer to sending and clears the error, keeping the draft", () => {
    const failed = { draft: "newer", phase: "failed" as const, error: "offline" };
    expect(composerReducer(failed, { type: "retry" })).toEqual({ draft: "newer", phase: "sending", error: null });
  });
  it("a retry from idle also enters sending", () => {
    expect(composerReducer(initialComposerState(), { type: "retry" })).toMatchObject({ phase: "sending" });
  });
  it("a retry while sending changes nothing, and a later 'sent' settles it", () => {
    const sending = { draft: "", phase: "sending" as const, error: null };
    expect(composerReducer(sending, { type: "retry" })).toBe(sending);
    const retried = composerReducer({ draft: "", phase: "failed", error: "x" }, { type: "retry" });
    expect(composerReducer(retried, { type: "sent" })).toMatchObject({ phase: "idle", error: null });
  });
});
