import { describe, expect, it } from "vitest";
import { announcementFor } from "./announce";
import { AgentEvent } from "@/types/events";

const base = { id: "e", timestamp: "t", session_id: "s" };

describe("announcementFor", () => {
  it("announces step outcomes, questions, errors and completion", () => {
    expect(announcementFor({ ...base, type: "step", step_id: "1", description: "Fetch data", status: "completed" })).toBe(
      "Step completed: Fetch data"
    );
    expect(announcementFor({ ...base, type: "step", step_id: "1", description: "Fetch data", status: "failed" })).toBe(
      "Step failed: Fetch data"
    );
    expect(announcementFor({ ...base, type: "wait_for_user", question: "Which file?" })).toContain("Which file?");
    expect(announcementFor({ ...base, type: "error", error: "boom" })).toBe("Error: boom");
    expect(announcementFor({ ...base, type: "done" })).toBe("Session completed");
  });

  it("stays silent for the rest of the stream", () => {
    const quiet: AgentEvent[] = [
      { ...base, type: "message", role: "assistant", message: "hello" },
      { ...base, type: "step", step_id: "1", description: "x", status: "running" },
      { ...base, type: "notification", text: "n" },
      { ...base, type: "tool", tool_call_id: "c", tool_name: "bash", function_name: "run", function_args: {}, status: "calling" },
    ];
    expect(quiet.map(announcementFor)).toEqual([null, null, null, null]);
  });

  it("announces a failed tool but not a successful one", () => {
    const tool = { ...base, type: "tool" as const, tool_call_id: "c", tool_name: "bash", function_name: "run", function_args: {}, status: "called" as const };
    expect(announcementFor({ ...tool, is_error: true })).toBe("Tool bash failed");
    expect(announcementFor({ ...tool, is_error: false })).toBeNull();
  });
});
