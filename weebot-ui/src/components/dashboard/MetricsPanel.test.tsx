import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AnnouncerProvider } from "@/providers/AnnouncerProvider";
import { MetricsPanel } from "./MetricsPanel";

const base = {
  activeSessions: 2,
  totalSessions: 1500,
  avgResponseTime: 123.4,
  cpuUsage: 40,
  memoryUsage: 30.6,
  dbSize: "12 MB",
  requestsPerMinute: 12345,
};

const ui = (metrics = base) => (
  <AnnouncerProvider>
    <MetricsPanel metrics={metrics} />
  </AnnouncerProvider>
);
const live = () => document.querySelector("[aria-live='polite']")!.textContent!.replace(/​/g, "");

describe("MetricsPanel", () => {
  it("formats numbers and percentages for the reader", () => {
    render(ui());
    expect(screen.getByText("40%")).toBeTruthy();
    expect(screen.getByText("31%")).toBeTruthy();
    expect(screen.getByText("123ms")).toBeTruthy();
    expect(screen.getByText("12,345")).toBeTruthy();
    expect(screen.getByText("of 1,500 total")).toBeTruthy();
  });

  it("marks icons decorative, aligns figures, and uses h3 under the page's h2 card", () => {
    const { container } = render(ui());
    expect(container.querySelectorAll("svg:not([aria-hidden='true'])")).toHaveLength(0);
    expect(container.querySelectorAll(".tabular-nums").length).toBeGreaterThanOrEqual(6);
    expect(screen.getAllByRole("heading", { level: 3 })).toHaveLength(6);
  });

  it("announces only when usage crosses the high line, never for polled values or on mount", () => {
    const { rerender } = render(ui({ ...base, cpuUsage: 95 }));
    expect(live()).toBe("");
    rerender(ui({ ...base, cpuUsage: 96 }));
    expect(live()).toBe("");
    rerender(ui({ ...base, cpuUsage: 50 }));
    expect(live()).toBe("CPU usage is back to normal.");
    rerender(ui({ ...base, cpuUsage: 91, memoryUsage: 10 }));
    expect(live()).toBe("CPU usage is high, 91%.");
  });
});
