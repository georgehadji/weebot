---
status: reference
date: 2026-10-31
---

# Wave 7 - Primitives & Design Contracts

Execution record for W7 of [`tasks/specs/ui_defect_hunt_v71_execution_plan.md`](../specs/ui_defect_hunt_v71_execution_plan.md).
Threat **T7** (interaction / a11y); classes **C8** (contract / dependency), **C9** (architecture-conformance, tokens).
Structural wave: no seeds (plan section 7). Instruments `scripts/lint_ui_debt.py` and `scripts/check_ui_contrast.py`
were read and run, not changed. **No ceiling changed.**

Every `[VF]` below came from running code (vitest 3.2.7, jsdom, `@base-ui/react` 1.8.0). Commands: section 8.

---

## Phase 0-WAVE - scope, budget

| | |
|---|---|
| **Surface** | `weebot-ui/src/components/ui/*` (18 files), `primitives.contract.test.tsx`, `src/app/globals.css` |
| **Baseline** | `tsc` 0, `eslint` clean, vitest 28 files, `lint_ui_debt` 6 counters at ceiling, contrast 58 pairs >= 4.5 |
| **Budget** | <=15 / <=10 / <=5 |
| **Spent** | 13 generated, 11 investigated, **3 fixed**, 8 cleared, 1 observation, 1 dead-and-unexercised |
| **Browser** | Unavailable (plan 8.2). Anything about layout or paint is `[UNK]`, listed in the exit-criterion table. |

---

## Phase 1 - region map

Who actually uses a primitive (grep of `@/components/ui/*` imports outside `ui/`):

| Primitive | Consumers in the composition layer |
|---|---|
| button (17), card (9), badge (7) | everywhere |
| dialog | `CommandPalette`, `ConfirmDialog`, `AppBar` menu (`DialogContent`); `ResponsivePanel` (`DialogSheet`) |
| tabs | `ops`, `behavior`, `Dock` |
| skeleton | `ops`, `StateView`, `LazyPlanVisualizer` |
| scroll-area | `ConversationPane` (`viewportRef`), `ops` |
| input / textarea / label / separator | `settings`, `ConnectionStatus`, `Composer` |
| progress | `MetricsPanel` |
| alert | `ConnectionStatus` (destructive) |
| tooltip | only `TooltipProvider` in `app/layout.tsx` |
| **select, dropdown-menu, avatar, switch** | **none** |

| R | Region | Layer | Classes | Reachability | Blast | Owner |
|---|---|---|---|---|---|---|
| R1 | contract test + every `data-*`/`aria-*` selector in `ui/*` | components/ui | C8 | REACHABLE (all primitives) | MODULE | the wrapper + base-ui |
| R2 | `dialog.tsx` (`DialogContent`, `DialogSheet`) nesting, focus, naming | components/ui | C8, T7 | REACHABLE: palette, confirm, menu, sheets | SYSTEM (every modal) | base-ui via wrapper |
| R3 | `select.tsx`, `dropdown-menu.tsx` keyboard | components/ui | C8 | **DEAD** (no consumer) | LOCAL | base-ui |
| R4 | `scroll-area.tsx` viewport ref plumbing | components/ui | C8 | REACHABLE: `/sessions/[id]` timeline | MODULE | wrapper |
| R5 | `globals.css` tokens vs. the states the contrast script does not walk | globals.css | C9, T7 | REACHABLE: dark theme is the default | EXTERNALLY-VISIBLE (what the user reads) | CSS tokens + primitive classes |

### Atomic assertions about the map

1. **`[VF]`** The contract test audited only the *bare* `data-xxx:` shorthand. The explicit `data-[name=value]:` form, which is where `data-[state=open]` lives, was invisible to it.
2. **`[VF]`** `scripts/check_ui_contrast.py` walks only `<x>-foreground` on `<x>` (+ status-fg). Any variant that puts a plain token (`text-destructive`) or an alpha fill under text is outside its search space.
3. **`[VF]`** Four of 18 primitives have no composition-layer consumer; they are classified DEAD and are not part of W7's exit criterion, but are still held to the selector contract (a latent defect there is cheap to remove).
4. **`[HYP]`** `Tooltip`/`TooltipContent` are unmounted today, so tooltip regressions have no user path.

---

## Phase 2 - candidates

| ID | Location | Property claimed violated | Class | Innocence path |
|---|---|---|---|---|
| D1 | `select.tsx:70`, `dropdown-menu.tsx:40`, `tooltip.tsx:53` | a selector names an attribute the primitive emits | C8 | base-ui emits `data-state` (it does not) |
| D2 | `alert.tsx:17`, `badge.tsx:21` | destructive text is readable in the default (dark) theme | C9, T7 | a token elsewhere lightens it |
| D3 | `tabs.tsx:8-22` | the `orientation` prop reaches the primitive that owns keyboard semantics | C8 | the prop is forwarded via `...props` (it is destructured out) |
| D4 | `button.tsx` | a `<Button>` inside a `<form>` does not submit it (no default `type="button"`) | C8 | no `<form>` exists in the app |
| D5 | `scroll-area.tsx` | `viewportRef`/`onViewportScroll` bind the scrolling element | C8 | base-ui Viewport forwards the ref |
| D6 | `dialog.tsx` | nested Dialog: Escape closes one layer, `initialFocus` honoured, focus returns | T7 | base-ui focus manager owns it |
| D7 | `progress.tsx` | NaN / >100 / <0 input does not fabricate a value | C1 | base-ui clamps |
| D8 | every `bg-/text-/border-/ring-<token>` in `ui/*` | each resolves to a defined `--color-*` | C9 | all are defined |
| D9 | `input.tsx` | `onChange` still receives a DOM event after wrapping base-ui `Input` | C8 | base-ui passes it through |
| D10 | `select.tsx`, `dropdown-menu.tsx` | keyboard open/typeahead | C8 | no consumer (DEAD) |
| D11 | `DialogSheet` | the popup has an accessible name | T7 | caller passes `aria-label` |
| D12 | `TabsTrigger` `text-foreground/60` | alpha text on `bg-muted` meets AA | C9 | arithmetic says yes |
| D13 | `dialog.tsx` overlay `bg-black/10`, `/50` | raw colour where a token exists | C9 | a scrim is not a token |

---

## Phase 3 - proof of defect

### 3.1 D2 - destructive Alert title/body and failed-step Badge are ~1.7:1 in dark mode

**Trigger** (`primitives.contract.test.tsx` > "W7 D2"): render the primitive, read the classes it
actually emits, resolve each `text-<token>[/alpha]` against `globals.css` for both themes, compute the
WCAG ratio against the fill it sits on.

```
destructive/1:            expected 1.8131908450193193 to be >= 4.5     (Alert, dark)
destructive on card:      expected 1.7135318036343792 to be >= 4.5     (Badge, dark)
```

Light theme passes (5.61 / 4.77). The numbers agree with an independent computation using the repo's
own `check_ui_contrast.py` functions (1.81, 1.71).

**Why the instrument missed it:** `--destructive` in `.dark` is `0 63% 31%`, a dark red chosen as a
*fill* (it passes as `destructive-foreground` on `destructive`, 9.43:1, which is the pair the script
walks). Used as *text* on a dark card it is nearly invisible. `check_ui_contrast.py` never evaluates
that pairing.

**Innocence attempt.** Guard: none, the class is unconditional. Reachability: `layout.tsx`'s
`THEME_INIT_SCRIPT` adds `.dark` for every user except those who chose light, so dark is the default.
`ConnectionStatus` renders `<Alert variant="destructive">` for the "Connection Error" state (the
moment the user most needs to read it) and `StatusEventRow` renders `<Badge variant="destructive">`
for every **failed** step. Owner: the primitive's own class string; the `status-error-fg` token that
is already text-safe in both themes exists and is already contrast-checked. No defence holds.

**Net verdict: CONFIRMED.** Severity MEDIUM (T7 / T2 adjacent: an error state that renders
near-invisible reads as "nothing is wrong").

### 3.2 D3 - `Tabs orientation="vertical"` is half-applied

Trigger: render vertical Tabs.

```
expected null to be 'vertical'                       (tablist aria-orientation)
expected <button ... B> to be <button ... A>         (ArrowDown does not move focus)
```

Mechanism `[VF]`: `orientation` is destructured out of props and only written to the wrapper's
`data-orientation`; `TabsPrimitive.Root` never receives it, so base-ui stays horizontal. The wrapper's
class selectors (`group-data-[orientation=vertical]/tabs`) lay it out vertically while keyboard and ARIA
semantics stay horizontal (ArrowRight navigates, ArrowDown does nothing, `aria-orientation` absent).

**Innocence attempt.** Reachability: no current consumer passes `orientation` (all three use the
default), so this is a **latent** defect in an exported prop, not a live one. Contract owner: the
wrapper declares the prop, so it owns forwarding it. The "unused" defence lowers severity to LOW; it
does not clear the defect.

**Net verdict: CONFIRMED, LOW (latent).**

### 3.3 D1 - `data-[state=...]` selectors never match

Probe `[VF]` (open each popup, list attributes):

```
Menu popup    data-starting-style data-side data-align data-open data-instant ...   (no data-state)
Select popup  data-open data-side data-align ...                                    (no data-state)
Tooltip popup data-open data-side data-align data-instant ...                       (no data-state)
```

Trigger: `it.each(files)("%s has no data-[state=...] selector")` fails for `select.tsx`,
`dropdown-menu.tsx`, `tooltip.tsx`.

Consequence: Select and Menu popups carried **only** `data-[state=...]` animation classes, so their
open/close animation never existed. Tooltip carried `data-[state=delayed-open]` duplicates *beside*
working `data-open` classes, so it was dead weight, not a behavioural defect.

**Innocence attempt.** Reachability: Select and DropdownMenu have no consumer and Tooltip content is
never mounted, so **no user can see this today**. Contract owner: the project's own contract test
claims to catch "a selector names an attribute the primitive does not emit"; it demonstrably does not
for this form, which is the genuine defect (a hole in the guard). Verdict: CONFIRMED as a
contract-test gap with latent visual effect, LOW.

### 3.4 Cleared (code-innocent)

| ID | Trigger | Outcome |
|---|---|---|
| D4 | grep for `<form` / `type="submit"` across `src` | **no form exists**: the missing default `type` is unreachable. CLEARED (observation: becomes live the day a form is added) |
| D5 | `viewportRef.current` is `[data-slot=scroll-area-viewport]` and not Root; `fireEvent.scroll` on the viewport calls `onViewportScroll` once | plumbing is correct. CLEARED, now asserted |
| D6 | nested `Dialog`: `initialFocus` lands on `openB`; first Escape closes B only; second closes A; focus returns to the opener; `DialogSheet` keeps `aria-label`; `DialogContent` `aria-labelledby` resolves to the title | all correct. CLEARED, now asserted |
| D7 | `value` 150 gives width 100%, -5 gives 0%, NaN/null/undefined give `data-indeterminate` with no `aria-valuenow` | base-ui clamps; NaN is rendered as indeterminate, not as a number. CLEARED, now asserted |
| D8 | scan of all `(bg|text|border|ring|fill|outline)-<name>` in `ui/*` against `--color-*` | every name resolves. CLEARED |
| D9 | `fireEvent.change` on `<Input onChange>` | handler called once with an event whose `target.value` is the new value. CLEARED, now asserted |
| D11 | covered by D6 | CLEARED |
| D12 | alpha text on muted: `text-foreground/60` on `bg-muted` is 5.19 (light) / 6.24 (dark); `dark:text-muted-foreground` 6.07 | meets AA. CLEARED |

### 3.5 Not exercised

- **D10** (Select/DropdownMenu keyboard): DEAD, no consumer, not investigated; budget spent where users are.
- **D13** (raw `bg-black` scrim, `dialog.tsx`): a scrim is not a themeable surface and `lint_ui_debt` accepts it. OBSERVATION only; no fix.

---

## Phase 4 - inventory

| Candidate | Trigger | Innocence | Evidence | User-visible consequence | Status |
|---|---|---|---|---|---|
| D2 destructive text | contract test, ratio 1.81 / 1.71 | none holds | `[VF]` | failed-step badge and "Connection Error" alert unreadable in the default theme | **VERIFIED DEFECT** (MEDIUM) |
| D3 Tabs orientation | RTL: aria-orientation null, ArrowDown no-op | prop never reaches base-ui | `[VF]` | none today (no vertical consumer) | **VERIFIED DEFECT** (LOW, latent) |
| D1 `data-[state=]` | source scan + popup attribute probe | contract-test gap is real; popups unused | `[VF]` | none today (Select/Menu/Tooltip unmounted) | **VERIFIED DEFECT** (LOW, latent) |
| D4 Button `type` | grep | no `<form>` | `[VF]` | none | CLEARED |
| D5 ScrollArea | RTL | correct | `[VF]` | n/a | CLEARED |
| D6 Dialog | RTL | correct | `[VF]` | n/a | CLEARED |
| D7 Progress | RTL | correct | `[VF]` | n/a | CLEARED |
| D8 token resolution | scan | all resolve | `[VF]` | n/a | CLEARED |
| D9 Input | RTL | correct | `[VF]` | n/a | CLEARED |
| D11 Sheet name | RTL | correct | `[VF]` | n/a | CLEARED |
| D12 tab alpha text | arithmetic | AA | `[VF]` | n/a | CLEARED |
| D13 raw scrim | read | by design | `[VF]` | n/a | OBSERVATION |
| D10 Select/Menu keys | none | DEAD | `[UNK]` | none | NOT EXERCISED |

---

## Phase 5 - fix design

Placement: each violated property is owned by the primitive's class string or prop forwarding, so the
fix is in `components/ui/*`. No new mechanism and no new token (the text-safe `status-error-fg` already
existed and is contrast-checked).

| Defect | Diff |
|---|---|
| D2 | `alert.tsx`: destructive variant `text-destructive` to `text-status-error-fg`, description `text-destructive/90` to `text-status-error-fg/90`. `badge.tsx`: destructive `text-destructive` to `text-status-error-fg`. Two class-string lines. |
| D3 | `tabs.tsx`: `Tabs` passes `orientation={orientation}` to `TabsPrimitive.Root` (+1 line). |
| D1 | `select.tsx`, `dropdown-menu.tsx`: `data-[state=open/closed]:` to `data-open:` / `data-closed:` (the spelling `dialog.tsx` already uses). `tooltip.tsx`: removed the three dead `data-[state=delayed-open]` classes. One class string per file. |

Constraint note: D1 touches three components and D2 two, one string literal each. The plan's "1 function
per defect" limit is exceeded in letter; there is no semantic coupling and no shared state, so a split
would be artificial. Flagged for the verdict.

Conformance: public props unchanged; no new `fetch`, no ceiling touched, no dependency, no new lint rule.

### Self-review (RAR, eight vectors)

| # | Vector | Verdict |
|---|---|---|
| 1 | Boundary | light-theme ratios still pass (test runs both themes, two surfaces for Badge); default horizontal Tabs unchanged (test) `[VF]` |
| 2 | Invalid input | n/a (class strings, one forwarded enum) |
| 3 | State | Tabs value handling untouched; `orientation` is a static prop `[VF]` |
| 4 | Regression | full vitest 196/196, ESLint clean, `lint_ui_debt` six counters at ceiling, contrast script 58 pairs `[VF]` |
| 5 | Concurrency | n/a |
| 6 | New defect | Alert default and non-destructive Badge variants untouched; `status-error-fg` is defined in both themes `[VF]` |
| 7 | Architecture | token used where one exists, no raw colour added `[VF]` |
| 8 | Paradigm | same idiom as sibling variants and `dialog.tsx` `[VF]` |

`FIX HOLDS [VF]` for D2, D3, D1.

---

## Phase 7 - tests

All in `weebot-ui/src/components/ui/primitives.contract.test.tsx` (colocated, existing file; no new
fixture or harness). 58 tests total; 37 new.

| Test | Role |
|---|---|
| `W7 D1 > %s has no data-[state=...] selector` x18 | proof-of-defect (3 failed at HEAD: select, dropdown-menu, tooltip) |
| `W7 D1 > an open Tooltip popup carries data-open and no data-state` | boundary: documents what base-ui emits (passed before and after) |
| `W7 D3 > vertical Tabs expose aria-orientation=vertical` | proof-of-defect (failed at HEAD) |
| `W7 D3 > vertical Tabs move focus with ArrowDown, not ArrowRight` | proof-of-defect + negative boundary (ArrowDown failed at HEAD) |
| `W7 D3 > default Tabs stay horizontal` | no-regression |
| `W7 D2 > Alert destructive text on card (light/dark)` | proof-of-defect (dark failed at HEAD: 1.81) / no-regression (light) |
| `W7 D2 > Badge destructive text on its tinted fill (light/dark)` | proof-of-defect (dark failed at HEAD: 1.71) / no-regression (light) |
| `W7: Dialog contract` x3 | exit-criterion assertions (nesting, focus, naming, sheet label) |
| `W7: ScrollArea viewport plumbing` x2 | exit-criterion assertions (R4) |
| `W7: Progress` x3 | exit-criterion assertions (clamp, indeterminate) |
| `W7: form and status primitives` x3 | exit-criterion assertions (Input, Button, Alert) |

The contrast helper reads the real `globals.css`, resolves `var()` chains, and computes alpha-over-surface,
so it covers the case `check_ui_contrast.py` cannot (plain token and alpha fill). It reads the classes the
primitive renders; it does not hardcode the variant's token.

---

## Phase 8 - verdict

### Process checks

| Check | Status |
|---|---|
| Defect VERIFIED (trigger fired, no innocence defence) | yes, x3 |
| Fix <=15 lines | yes (6 changed lines in total) |
| Fix <=1 function | no for D1 (3 components) and D2 (2 components), see note above |
| Proof + boundary + no-regression tests | yes |
| Phase 0 census complete | yes |
| Fix in the invariant-owning layer | yes |

### Engineering checks

| Check | Status |
|---|---|
| All vectors FIX HOLDS | yes |
| Regression risk | LOW |
| Fix causal, not symptomatic | yes |
| Dependency-rule / abstraction bypass | none |
| Pattern introduced | none |

**Routing: ACCEPT** for D1, D2, D3 (with the one-function note recorded).

### Exit criterion

"Every primitive the composition layer relies on has either a contract assertion or a written `[UNK]` note": **met**.

| Primitive | Assertion / note |
|---|---|
| Button | ref + variant class; also exercised through `Dialog` Close `render={<Button/>}` |
| Card, Skeleton, Label, Separator | Separator asserted (pre-existing); the others are pure class wrappers, `[UNK]` layout note in the test file |
| Badge, Alert | D2 contrast + Alert `role=alert` |
| Dialog (Content, Sheet) | nesting, focus, naming |
| Tabs | pre-existing + D3 |
| ScrollArea | ref/scroll plumbing; `size-full` height chain `[UNK]` |
| Input | onChange event |
| Textarea | `field-sizing-content` auto-grow `[UNK]` |
| Progress | clamp, indeterminate |
| Tooltip | provider only; popup attributes asserted |
| Select, DropdownMenu, Avatar, Switch | no consumer; selector contract still applies (Switch also asserted) |

### Coverage statement

```
Surface audited:            R1 (selector contract), R2 (Dialog), R4 (ScrollArea), R5 (tokens/contrast for
                            Alert, Badge, Tabs, Button, Switch, Input placeholder), Progress, Input, Button
Surface NOT audited:        R3 Select/DropdownMenu keyboard (no consumer); layout/paint of every primitive
                            (no browser); globals.css beyond tokens (reduced-motion block read, not exercised)
Defect classes covered:     C1 (Progress), C8, C9; T7 for Dialog/Tabs
Architecture census basis:  VF (grep of consumers, README conventions, ceilings.toml, instruments run)
Confirmed defects:          CRITICAL 0 / HIGH 0 / MEDIUM 1 / LOW 2   (all fixed)
Cleared (innocent):         8     Re-attributed to owner: 0     Observations: 2 (D4 latent, D13)
Residual UNKNOWN:           layout/paint of the ScrollArea height chain, Textarea auto-grow, AppBar
                            -translate-y-0 merge, 44 px touch targets, focus rings (need a browser)
Clean-claim scope:          "Regions R1, R2, R4, R5 were audited for classes C1, C8, C9 and no VERIFIED
                            defect remains unfixed there."  Not "the primitives are bug-free".
Highest-value next hunt:    the contrast instrument's blind spot, generalised: every text-<plain token>
                            or alpha fill in components OUTSIDE ui/ (W5/W6 surfaces) is unwalked by
                            check_ui_contrast.py. grep finds no text-destructive / border-destructive
                            outside ui/ today, but text-muted-foreground/NN and bg-*/NN were not swept.
```

---

## 9. Recommendations carried to W8 (not implemented)

1. **Extend the instrument, do not hand-check:** the test's resolve-class-against-tokens helper could
   replace a hardcoded `PAIRS` list in `check_ui_contrast.py` for text tokens. That changes an instrument
   this wave was told not to touch, so it is a proposal only.
2. **`Button` default `type="button"`** becomes a real defect the day the first `<form>` lands. Cheap to add then.
3. **Dependency drift:** `package.json` declares `@base-ui/react ^1.9.0` and `vitest ^5`; installed are
   1.8.0 and 3.2.7. The contract test reflects the installed base-ui. Re-run it after any `npm ci`
   against the lockfile of record.

## 10. Uncertainty acknowledgment

**Finding most likely to be a false positive.** D1: no user path today (the three popups are unmounted).
It is filed LOW and is really a hole in the guard rather than a visible bug.

**Real defect most likely missed.** Anything paint-level in the dark theme that uses a plain token or an
alpha fill outside `ui/` (the same blind spot as D2, in W5/W6 territory), and browser-only layout behaviour.

**What requires runtime validation.** Whether the failed-step Badge and Alert now look right in the real
page (colour is computed, not seen); the ScrollArea height chain; the AppBar translate override.

**What additional input would most increase confidence.** A browser-capable host to run the e2e axe
suite, which would have caught D2 directly.

## 11. Commands

```bash
cd weebot-ui
npx vitest run src/components/ui/primitives.contract.test.tsx   # 7 failed before the fixes, 58 passed after
npx vitest run                                                  # 28 files, 196 tests
npx tsc --noEmit                                                # 0 errors
npm run lint                                                    # ESLint: no issues
cd ..
.venv/Scripts/python scripts/lint_ui_debt.py                    # 6 counters at ceiling, exit 0
.venv/Scripts/python scripts/check_ui_contrast.py               # 58 token pairs meet 4.5:1
```
