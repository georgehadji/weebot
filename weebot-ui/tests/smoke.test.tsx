import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

function HelloWorld() {
  return <h1>Hello, World!</h1>;
}

describe("HelloWorld", () => {
  it("renders the greeting text", () => {
    render(<HelloWorld />);
    expect(screen.getByText("Hello, World!")).toBeDefined();
  });

  it("renders an h1 element", () => {
    render(<HelloWorld />);
    const heading = screen.getByRole("heading", { level: 1 });
    expect(heading).toBeDefined();
    expect(heading.textContent).toBe("Hello, World!");
  });
});
