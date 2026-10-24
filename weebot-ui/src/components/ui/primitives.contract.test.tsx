/**
 * Contract between base-ui and the class selectors in components/ui.
 *
 * base-ui emits `data-orientation="horizontal"`, `data-active`, `data-checked` ...; the shadcn
 * template once selected on `data-horizontal:`, which never matched and laid Tabs out as a row.
 * These tests fail when a selector names an attribute the primitive does not emit.
 */
import { readdirSync, readFileSync } from "node:fs"
import path from "node:path"
import { render } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { Separator } from "./separator"
import { Switch } from "./switch"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./tabs"

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
