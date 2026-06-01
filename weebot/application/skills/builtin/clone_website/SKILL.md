---
name: clone_website
description: Clone any website pixel-perfect into the weebot-ui Next.js app. Reverse-engineers design tokens, CSS, assets, and interactions then rebuilds each section as a React component. Use when user says "clone", "replicate", "rebuild", "copy this site", or provides a URL to replicate.
metadata:
  emoji: 🌐
  env: []
  homepage: https://github.com/JCodesMore/ai-website-cloner-template
---

# Clone Website

You are a **foreman**. Your job is to inspect the target site, write detailed section specs to files, then dispatch specialist builder sub-agents in parallel. You do not build — you direct.

## Target

The target URL(s) are provided as the task description. Normalize each URL and clone exactly what is visible at that URL.

**Default fidelity**: pixel-perfect — exact colors, spacing, typography, animations.
**In scope**: visual layout, component structure, interactions, responsive design, mock data.
**Out of scope**: real backend/database, authentication, real-time features.

---

## Pre-Flight (do these sequentially before anything else)

1. **Verify browser tool**: Confirm `browser_inspector` and `advanced_browser` are in your tool list.
2. **Verify scaffold**: Confirm `weebot-ui/` exists and contains `package.json`. If missing, tell the user to set it up first.
3. **Create output directories**:
   - `tasks/specs/<hostname>/` — for spec files
   - `weebot-ui/src/components/` — for built components
   - `weebot-ui/src/styles/` — for design tokens CSS

---

## Phase 1 — Foundation Extraction (sequential, blocks everything else)

Use `advanced_browser` to navigate to the target URL, then:

1. **Extract design tokens**:
   ```
   browser_inspector(action="extract_design_tokens")
   ```
   Write the result to `tasks/specs/<hostname>/design_tokens.json`.

2. **Get page structure**:
   ```
   browser_inspector(action="get_structure")
   ```
   Write the section manifest to `tasks/specs/<hostname>/sections.json`.

3. **Take a reference screenshot**:
   ```
   browser_inspector(action="screenshot")
   ```
   Save the base64 PNG reference as `docs/design-references/<hostname>/original.png`.

4. **Write the CSS tokens file** `weebot-ui/src/styles/tokens.css`:
   - Convert all extracted CSS custom properties to `:root { ... }` declarations.
   - Add computed fallback values for font-family, font-size, line-height, color, background-color.

**STOP here.** Nothing is built until the foundation exists.

---

## Phase 2 — Per-Section Spec Writing (sequential, one section at a time)

For each section identified in `sections.json`:

1. **Inspect the section root element**:
   ```
   browser_inspector(action="inspect_element", selector="<section-css-selector>")
   ```

2. **Enumerate its assets**:
   ```
   browser_inspector(action="enumerate_assets")
   ```

3. **Write the spec file** to `tasks/specs/<hostname>/<section_name>.md` using `file_editor`. Include:
   - Section name and CSS selector
   - Exact computed CSS values (from inspect_element — do NOT approximate)
   - Full asset list with URLs and dimensions
   - Text content
   - Layout structure (flex/grid properties, spacing)
   - Interactive behaviors: hover states, scroll triggers, animation transitions, responsive breakpoints
   - Reference to any assets in `tasks/specs/<hostname>/assets/`

**Complexity budget**: If a spec file would exceed ~150 lines, split into sub-sections (e.g., `hero_background.md`, `hero_content.md`). This is a mechanical rule — do not override it.

---

## Phase 3 — Parallel Build Dispatch

Once ALL spec files are written, use `dispatch_parallel_tasks` to build sections concurrently:

```json
{
  "tasks": [
    {
      "task_id": "build-hero",
      "description": "Build the Hero section as a React component in weebot-ui/src/components/Hero/. Read the full spec from tasks/specs/<hostname>/hero.md before writing any code. Use only exact CSS values from the spec — no approximations. Export as Hero.tsx with accompanying Hero.css.",
      "context": "Spec file: tasks/specs/<hostname>/hero.md\nTokens: tasks/specs/<hostname>/design_tokens.json"
    },
    {
      "task_id": "build-nav",
      "description": "Build the Navigation component...",
      "context": "Spec file: tasks/specs/<hostname>/nav.md"
    }
  ],
  "max_concurrency": 3
}
```

**Each sub-agent task description must**:
- Reference its spec file path explicitly
- Reference `tasks/specs/<hostname>/design_tokens.json`
- Output to `weebot-ui/src/components/<SectionName>/`
- Export a named React component

---

## Phase 4 — Assembly and Verification

After all builders complete:

1. **Update `weebot-ui/src/app/page.tsx`** to import and render all components in visual order (top to bottom as they appear on the original site).

2. **Run the build**:
   ```
   bash(command="cd weebot-ui && npm run build")
   ```
   Fix any TypeScript or import errors before proceeding.

3. **Take a result screenshot** with `browser_inspector(action="screenshot")` after starting the dev server.

4. **Compare**: note any obvious differences from the reference screenshot and add correction steps to the plan if needed.

---

## Guiding Principles

These rules override any shortcuts:

1. **Foundation first** — no component is built until `tokens.css` exists.
2. **Completeness beats speed** — every builder sub-agent receives exact CSS values, not approximations. If a value is missing from the spec, go back and extract it rather than guessing.
3. **Appearance AND behavior** — capture hover states, scroll triggers, animation transitions, not just static CSS. A clone that looks right but feels dead is incomplete.
4. **Real content** — use actual text, download actual images. Never use placeholder text or lorem ipsum.
5. **Layered assets** — a section that looks like one image is often multiple layers (background gradient + foreground PNG + overlay SVG). Inspect the full DOM tree to enumerate ALL layers.
6. **Complexity budget** — spec > 150 lines = split. This is mechanical. Do not override it.
