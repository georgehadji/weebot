---
status: reference
date: 2026-10-31
---

# Wave 6 - Shell, Providers & Navigation

Execution record for W6 of [`tasks/specs/ui_defect_hunt_v71_execution_plan.md`](../specs/ui_defect_hunt_v71_execution_plan.md).
Threats **T5, T6, T7**; classes **C1, C2, C3, C7, C9, C10**. Seeds **D6, D14**. Format follows
[W7](ui_defect_hunt_w7_primitives.md). **No ceiling changed, no dependency added, no lint rule added.**

Every `[VF]` came from running code (vitest 3.2.7, jsdom, React 19, `@base-ui/react` 1.8.0, fake `matchMedia`,
mocked `next/navigation` and `next/link`). No browser: layout, paint and real focus ring behaviour are `[UNK]`.

---

## Phase 0-WAVE - scope, budget

| | |
|---|---|
| **Surface** | `components/shell/{AppShell,AppBar,ConsoleShell,SessionRail,ResponsivePanel}.tsx`, `providers/{Toast,Theme,Shell,Announcer}Provider.tsx`, `components/command/CommandPalette.tsx`, `lib/commands/registry.ts`, `hooks/{useShellSlots,useRegisterCommands}.ts`, `app/layout.tsx`, `app/error.tsx` |
| **Budget** | <=15 / <=10 / <=5 |
| **Spent** | 15 generated, 10 investigated, **5 fixed**, 3 more VERIFIED but unfixed (fix budget), 3 cleared, 5 not investigated |

---

## Phase 1 - region map

| R | Region | Layer | Classes | Reachability | Blast | Owner |
|---|---|---|---|---|---|---|
| R1 | `useShellSlots` set/clear + `ShellProvider` slots | hooks/providers | C3, C7 | REACHABLE: every route | SYSTEM (title, h1, dock) | `ShellProvider` |
| R2 | `useRegisterCommands` / `commandRegistry` | hooks/lib | C3, C9 | REACHABLE, only registrar is `AppShell` | MODULE | registry |
| R3 | `CommandPalette` highlight index | components | C1 | GUARDED today (see 3.2) | LOCAL | component |
| R4 | `ToastProvider` id + hold timer | providers | C5, C8, C10 | REACHABLE: `RunControls`, `sessions/page` | SYSTEM (error reporting) | provider |
| R5 | `ThemeProvider` vs `THEME_INIT_SCRIPT` | providers/app | C6, C10 | REACHABLE: every load | SYSTEM | provider |
| R6 | `ResponsivePanel` sheet, `AppBar` menu, `ConsoleShell` path-keyed open state | components | C7, T7 | REACHABLE below `md`/`lg` | MODULE | component |
| R7 | `AppShell` landmarks, skip link, shortcuts; `app/error.tsx` | components/app | C9, C10 | REACHABLE: every route | SYSTEM | `AppShell` |

### Atomic assertions

1. **`[VF]`** The shell had **zero direct tests**: `AppShell`, `AppBar`, `ConsoleShell`, `ResponsivePanel`, `CommandPalette`, `ThemeProvider`, `useShellSlots` were never rendered by any test (only `SessionRail` and `ToastProvider` had one).
2. **`[VF]`** The one-`<main>` invariant is held by `lint_ui_debt` (`ui_main_landmarks` = 1) but only as a source-text count; nothing asserted the rendered DOM, the skip-link target or the heading count.
3. **`[VF]`** One `<h1>` per route is held by convention: console pages fill the bar's `<h1>` through the slot, the five standalone pages own theirs, and nothing stops a page doing both. `app/error.tsx` rendered neither.
4. **`[VF]`** This Node's experimental `localStorage` is absent under jsdom (`window.localStorage` is `undefined`), so any storage-dependent provider test must stub it. Recorded for later waves.

---

## Phase 2 - candidates (15 generated)

| ID | Location | Property claimed violated | Class | Innocence path |
|---|---|---|---|---|
| G1 | `useShellSlots.ts:9-12` | an outgoing page's clear never erases the incoming page's slots | C3 | React runs unmount cleanups before the new commit's effects |
| G2 | `useRegisterCommands.ts:9-13` | registered `run` closures stay current (id-only deps) | C3 | every registrar passes stable callbacks (plan O1) |
| G3 (D14) | `CommandPalette.tsx:54,80-93` | the highlight addresses an existing option | C1 | the command set cannot shrink while open |
| G4 | `AppShell.tsx:23` | a shortcut shown in the palette exists | C10 | a global handler elsewhere binds it |
| G5 (D6) | `ToastProvider.tsx:60` | a toast cannot throw on a capability gap | C5, C8 | the app is only served from localhost/HTTPS |
| G6 | `ToastProvider.tsx:117-120` | a toast holds still while hovered **or** focused | C7 | one flag is equivalent |
| G7 | `ToastProvider.tsx` | persistent error toasts are bounded | C5 | no caller loops |
| G8 | `ThemeProvider.tsx:28` | first client render equals the server render | C6, C10 | `suppressHydrationWarning` covers it |
| G9 | `ThemeProvider` vs `layout.tsx` init script | both agree on garbage / missing storage | C10 | both default dark |
| G10 | `ResponsivePanel.tsx` + `Dialog` | closing a sheet returns focus to its opener | T7 | base-ui focus manager owns it |
| G11 | `AppBar.tsx:109`, `ConsoleShell.tsx:48-61` | activating a link in a modal dismisses it, **including to the current path** | C7, T7 | navigation always changes the path |
| G12 | `app/error.tsx:25` | exactly one `<h1>` on every route | C9 | the bar supplies it |
| G13 | `AppShell.tsx` | one `<main>`, skip link first and targeting it | C9 | enforced by lint |
| G14 | `AnnouncerProvider.tsx:30` | the same sentence twice in a row re-announces | C10 | zero-width toggle |
| G15 | `ResponsivePanel.tsx` / `ConsoleShell` | widening then narrowing the viewport does not reopen a closed-by-resize sheet | C7 | restoring is acceptable |

---

## Phase 3 - proof of defect

Tests: `components/shell/shell.invariants.test.tsx`, `components/command/CommandPalette.test.tsx`,
`providers/ToastProvider.w6.test.tsx`, `providers/ThemeProvider.test.tsx`.

### 3.1 G5 / D6 - `crypto.randomUUID()` is unguarded: every toast throws on a plain-http origin

`vi.stubGlobal("crypto", {})` (the shape of a non-secure context) then fire a toast:

```
TypeError: crypto.randomUUID is not a function   src/providers/ToastProvider.tsx:60
```

3 of 4 new tests failed at HEAD (`{}` crypto, `undefined` crypto, two toasts keep distinct ids); the 4th (real crypto) passed.
**Innocence attempt.** Guard: none (the same call in `useComposer.ts:31` is guarded, this one is not). Reachability: a self-hosted
console opened as `http://<lan-ip>:3000` is a non-secure context, where `randomUUID` is undefined; no doc restricts the origin. The
throw happens inside the caller's event handler, so the error toast ("Failed to interrupt session") never appears: the user sees
nothing at the moment something is already wrong. Owner: the provider. No defence holds.
**Verdict: CONFIRMED, MEDIUM.**

### 3.2 G3 / D14 - highlight index is not clamped when the registry shrinks

Register a, b, c; ArrowDown twice (highlight c); unregister b and c:

```
expected null to be 'command-palette-option-a'              (aria-activedescendant)
expected 'command-palette-option-b' to be '...-a'           (ArrowUp from a stale index 2)
```

Mechanism: `active = filtered[activeIndex]` with `activeIndex` clamped only inside the key handlers, so a shrunk list leaves
`active` undefined: no `aria-selected` option, and Enter does nothing. 2 of 5 tests failed at HEAD.
**Innocence attempt.** Reachability: only `AppShell` registers commands, at the root, never unmounting; `when` is unused. So the
registry cannot shrink while the palette is open **today** (a page that registers commands and unmounts on browser-Back under an open
palette would trigger it). Guard defence lowers severity, does not clear the property.
**Verdict: CONFIRMED, LOW (latent).** Fixed then reverted for budget (see 5).

### 3.3 G4 - the palette advertises `⌘N` for "New conversation" and no handler exists

Walk every `⌘<letter>` label in the open palette, dispatch that chord, expect the command to run:

```
New conversation⌘N advertises a shortcut with no handler: expected "spy" to be called at least once
```

**Innocence attempt.** The only global key handler in the tree is `AppShell`'s Ctrl/Cmd+K (`grep keydown`). Cmd/Ctrl+N is also
reserved by the browser (new window), so binding it would be wrong; the defect is the label, not a missing handler.
**Verdict: CONFIRMED, LOW (C10: an indicator asserting something the code never provides).**

### 3.4 G11 - a link to the current path leaves the menu / sheet open

Mock `usePathname` constant, open the menu (or the rail sheet), activate a link whose `href` equals the current path:

```
the menu closes when the operator picks the page they are already on:   expected <div data-open ...> to be null
New session from the menu at '/' closes it:                              expected <div data-open ...> to be null
the rail sheet closes when a rail link is activated at the same path:    expected <div data-open ...> to be null
```

Mechanism: both open states are keyed to a path (`menuPath === pathname`, `railPath === pathname`) so that *navigation* closes them
without an effect. A same-path activation does not change the path, so nothing closes. Concretely on mobile at `/`, tapping **New
session** in the menu (or the active session in the rail) does nothing visible; the modal stays up over the page.
**Innocence attempt.** Guard: none for the same-path case. Reachability: `AppBar` below `lg`, `ConsoleShell` below `md`; the comment
in `AppBar` states the intent ("a link in the menu closes it"), which the same-path case violates. Owner: the two components that
own the open state. Not the Dialog primitive (it cannot know a click was a link).
**Verdict: CONFIRMED, MEDIUM (T7), two sites.**

### 3.5 G12 - `app/error.tsx` renders `<h2>`, so the route has no `<h1>`

`RouteError` inside the shell: `Unable to find an accessible element with the role "heading"` (level 1). A crashed page unmounts, its
slot clear removes the bar's `<h1>`, and the boundary supplies only an `<h2>`. A screen-reader user lands on a page with no h1 at the
moment a crash happens.
**Innocence attempt.** The bar supplies the h1 only while a page holds the slot; the crashing page's cleanup has run. No defence.
**Verdict: CONFIRMED, LOW (C9, the plan's `<h1>` invariant).**

### 3.6 G6 - a toast held by focus is released when the pointer leaves

`mouseenter`, `focus` on the action button, `mouseleave`, advance 60 s: the toast is dismissed while keyboard focus is inside it.
The comment says "hold still while hovered **or** focused"; one boolean cannot express OR (the last event wins).
**Innocence attempt.** Only non-error toasts auto-dismiss (errors have no timer), and the case needs hover then focus then pointer
exit. Reachable by a mouse user who tabs into a toast. **Verdict: CONFIRMED, LOW.** Fixed then reverted for budget.

### 3.7 G8 - a stored light theme fails hydration (`R5`)

`renderToString` with `window` undefined (the server), then `hydrateRoot` with `localStorage.weebot_theme = "light"`:

```
Hydration failed because the server rendered text didn't match the client. As a result this tree will be regenerated on the client.
```

Mechanism: `useState(readStoredTheme)` reads storage on the **first client render**; the server cannot, so it renders `"dark"`.
`suppressHydrationWarning` on `<html>` only covers that element's own attributes, not the theme-dependent `AppBar` icon and
`aria-label`. React discards the server tree and re-renders from the root, which remounts every provider below `ThemeProvider`
(including `EventStreamProvider`: sockets reopen on every load for a light-theme user). Dark and unset storage hydrate cleanly
(3 boundary tests pass).
**Innocence attempt.** Guard: none; reachability: every load for every light-theme user; owner: `ThemeProvider`. No defence holds.
**Verdict: CONFIRMED, MEDIUM.** Not fixed: the correct fix is larger than the 15-line cap (see 5).

### 3.8 Cleared (code-innocent)

| ID | Trigger | Outcome |
|---|---|---|
| G1 | swap `<Page title="A">` for `<Page title="B">` in one commit; unmount a page | incoming title wins; unmount leaves no h1. CLEARED, now asserted (P6) |
| G10 | focus the opener, open the rail sheet, click Close panel, wait | `document.activeElement` is the opener. CLEARED, now asserted (P5) |
| G13 | render `AppShell` | one `<main id=main-content tabindex=-1>`, skip link `href` equals that id and is the first tab stop; one h1 whether the bar or the page supplies it. CLEARED, now asserted (P1, P2) |

---

## Phase 4 - inventory

| Candidate | Trigger | Innocence | Evidence | User-visible consequence | Status |
|---|---|---|---|---|---|
| G5 / D6 toast id | RTL, crypto stubbed | none holds | `[VF]` | on `http://<lan-ip>`, error toasts never appear | **VERIFIED, FIXED** (MEDIUM) |
| G11 same-path link | RTL, 3 sites | none holds | `[VF]` | mobile: tapping the current page does nothing, modal stays | **VERIFIED, FIXED** (MEDIUM, 2 sites) |
| G12 error h1 | RTL | none holds | `[VF]` | crash page has no h1 | **VERIFIED, FIXED** (LOW) |
| G4 `⌘N` label | RTL, chord walk | label only | `[VF]` | palette shows a shortcut that does nothing | **VERIFIED, FIXED** (LOW) |
| G8 theme hydration | `renderToString` + `hydrateRoot` | none holds | `[VF]` | light theme: hydration error, whole tree regenerated | **VERIFIED, NOT FIXED** (MEDIUM, cap) |
| G3 / D14 highlight | RTL, registry shrink | latent (no shrinker today) | `[VF]` | none today | **VERIFIED, NOT FIXED** (LOW, budget) |
| G6 toast hold | RTL, fake timers | rare path | `[VF]` | toast vanishes under keyboard focus | **VERIFIED, NOT FIXED** (LOW, budget) |
| G1 slot ordering | RTL | React ordering | `[VF]` | n/a | CLEARED |
| G10 focus return | RTL | base-ui | `[VF]` | n/a | CLEARED |
| G13 landmarks | RTL | lint + structure | `[VF]` | n/a | CLEARED |
| G2 id-only deps | none run | plan O1 (stable callbacks) | `[HYP]` | none today | NOT INVESTIGATED (OBSERVATION; also: two registrars of one id would let one's unmount delete the other's command) |
| G7 unbounded error toasts | none run | two callers, neither loops | `[HYP]` | none seen | NOT INVESTIGATED |
| G9 init script vs provider | read | both map non-`light` to dark | `[HYP]` | n/a | NOT INVESTIGATED (reads equal) |
| G14 announcer repeat | read | zero-width toggle flips text node | `[HYP]` | n/a | NOT INVESTIGATED |
| G15 breakpoint reopen | read | path-keyed state survives the Dialog unmount | `[HYP]` | sheet may reappear after widen-then-narrow | NOT INVESTIGATED `[UNK]` |

---

## Phase 5 - fix design

Placement follows ownership: each fix is in the component or provider that owns the violated property.

| Defect | Diff |
|---|---|
| G5 / D6 | `ToastProvider.tsx`: `useRef` counter, id is `` `toast-${nextId.current++}` `` instead of `crypto.randomUUID()` (ids only need uniqueness inside one provider). +`useRef` import, 2 lines. |
| G11 | `AppBar.tsx`: `onClick={(e) => (e.target as Element).closest("a") && setMenuPath(null)}` on the menu `DialogContent`. `ResponsivePanel.tsx`: same handler on `DialogSheet`, calling `onOpenChange(false)`. One handler per owner; the menu's theme **button** is not an anchor and still keeps the menu open (asserted). Cross-file in letter, one idiom, no shared state. |
| G12 | `app/error.tsx`: `<h2>` to `<h1>`. |
| G4 | `AppShell.tsx`: drop `shortcut: "⌘N"` from "New conversation". |

Constraint notes: G11 touches two components (flagged, as W7 did for D1/D2). Public props unchanged.

### Proposed, not applied (fix budget spent)

| Defect | Minimal fix | Why not applied |
|---|---|---|
| G3 / D14 | In `PaletteBody`: `const index = Math.min(activeIndex, filtered.length - 1); const active = filtered[index];` and use `index` in the two arrow handlers and in `aria-selected`/class. ~7 lines. Written, passed 5/5, reverted. | 6th verified defect; ceiling is 5 and it is latent |
| G6 | `ToastItem`: replace `held` with `hovered` and `focused` flags, `held = hovered \|\| focused`. ~6 lines. Written, passed, reverted. | 7th verified defect, LOW |
| G8 | `[REQUIRES HUMAN REVIEW: exceeds 15-line cap]`. MINIMAL (masks): `useState<Theme>("dark")` plus a mount effect that reads storage; this flashes the wrong theme for one frame and the existing persist effect overwrites storage with `"dark"` on that first commit unless persistence moves into `setTheme`/`toggleTheme`. ARCHITECTURAL (recommended): `useSyncExternalStore(subscribe, () => document.documentElement.classList.contains("dark") ? "dark" : "light", () => "dark")`, with the pre-hydration script as the single source of truth and the provider only writing the class and storage on user action. ~20 lines, one provider, same idiom as `useMediaQuery`. | over the cap; needs a decision on who owns the theme (O6) |

The three proof tests for these are committed as `it.fails(...)`: green while the defect exists, red the moment it is fixed, with a
comment telling the next person to flip them to `it`.

### Self-review (RAR)

| # | Vector | Verdict |
|---|---|---|
| 1 | Boundary | zero toasts / two toasts distinct ids; menu theme button and a click inside the sheet away from a link do not close; default/empty storage hydrate cleanly `[VF]` |
| 2 | Invalid input | `crypto` missing or `{}`; unrecognised stored theme falls back to dark `[VF]` |
| 3 | State | focus return after close; slot swap and unmount `[VF]`. StrictMode double effect not exercised `[UNK]` |
| 4 | Regression | full run below; `lint_ui_debt` six counters at ceiling, contrast 58 pairs `[VF]` |
| 5 | Concurrency | n/a for the fixes (synchronous handlers, a counter) |
| 6 | New defect | `closest("a")` on a nested svg click resolves through the anchor; a click on a non-anchor child of the sheet does not close (asserted) `[VF]` |
| 7 | Architecture | no `fetch`, no new global, no raw colour, one `<main>` and one `<h1>` preserved `[VF]` |
| 8 | Paradigm | ids stay provider-local; handlers reuse the existing path-keyed open state |

`FIX HOLDS [VF]` for G5, G11, G12, G4.

---

## Phase 7 - tests

All colocated; no new harness (the existing mocking idiom of `SessionRail.test.tsx`, plus a fake `matchMedia`).

| File | Test | Role |
|---|---|---|
| `providers/ToastProvider.w6.test.tsx` | randomUUID `{}` / missing / two distinct ids | proof of D6 (3 failed at HEAD) |
| | randomUUID present | no-regression |
| | hold: focus survives pointer leave (`it.fails`) | proof of G6 (fails at HEAD) |
| | hold: focus moving inside the toast, then leaving | boundary (passes) |
| `components/command/CommandPalette.test.tsx` | shrink under highlight, ArrowUp after shrink (`it.fails`) | proof of D14 (2 failed at HEAD) |
| | ArrowDown past end, empty registry, typing resets highlight | boundary / no-regression |
| `components/shell/shell.invariants.test.tsx` | P1 one `<main>`, skip link first and targets it | exit criterion |
| | P2 one h1 (slot / own / error boundary) | exit criterion; error case failed at HEAD |
| | P3 every `⌘x` label fires; Ctrl/Cmd+K toggles; palette runs and closes | G4 proof (failed at HEAD) + no-regression |
| | P4 menu same path, menu "New session", rail same path | G11 proof (3 failed at HEAD) |
| | P4 theme button and in-sheet non-link click keep it open | no-regression |
| | P5 focus returns to the opener | exit criterion (G10 cleared) |
| | P6 slot swap, slot cleared on unmount | exit criterion (G1 cleared) |
| `providers/ThemeProvider.test.tsx` | stored light (`it.fails`) | proof of G8 (fails at HEAD) |
| | stored dark, unset, garbage hydrate cleanly | boundary |

---

## Phase 8 - verdict

### Process checks

| Check | Status |
|---|---|
| Defect VERIFIED (trigger fired, no innocence defence) | yes, x7 (4 fixed, 3 open) |
| Fix <=15 lines | yes for the four fixes (17 changed lines total across 5 files incl. comments) |
| Fix <=1 function | no for G11 (two components), noted |
| Proof + boundary + no-regression tests | yes |
| Phase 0 census complete | yes |
| Fix in the invariant-owning layer | yes |

### Engineering checks

| Check | Status |
|---|---|
| All vectors FIX HOLDS | yes |
| Regression risk | LOW |
| Fix causal, not symptomatic | yes (G4 removes a false claim rather than inventing a handler) |
| Dependency-rule / abstraction bypass | none |
| Pattern introduced | none |

Routing: **ACCEPT** for G5, G11, G12, G4. **PARTIAL** for the wave: three VERIFIED defects (G8, G3, G6) are unfixed because the
5-fix ceiling was reached; five candidates were not investigated.

(Count note: the four fixed defects touch five sites: G11 is two. The budget was spent as five fixes.)

### Exit criterion

"Shell-level invariants (one `<main>`, one `<h1>`, skip link, focus return) restated as properties with a test each": **met**.

| Property | Test | Result |
|---|---|---|
| P1 exactly one `<main>`; skip link first tab stop, `href` = `main#id`, `main` focusable (`tabindex=-1`) | `shell.invariants` P1 | holds |
| P2 exactly one `<h1>`: slot title XOR page-owned XOR error boundary | `shell.invariants` P2 (x3) | holds after G12 fix |
| P3 a displayed shortcut exists | `shell.invariants` P3 | holds after G4 fix |
| P4 a link in a modal dismisses it | `shell.invariants` P4 | holds after G11 fix |
| P5 focus returns to the opener on sheet close | `shell.invariants` P5 | holds |
| P6 slots belong to the mounted page | `shell.invariants` P6 | holds |

`[UNK]` (needs a browser): visible focus ring on the skip link (`focus:not-sr-only`), real tab order across the portalled sheet,
whether `md` crossover hides the inline rail correctly, focus return under real animation timing, `h-dvh` on mobile browser chrome.

### Coverage statement

```
Surface audited:            R1 slots, R3 palette index, R4 toast id/hold, R5 theme hydration, R6 sheet/menu
                            dismissal and focus return, R7 landmarks, skip link, shortcuts, error boundary
Surface NOT audited:        R2 useRegisterCommands closure staleness (plan O1, not run), AnnouncerProvider,
                            SessionRail beyond its existing test, ConsoleShell breakpoint-crossing,
                            layout.tsx provider order under StrictMode; layout/paint of everything (no browser)
Defect classes covered:     C1, C3, C5, C6, C7, C9, C10 (C2 only via the StrictMode-free slot swap; the shell
                            owns no sockets or timers except the toast timer, which has correct cleanup)
Architecture census basis:  VF (source read, lint_ui_debt, rendered DOM)
Confirmed defects:          CRITICAL 0 / HIGH 0 / MEDIUM 3 (G5, G11, G8) / LOW 4 (G12, G4, G3, G6)
                            fixed 5 sites (G5, G11 x2, G12, G4); open 3 (G8, G3, G6)
Cleared (innocent):         3     Re-attributed to owner: 0     Observations: 3 (G2, G7, G9 left as HYP)
Residual UNKNOWN:           G15 (resize reopens a sheet), StrictMode double mount of ThemeProvider/ToastProvider,
                            every browser-only property in the exit-criterion table
Clean-claim scope:          "Regions R1, R7 (landmarks) and the P5 focus-return path were audited for classes
                            C3, C7, C9 and no VERIFIED defect was found there." Not "the shell is bug-free".
Highest-value next hunt:    ThemeProvider/layout (G8 fix plus O6: two writers of the theme class) and the
                            breakpoint-crossing behaviour of ResponsivePanel (G15), the latter needs a browser.
```

---

## Deferred / outside W6's surface

- `app/sessions/page.test.tsx` (W5) failed in the shared tree during an earlier full run (green in the final run): "a session deleted on the page leaves the rail once its deleted presence frame lands (W5 D10)". W5's in-progress file, not touched.
- Observation for W7/W8: `AnnouncerProvider`'s header claims "nothing else on the page is a live region", but toasts (`role=status`/`alert`) and `SessionRail`'s "No sessions match" (`role=status`) are live regions too. Doc claim, not a defect.
- `app/error.tsx` and any crash above it: there is no `global-error.tsx`, so a throw in a root provider shows Next's bare page. Not hunted; owner `app/`.
- `console.error` in `app/error.tsx` is the O5 observation (no logger); unchanged.

## Uncertainty acknowledgment

**Finding most likely to be a false positive.** G4: it is a label, not behaviour; filed LOW. G3/D14 is likewise real but unreachable
today.

**Real defect most likely missed.** Browser-only behaviour of the sheet/menu (focus trap against the portalled rail, `md`
crossover), and StrictMode double-mount of the providers.

**What requires runtime validation.** Whether G8's full-tree regeneration really remounts `EventStreamProvider` in production
builds (React regenerates to the nearest Suspense boundary; none is declared in `layout.tsx`), and the real origins users open the
console from (decides how often G5 bites).

## Commands

```bash
cd weebot-ui
npx vitest run src/components/shell src/components/command src/providers   # 7 files, 42 tests (3 `it.fails` pins)
npx vitest run                                                             # 36 files, 271 tests pass (final run; an earlier run had one W5 failure in sessions/page.test.tsx, since fixed by W5)
npx tsc --noEmit                                                           # 0 errors
npm run lint                                                               # ESLint: no issues found
cd ..
.venv/Scripts/python scripts/lint_ui_debt.py                               # 6 counters at ceiling
.venv/Scripts/python scripts/check_ui_contrast.py                          # 58 token pairs meet 4.5:1
```
