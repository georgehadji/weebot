/**
 * Composer state machine — a pure reducer.
 *
 * Sending, failed and retry are states, not flags: the textarea is never disabled (focus stays
 * where the user is typing) and a failed send keeps the text so it can be sent again.
 */

export type ComposerPhase = "idle" | "sending" | "failed";

export interface ComposerState {
  draft: string;
  phase: ComposerPhase;
  /** Message of the last failure; cleared when a new send starts. */
  error: string | null;
}

export type ComposerAction =
  | { type: "edit"; draft: string }
  | { type: "submit" }
  | { type: "sent" }
  | { type: "failed"; error: string; text: string };

export const initialComposerState = (draft = ""): ComposerState => ({
  draft,
  phase: "idle",
  error: null,
});

export function canSubmit(state: ComposerState): boolean {
  return state.draft.trim().length > 0 && state.phase !== "sending";
}

export function composerReducer(state: ComposerState, action: ComposerAction): ComposerState {
  switch (action.type) {
    case "edit":
      return { ...state, draft: action.draft };
    case "submit":
      // The text leaves the box the moment it is sent; typing the next message is allowed.
      return canSubmit(state) ? { draft: "", phase: "sending", error: null } : state;
    case "sent":
      return state.phase === "sending" ? { ...state, phase: "idle" } : state;
    case "failed":
      // Give the text back unless the user has already started something new.
      return {
        draft: state.draft === "" ? action.text : state.draft,
        phase: "failed",
        error: action.error,
      };
  }
}
