/**
 * Contract between base-ui and the class selectors in components/ui.
 *
 * base-ui emits `data-orientation="horizontal"`, `data-active`, `data-checked` ...; the shadcn
 * template once selected on `data-horizontal:`, which never matched and laid Tabs out as a row.
 * These tests fail when a selector names an attribute the primitive does not emit.
 */
import { readdirSync, readFileSync } from "node:fs"
import path from "node:path"
import { act, fireEvent, render, screen } from "@testing-library/react"
import { createRef, useRef, useState } from "react"
import { describe, expect, it, vi } from "vitest"

import { Alert } from "./alert"
import { Badge } from "./badge"
import { Button } from "./button"
import { Dialog, DialogContent, DialogSheet, DialogTitle } from "./dialog"
import { Input } from "./input"
import { Progress } from "./progress"
import { ScrollArea } from "./scroll-area"
import { Separator } from "./separator"
import { Switch } from "./switch"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./tabs"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "./tooltip"

// Boolean `data-*` attributes base-ui is known to emit (checked against its docs / DOM output).
const EMITTED = new Set([
  "active", "open", "closed", "checked", "unchecked", "disabled", "highlighted", "pressed",
  "popup-open", "starting-style", "ending-style", "selected", "dragging", "valid", "invalid",
])
// `data-[name=value]` and `data-[name]` forms are explicit, so only the bare shorthand is audited.
const BARE_VARIANT = /(?<![\w[-])(?:group-|peer-)?data-([a-z][a-z-]*)(?:\/[\w-]+)?:/g

describe("components/ui class selectors", () => {
  const dir = __dirname
  const files = readdirSync(dir).filter((f) => f.endsWith(".tsx") && !f.endsWith(".test.tsx"))

  it.each(files)("%s uses only data-* shorthands that base-ui emits", (file) => {
    const source = readFileSync(path.join(dir, file), "utf8")
    const unknown = [...source.matchAll(BARE_VARIANT)]
      .map((m) => m[1])
      .filter((name) => !EMITTED.has(name))
    expect([...new Set(unknown)]).toEqual([])
  })
})

describe("emitted attributes", () => {
  it("Tabs root carries data-orientation and the list sits under it", () => {
    const { container } = render(
      <Tabs defaultValue="a">
        <TabsList>
          <TabsTrigger value="a">A</TabsTrigger>
          <TabsTrigger value="b">B</TabsTrigger>
        </TabsList>
        <TabsContent value="a">one</TabsContent>
      </Tabs>,
    )
    const root = container.querySelector('[data-slot="tabs"]')!
    expect(root.getAttribute("data-orientation")).toBe("horizontal")
    expect(root.className).toContain("data-[orientation=horizontal]:flex-col")
    expect(root.querySelector('[data-slot="tabs-list"]')).not.toBeNull()
    expect(container.querySelector('[role="tab"][data-active]')).not.toBeNull()
  })

  it("Separator carries data-orientation", () => {
    const { container } = render(<Separator />)
    expect(container.querySelector("[data-orientation=horizontal]")).not.toBeNull()
    const v = render(<Separator orientation="vertical" />)
    expect(v.container.querySelector("[data-orientation=vertical]")).not.toBeNull()
  })

  it("Switch carries data-checked when on", () => {
    const { container } = render(<Switch defaultChecked />)
    expect(container.querySelector("[data-checked]")).not.toBeNull()
  })
})

// ── W7 ──────────────────────────────────────────────────────────────────────────────────────
// base-ui 1.x emits `data-open` / `data-closed`; it never emits Radix's `data-state`. The bare
// shorthand audit above skips the explicit `data-[state=open]:` form, so those selectors went
// unnoticed (select + dropdown-menu popups never animated; tooltip carried dead duplicates).
describe("W7 D1: no selector on an attribute base-ui does not emit", () => {
  const dir = __dirname
  const files = readdirSync(dir).filter((f) => f.endsWith(".tsx") && !f.endsWith(".test.tsx"))
  it.each(files)("%s has no data-[state=...] selector", (file) => {
    expect(readFileSync(path.join(dir, file), "utf8")).not.toMatch(/data-\[state=/)
  })

  it("an open Tooltip popup carries data-open and no data-state", async () => {
    render(
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger>t</TooltipTrigger>
          <TooltipContent>tip</TooltipContent>
        </Tooltip>
      </TooltipProvider>,
    )
    const t = screen.getByText("t")
    fireEvent.focus(t)
    fireEvent.pointerEnter(t)
    await screen.findByText("tip")
    const popup = document.querySelector('[data-slot="tooltip-content"]')!
    expect(popup.hasAttribute("data-open")).toBe(true)
    expect(popup.hasAttribute("data-state")).toBe(false)
  })
})

describe("W7 D3: Tabs orientation reaches base-ui", () => {
  const vertical = (
    <Tabs defaultValue="a" orientation="vertical">
      <TabsList>
        <TabsTrigger value="a">A</TabsTrigger>
        <TabsTrigger value="b">B</TabsTrigger>
      </TabsList>
      <TabsContent value="a">one</TabsContent>
    </Tabs>
  )
  it("vertical Tabs expose aria-orientation=vertical on the tablist", () => {
    render(vertical)
    expect(screen.getByRole("tablist").getAttribute("aria-orientation")).toBe("vertical")
  })
  it("vertical Tabs move focus with ArrowDown, not ArrowRight", async () => {
    render(vertical)
    const [a, b] = screen.getAllByRole("tab")
    a.focus()
    fireEvent.keyDown(a, { key: "ArrowDown" })
    await act(async () => { await new Promise((r) => setTimeout(r, 30)) })
    expect(document.activeElement).toBe(b)
    a.focus()
    fireEvent.keyDown(a, { key: "ArrowRight" })
    await act(async () => { await new Promise((r) => setTimeout(r, 30)) })
    expect(document.activeElement).toBe(a)
  })
  it("default Tabs stay horizontal (no aria-orientation)", () => {
    render(
      <Tabs defaultValue="a">
        <TabsList>
          <TabsTrigger value="a">A</TabsTrigger>
        </TabsList>
      </Tabs>,
    )
    expect(screen.getByRole("tablist").getAttribute("aria-orientation")).toBeNull()
  })
})

// ── token contrast for pairs scripts/check_ui_contrast.py does not walk (R5) ─────────────────
// The script only checks `<x>-foreground` on `<x>`. Variants that put a *plain* token (text-
// destructive) or an alpha fill under text are invisible to it. Resolve the classes a primitive
// really renders against globals.css and require WCAG AA.
type Rgb = [number, number, number]
const css = readFileSync(path.join(__dirname, "..", "..", "app", "globals.css"), "utf8").replace(
  /\/\*[\s\S]*?\*\//g,
  "",
)
const blockTokens = (sel: string): Record<string, string> => {
  const body = [...css.matchAll(new RegExp(`${sel}\\s*\\{([^}]*)\\}`, "g"))].map((m) => m[1]).join("\n")
  return Object.fromEntries([...body.matchAll(/--([\w-]+)\s*:\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]))
}
const THEMES = {
  light: blockTokens(":root"),
  dark: { ...blockTokens(":root"), ...blockTokens("\\.dark") },
}
const themeColors = new Set([...css.matchAll(/--color-([\w-]+):\s*hsl\(var\(--([\w-]+)\)\)/g)].map((m) => m[1]))
const rgbOf = (t: Record<string, string>, name: string): Rgb => {
  let v = t[name]
  for (let ref = /^var\(--([\w-]+)\)$/.exec(v); ref; ref = /^var\(--([\w-]+)\)$/.exec(v)) v = t[ref[1]]
  const [h, s, l] = v.match(/[\d.]+/g)!.map(Number)
  const a = (s / 100) * Math.min(l / 100, 1 - l / 100)
  const f = (n: number) => {
    const k = (n + h / 30) % 12
    return l / 100 - a * Math.max(-1, Math.min(k - 3, 9 - k, 1))
  }
  return [f(0), f(8), f(4)]
}
const lum = (c: Rgb) => {
  const [r, g, b] = c.map((x) => (x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4))
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}
const ratio = (a: Rgb, b: Rgb) => {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}
const over = (fg: Rgb, bg: Rgb, alpha: number) => fg.map((x, i) => x * alpha + bg[i] * (1 - alpha)) as Rgb
/** Every `text-<token>[/NN]` (any variant prefix) in a class string, as [token, alpha]. */
const textTokens = (cls: string) =>
  [...cls.matchAll(/(?:^|[\s:*])text-([a-z-]+)(?:\/(\d+))?(?=\s|$)/g)]
    .filter((m) => themeColors.has(m[1]))
    .map((m) => [m[1], m[2] ? Number(m[2]) / 100 : 1] as const)

describe("W7 D2: destructive text meets AA in both themes", () => {
  for (const theme of ["light", "dark"] as const) {
    const t = THEMES[theme]
    it(`Alert destructive text on card (${theme})`, () => {
      const cls = render(<Alert variant="destructive" />).container.firstElementChild!.className
      const found = textTokens(cls)
      expect(found.length).toBeGreaterThan(0)
      for (const [tok, alpha] of found) {
        const bg = rgbOf(t, "card")
        expect(ratio(over(rgbOf(t, tok), bg, alpha), bg), `${tok}/${alpha}`).toBeGreaterThanOrEqual(4.5)
      }
    })
    it(`Badge destructive text on its tinted fill (${theme})`, () => {
      const cls = render(<Badge variant="destructive">x</Badge>).container.firstElementChild!.className
      const fill = theme === "dark" ? /dark:bg-destructive\/(\d+)/ : /(?<![\w:-])bg-destructive\/(\d+)/
      const a = Number(fill.exec(cls)![1]) / 100
      const found = textTokens(cls)
      expect(found.length).toBeGreaterThan(0)
      for (const surface of ["card", "background"]) {
        const bg = over(rgbOf(t, "destructive"), rgbOf(t, surface), a)
        for (const [tok] of found) {
          expect(ratio(rgbOf(t, tok), bg), `${tok} on ${surface}`).toBeGreaterThanOrEqual(4.5)
        }
      }
    })
  }
})

// ── contract assertions for the primitives the composition layer relies on ────────────────────
describe("W7: Dialog contract (CommandPalette, ConfirmDialog, AppBar menu, ResponsivePanel)", () => {
  function Nested() {
    const [a, setA] = useState(false)
    const [b, setB] = useState(false)
    const ref = useRef<HTMLButtonElement>(null)
    return (
      <>
        <button onClick={() => setA(true)}>openA</button>
        <Dialog open={a} onOpenChange={setA}>
          <DialogContent initialFocus={ref}>
            <DialogTitle>A</DialogTitle>
            <Button ref={ref} onClick={() => setB(true)}>openB</Button>
            <Dialog open={b} onOpenChange={setB}>
              <DialogContent><DialogTitle>B</DialogTitle></DialogContent>
            </Dialog>
          </DialogContent>
        </Dialog>
      </>
    )
  }
  const tick = () => act(async () => { await new Promise((r) => setTimeout(r, 50)) })

  it("initialFocus lands on the ref, Escape peels one layer, focus returns to the opener", async () => {
    render(<Nested />)
    const opener = screen.getByText("openA")
    opener.focus()
    fireEvent.click(opener)
    await screen.findByText("A")
    await tick()
    expect(document.activeElement?.textContent).toBe("openB")
    fireEvent.click(screen.getByText("openB"))
    await screen.findByText("B")
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" })
    await tick()
    expect(screen.queryByText("B")).toBeNull()
    expect(screen.queryByText("A")).not.toBeNull()
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" })
    await tick()
    expect(screen.queryByText("A")).toBeNull()
    expect(document.activeElement).toBe(opener)
  })

  it("DialogContent is named by its title and has a labelled Close", async () => {
    render(<Dialog open><DialogContent><DialogTitle>T</DialogTitle></DialogContent></Dialog>)
    const d = await screen.findByRole("dialog")
    expect(document.getElementById(d.getAttribute("aria-labelledby")!)?.textContent).toBe("T")
    expect(screen.getByRole("button", { name: "Close" })).not.toBeNull()
  })

  it("DialogSheet keeps the caller aria-label and a labelled close button", async () => {
    render(<Dialog open><DialogSheet aria-label="Rail"><p>x</p></DialogSheet></Dialog>)
    expect((await screen.findByRole("dialog")).getAttribute("aria-label")).toBe("Rail")
    expect(screen.getByRole("button", { name: "Close panel" })).not.toBeNull()
  })
})

describe("W7: ScrollArea viewport plumbing (ConversationPane stick-to-bottom)", () => {
  it("viewportRef is the scrolling viewport, not the Root", () => {
    const viewportRef = createRef<HTMLDivElement>()
    const rootRef = createRef<HTMLDivElement>()
    const { container } = render(<ScrollArea ref={rootRef} viewportRef={viewportRef}><p>hi</p></ScrollArea>)
    expect(viewportRef.current).toBe(container.querySelector('[data-slot="scroll-area-viewport"]'))
    expect(rootRef.current).toBe(container.querySelector('[data-slot="scroll-area"]'))
    expect(viewportRef.current).not.toBe(rootRef.current)
  })
  it("onViewportScroll fires for a scroll on the viewport", () => {
    const onViewportScroll = vi.fn()
    const { container } = render(<ScrollArea onViewportScroll={onViewportScroll}><p>hi</p></ScrollArea>)
    fireEvent.scroll(container.querySelector('[data-slot="scroll-area-viewport"]')!)
    expect(onViewportScroll).toHaveBeenCalledTimes(1)
  })
})

describe("W7: Progress (MetricsPanel)", () => {
  const bar = (value: number | null) => render(<Progress value={value} aria-label="p" />).container
  const width = (c: HTMLElement) => c.querySelector<HTMLElement>('[data-slot="progress-indicator"]')!.style.width
  it("reports value and width", () => {
    const c = bar(40)
    expect(c.querySelector('[role="progressbar"]')!.getAttribute("aria-valuenow")).toBe("40")
    expect(width(c)).toBe("40%")
  })
  it("clamps above 100 and below 0", () => {
    expect(width(bar(150))).toBe("100%")
    expect(width(bar(-5))).toBe("0%")
  })
  it("NaN / null render as indeterminate, never as a fabricated value", () => {
    for (const v of [NaN, null]) {
      const el = bar(v).querySelector('[role="progressbar"]')!
      expect(el.hasAttribute("data-indeterminate")).toBe(true)
      expect(el.hasAttribute("aria-valuenow")).toBe(false)
    }
  })
})

describe("W7: form and status primitives", () => {
  it("Input forwards onChange with a real event (settings, ConnectionStatus)", () => {
    const onChange = vi.fn()
    render(<Input aria-label="i" type="password" onChange={onChange} />)
    fireEvent.change(screen.getByLabelText("i"), { target: { value: "x" } })
    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange.mock.calls[0][0].target.value).toBe("x")
  })
  it("Button forwards its ref and variant class", () => {
    const ref = createRef<HTMLButtonElement>()
    render(<Button ref={ref} variant="destructive">go</Button>)
    expect(ref.current).toBe(screen.getByRole("button", { name: "go" }))
    expect(ref.current!.className).toContain("bg-destructive")
  })
  it("Alert is role=alert", () => {
    render(<Alert>boom</Alert>)
    expect(screen.getByRole("alert").textContent).toBe("boom")
  })
})

// [UNK] browser-only (no browser host, plan section 8.2): layout and paint cannot be asserted in jsdom.
//  - Textarea `field-sizing-content` auto-grow; ScrollArea `size-full` viewport height chain
//  - DialogContent `-translate-y-0` override in AppBar (tailwind-merge group resolution, real CSS)
//  - focus-visible rings, pointer-coarse 44 px targets (e2e at 375 px, not runnable here)
//  - Card / Skeleton / Label / Separator layout: pure class wrappers, no behaviour to assert
// Primitives with NO consumer in the composition layer (DEAD for W7's exit criterion): Select,
// DropdownMenu, Avatar, Switch (asserted above), Tooltip/TooltipContent (only the provider is mounted).
