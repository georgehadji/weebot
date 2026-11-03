import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@/providers/ToastProvider";

const replace = vi.fn();
let search = "";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  usePathname: () => "/behavior",
  useSearchParams: () => new URLSearchParams(search),
}));
vi.mock("@/components/behavior", () => ({ BehaviorPanel: () => <div data-testid="panel" /> }));

import BehaviorPage from "./page";

const renderPage = () =>
  render(
    <ToastProvider>
      <BehaviorPage />
    </ToastProvider>
  );

beforeEach(() => {
  replace.mockClear();
  search = "";
  window.history.replaceState({}, "", "/behavior");
  vi.stubGlobal("sessionStorage", { getItem: () => null });
  vi.stubGlobal("localStorage", { getItem: () => null });
});
afterEach(() => vi.unstubAllGlobals());

describe("/behavior tabs follow the URL", () => {
  it("opens the tab named in ?tab=, and the Monitor tab by default", () => {
    search = "tab=settings";
    renderPage();
    expect(screen.getByText("Storage Location")).toBeTruthy();
  });

  it("selecting a tab writes it to the URL; Monitor drops the parameter", () => {
    search = "tab=settings";
    renderPage();
    window.history.replaceState({}, "", "/behavior?tab=settings");
    fireEvent.click(screen.getByRole("tab", { name: "Monitor" }));
    expect(replace).toHaveBeenLastCalledWith("/behavior", { scroll: false });
  });
});

describe("/behavior Monitor tab", () => {
  it("offers 'Generate Demo ID', and the id field has the entry attributes", () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Generate Demo ID" }));
    const input = screen.getByLabelText("Session ID") as HTMLInputElement;
    expect(input.name).toBe("session-id");
    expect(input.getAttribute("autocomplete")).toBe("off");
    expect(input.getAttribute("spellcheck")).toBe("false");
  });

  it("gives the code samples distinct names", () => {
    search = "tab=settings";
    renderPage();
    expect(screen.getAllByRole("region", { name: "Environment variable examples" })).toHaveLength(1);
  });
});

/** jsdom has no object URLs; a subclass keeps the real URL untouched once the stub is removed. */
function stubObjectUrls(create: () => string, revoke: (url: string) => void) {
  vi.stubGlobal(
    "URL",
    class extends URL {
      static createObjectURL = create;
      static revokeObjectURL = revoke;
    }
  );
}

describe("/behavior self-knowledge download", () => {
  const open = async () => {
    search = "tab=settings";
    renderPage();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Download Self-Knowledge" }));
    });
  };

  it("a failed response shows a toast with a next step and creates no file", async () => {
    const create = vi.fn(() => "blob:none");
    stubObjectUrls(create, vi.fn());
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 500 })));
    await open();
    expect(screen.getByRole("alert").textContent).toContain("try again");
    expect(create).not.toHaveBeenCalled();
  });

  it("a successful download releases the object URL", async () => {
    const revoke = vi.fn();
    stubObjectUrls(() => "blob:x", revoke);
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ content: "# me" }), { status: 200 })));
    await open();
    expect(revoke).toHaveBeenCalledWith("blob:x");
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
