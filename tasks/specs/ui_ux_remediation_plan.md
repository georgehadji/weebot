---
status: implemented
date: 2026-10-24
note: from the 2026-10-24 UX/UI audit of weebot-ui; implemented the same day (Appendix C lists what landed and where it deviated); decisions D1-D6 were applied as recommended
---

# UI/UX Remediation — weebot-ui

This plan fixes every finding of the 2026-10-24 audit of `weebot-ui` (Next 16 App Router, React 19,
Tailwind 4, base-ui primitives through shadcn). It keeps the architecture the code already has,
names the paradigm or pattern for each module, and orders the work so that tests and gates exist
before the fixes they protect. It does not restyle the product, add a state library, or change the
WebSocket protocol.

Evidence labels used throughout: **seen** (reproduced in the running app), **read** (found by
reading the code, not reproduced), **measured** (a number I computed), **unmeasured** (a suspicion
with no number yet). Where the audit overstated something, section 1.3 corrects it.

## 1. Ground rules

### 1.1 The architecture this plan keeps

`weebot-ui/src` has a layering that is already respected and that every fix below stays inside:

```
types/        pure types, mirrors the backend event hierarchy
lib/          pure functions and the API client: session-reducer, endpoints, api
hooks/        React bindings over lib/ and providers/: useSessionEvents, useSessionList
providers/    process-wide services: EventStream (WebSocket/SSE), Toast, Theme
components/ui/            primitives (shadcn over base-ui); no knowledge of Weebot
components/{shell,conversation,dock,...}   Weebot-specific composition
app/          routes only: compose components, own no logic
```

Dependencies point downward only. A new rule is added and enforced in Phase 0: `components/ui`
imports nothing from `hooks/`, `providers/` or `lib/` except `lib/utils`.

On the backend the fixes follow the existing hexagon (`domain` <- `application` <- `infrastructure`
<- `interfaces`), the DI container, and the ratcheted gates in `tasks/quality/ceilings.toml`.
Nothing in this plan adds an import exemption.

The project web standards (`weebot/skills/builtin/web-development/SKILL.md`) apply: mobile-first at
375 px, checked at 375, 768 and 1280; contrast of at least 4.5:1; exactly one `<h1>`; `aria-label`
on icon-only buttons.

### 1.2 Patterns used, and why each one

| Need | Pattern | Why this and not another |
|---|---|---|
| A fact with one source of truth (session title, status label) | Single home plus a pure selector | The audit found the same fact computed or missing in three places |
| Server data with loading, empty, error | A discriminated union `Remote<T>` and one `StateView` | Makes the illegal state "loading and error at once" unrepresentable; replaces ad-hoc booleans |
| A multi-step UI interaction (composer) | A small state machine in a reducer | Sending, failed and retry are states, not flags |
| Timeline projection | Keep the existing event-sourcing reducer; extend it | It is pure, tested and already dedupes; the optimistic-message fix belongs in it |
| Modal surfaces (drawer, palette, confirm) | Reuse base-ui `Dialog` through `components/ui/dialog` | Focus trap, Escape, `aria-modal` and focus return come for free; the hand-rolled copies lack all four |
| Page chrome that survives navigation | Next route group with a shared layout | Today each route re-mounts the shell; a layout mounts once |
| Variants that depend on a primitive's state | A contract test, not trust | The tab bug is a silent mismatch between emitted attributes and class selectors |
| Regressions in UI debt | A ratchet, as on the backend | Same culture as `ceilings.toml`: exact counts, lowered when debt is paid |

### 1.3 Corrections to the audit

- The broken orientation variants (`data-horizontal:`, `data-vertical:`) occur in **three** files,
  `components/ui/tabs.tsx`, `scroll-area.tsx` and `separator.tsx`. The audit said eight. Only Tabs
  was reproduced (**seen**: root `flex-direction: row`, tab list 640 px tall). The other two follow
  from the same cause (**read**). The other state variants (`data-open`, `data-checked`, ...) are
  unverified and are covered by the Phase 1 contract test.
- Session `event_count` is 0 for every session because it is `len(session.events)` on the `Session`
  model, while events live in the event store (**read**, `routers/sessions.py:53`). That is a
  backend bug with a backend fix, not a UI one.
- Session `title` is empty because nothing sets it: `Session.set_title` has no caller, and the
  create route never passes a title (**read**). `TitleEvent` is emitted by the planner but not
  persisted.

## 2. Findings to modules

| # | Finding | Evidence | Module(s) | Phase |
|---|---|---|---|---|
| 1 | Orientation variants never match; Ops tab list 640 px tall | seen | `components/ui/{tabs,scroll-area,separator}` | 1 |
| 2 | All sessions "Untitled"; every count "0 events" | seen | backend `domain`, `routers/sessions`, `EventStorePort`; UI types | 2 |
| 3 | Mobile: clipped header, 354 px "Sessions" bar, `100vh`, two `<main>`, 112 px of chrome | seen | `app/layout`, `Header`, `TopBar`, `ConsoleShell` | 3 |
| 4 | Rail search box is inert | read | `SessionRail`, `lib/` | 5 |
| 5 | Stick-to-bottom never updates (`onScroll` on the content div) | read | `ConversationPane` | 4 |
| 6 | Drawer and palette are not real dialogs | read | `ConsoleShell`, `CommandPalette` | 3 |
| 7 | Status is colour-only; light-theme status text 2.15 to 3.76:1 | measured | tokens in `globals.css`, `SessionRail`, `StatusEventRow` | 6 |
| 8 | 82 uses of 10 to 12 px text; 28 px mobile controls | measured | `ui/button`, many components | 6 |
| 9 | Stream not announced; toasts auto-dismiss errors; no skip link; no `aria-current`; `<a><button>` | read | `providers/Toast`, `Header`, `ConversationPane` | 3, 4, 6 |
| 10 | Composer: no failed state, disabled while sending, IME, no autosize | read | `Composer`, reducer | 4 |
| 11 | Tool rows show no arguments, no failure, no copy | read | `ToolCallRow` | 4 |
| 12 | Bare empty and loading states, no error state in the rail, native `confirm()` | read | rail, sessions, models, ops | 5 |
| 13 | Timeline re-renders fully, unvirtualized; heavy libraries imported statically (no `next/dynamic` anywhere) | read; effect unmeasured | `ConversationPane`, `CodeBlock`, `CostChart`, `PlanVisualizer` | 7 |

## 3. Phases

Order and reasons: Phase 0 builds the net. Phase 1 is the cheapest visible win. Phase 2 spans the
backend and is the one with a data contract. Phases 3 to 6 are the UI work, grouped by module so
that a reviewer reads one area at a time. Phase 7 starts with a measurement and may end in "no
change". Phase 8 is documentation. Phases 1, 2 and 3 are independent once Phase 0 lands and can run
in parallel; 4 depends on 3 (the shell) only for the live region placement; 5 depends on 2.

### Phase 0 — The net: gates before fixes

**0.1 Deterministic browser tests.** Playwright is installed but `tests/` holds one smoke test.
Add fixtures that intercept `/api/**` with `page.route` and stub the WebSocket, so the suite needs
no backend and no model keys. Fixtures: an empty app, nine sessions with real-shaped payloads
(copied from the audit's capture, including empty titles), a session with 2,000 events.

**0.2 Accessibility gate.** Add `@axe-core/playwright` (a new dev dependency; installing it needs
the network and is the one step outside the repository). A spec runs axe on `/`, `/sessions`,
`/ops`, `/models`, `/settings`, `/behavior`, in dark and light theme, at 375 and 1280 px, and fails
on any serious or critical violation. It starts red on today's code; each phase turns part of it
green, which is its acceptance test.

**0.3 Component contract tests.** `vitest` and Testing Library are installed. Add a
`primitives.contract.test.tsx` that renders each `components/ui` primitive that uses a state
variant and asserts the attribute the class selector needs actually appears on the element. This
is the test that would have caught finding 1.

**0.4 UI debt ratchet.** A script `scripts/lint_ui_debt.py` counts, over `weebot-ui/src`:
`data-horizontal:` / `data-vertical:` selectors (target 0), `text-[10px]` and `text-[11px]`
(ceiling today's count, target 0), `<main` elements (exactly 1 reachable per route), `100vh`
(target 0), and `onClick` on non-interactive elements. It reads its ceilings from
`tasks/quality/ceilings.toml` through the existing `quality_ceilings.py`, exact equality both ways,
and is wired into the Makefile (`lint-ui`) and `.github/workflows/architecture.yml`.

**0.5 Layer rule for the UI.** An ESLint `no-restricted-imports` rule: `components/ui/**` may not
import `@/hooks`, `@/providers` or `@/lib` (except `@/lib/utils`); `lib/**` may not import `react`.
Both already hold; the rule keeps them true.

**0.6 CI job.** `npm ci`, `npm run lint`, `npm test`, `next build`, then Playwright. The build
output size is recorded for Phase 7.

Acceptance: the new jobs run in CI; the axe spec and the contract test fail on the current code for
the reasons in section 2 and nothing else.

### Phase 1 — Primitive contract (finding 1)

Problem: shadcn's base-ui template selects on `data-horizontal`/`data-vertical`; base-ui 1.8 emits
`data-orientation="horizontal"`. The selectors never match, so Tabs lays out as a row.

Design: this is an Adapter problem at the `components/ui` boundary, so it is fixed there and only
there. Replace the selectors with `data-[orientation=horizontal]:` and `data-[orientation=vertical]:`
in the three files, using Tailwind 4's attribute form. Do not add a global
`@custom-variant data-horizontal` as the fix: whether it overrides Tailwind's built-in `data-*`
variant is not something I verified, and a global alias would hide the same mismatch from the next
generated component. The contract test from 0.3 is the durable fix; the selector change is the
repair.

Files: `tabs.tsx` (5 lines), `scroll-area.tsx` (1), `separator.tsx` (1), the new contract test.
Check every other `data-*:` variant in `components/ui` against what base-ui emits and fix any that
fail the contract test.

Acceptance: the Ops tab list is one row of about 32 px, panels below it; horizontal scrollbar and
separator have size; the contract test and `lint-ui` pass with zero orientation selectors.
Risk: low. Visual diff on Ops and any page with Tabs, Separator or ScrollArea.

### Phase 2 — Session identity: title and event count (finding 2)

Problem and root cause are on the backend, so the fix starts there and the UI only consumes it.

**2.1 Title is a domain fact, derived once.**
- Add a pure function `derive_session_title(text: str, max_len: int = 60) -> str` in
  `weebot/domain/services/session_title.py`: first non-empty line, whitespace collapsed, markdown
  and URL noise stripped, cut at a word boundary with an ellipsis, empty input returns an empty
  string. No LLM call: a title must cost nothing and cannot fail. Domain stays pure.
- `_session_to_response` in `routers/sessions.py` becomes the one place that decides the displayed
  title: `session.title` if set, else `derive_session_title(context.original_task or
  context.last_prompt)`. Deriving at read time means the 9 existing sessions are fixed with no
  migration, and it is idempotent.
- The create route also stores the derived title so it is persisted for exports and search.
- Replace-on-better-information: when the planner's `TitleEvent` arrives, the runner persists it
  with `Session.set_title` (today that method has no caller). `TaskRunner` already rewrites the
  session on each event, so the change is one branch in its event handling, and the presence event
  it already emits (`SessionPresenceEvent.title`) then carries the better title to the rail with
  no UI change.

**2.2 Event count is a read-model concern, not a Session field.**
- Add `count_events(session_ids: Sequence[str]) -> dict[str, int]` to `EventStorePort`, implemented
  in `infrastructure/event_store.py` as one grouped query. One call per list request, never one per
  session.
- The list and get routes pass the counts into `_session_to_response`. Remove `len(session.events)`
  as the source.
- A contract test over the SQLite adapter and the in-memory double, as was done for `TaskQueuePort`.

**2.3 UI.** `types/events.ts` already has `title?: string` and `event_count`. The rail, the sessions
page and the top bar show `session.title || "New session"`; there is no second derivation in the
UI (one home per fact). `useSessionList.applyPresence` keeps merging title from presence.

Tests: pure unit tests for `derive_session_title` (empty, long, markdown, Greek, multi-line, only
URL); a route test that a session created with a prompt returns a non-empty title; a contract test
for `count_events`; a Playwright check that the rail shows the prompt, not "Untitled".
Acceptance: no "Untitled session" for any session that has a prompt; counts match the event store.
Risk: low. A title shown in the rail is user content; it is rendered as text, never as HTML.

### Phase 3 — Shell and navigation (findings 3, 6, 9)

Pattern: **Composite with slots** for the shell, **route group layout** so it mounts once, and the
**existing `Dialog` primitive** for every modal.

**3.1 One shell, mounted once.** Create `app/(console)/layout.tsx` and move `app/page.tsx` and
`app/sessions/[id]` into the group. The layout renders `AppShell` (rail, main, optional dock). The
rail, its data fetch and its WebSocket subscription then persist across navigation instead of
re-mounting per page (today `ConsoleShell` is created separately in `page.tsx` and
`sessions/[id]/page.tsx`; only `/` and `/sessions/[id]` use it today, so `/sessions` and the other
pages stay outside the group). The dock is a parallel route slot (`@dock`) or a context-provided slot
filled by the session page; the choice is D5.

**3.2 One header.** Merge the global `Header` (64 px) and `TopBar` (48 px) into one `AppBar` of
48 px. Title, connection state and the command palette trigger become slots the page fills; global
navigation stays. This removes the 112 px of stacked chrome.

**3.3 One `<main>`.** `app/layout.tsx` renders the landmark; `ConsoleShell` stops rendering a
second one. A skip link ("Skip to content") is the first focusable element. `lint-ui` enforces one
`main` per route.

**3.4 Viewport units.** Replace `h-[calc(100vh-4rem)]` with a grid on `min-h-dvh` whose rows come
from the layout, not a hard-coded subtraction. The 354 px bar was `flex-1` on a bar that should be
`shrink-0`; the grid removes the class of bug.

**3.5 Mobile navigation.** Below `md`, the header shows the logo, the page title and a menu button
that opens a `Dialog` holding the nav links and actions (New Session, theme, settings). At `md` and
above it is the current inline row. The nav gets `aria-label="Primary"` and `aria-current="page"`
on the active link.

**3.6 Real dialogs.** `MobileDrawer` and `CommandPalette` are rebuilt on `components/ui/dialog`
(a `ResponsivePanel` for the rail and dock: inline at `md`+, a side `Dialog` below). This gives
Escape, focus trap, `aria-modal` and focus return for free and deletes two hand-rolled overlays.
The palette keeps its own list logic and gets the combobox pattern (`role="combobox"` on the input,
`aria-activedescendant`, options not wrapping buttons).

**3.7 No nested interactives.** `<Link><Button/></Link>` in the header becomes a `Link` styled with
the exported `buttonVariants`.

Tests: Playwright at 375, 768, 1280: no horizontal overflow; header actions reachable; drawer opens,
traps focus, closes on Escape and returns focus to the trigger; exactly one `main`; axe clean for
landmarks and dialogs.
Acceptance: findings 3 and 6 and the structural part of 9 closed; axe spec green for the shell.
Risk: medium. The route-group move changes file paths, so it lands as its own commit with no other
change. Mitigation: the Playwright suite from Phase 0 runs before and after.

### Phase 4 — Conversation module (findings 5, 9, 10, 11)

**4.1 Stick-to-bottom as a hook.** `useStickToBottom(viewportRef, deps)` in `hooks/`. It observes a
sentinel at the end of the list with an `IntersectionObserver` (robust to content height changes,
unlike a scroll handler) and exposes `{ atBottom, scrollToBottom }`. The scroll handler on the
wrong element is deleted. When the user is scrolled up, a "Jump to latest" pill appears with the
count of new events. The threshold logic is a pure function and unit-tested.

**4.2 Announcing a live stream without noise.** Two parts. The timeline gets `role="log"` and
`aria-live="polite"` with `aria-relevant="additions"`, but streamed text is not announced token by
token. A visually hidden `AnnouncerProvider` (a Mediator between events and assistive tech) is fed
only coarse, meaningful events: step completed, waiting for user, error, done. `ConversationPane`
publishes to it through a hook; nothing else announces.

**4.3 Composer as a state machine.** `useComposer` is a reducer with states `idle`, `sending`,
`failed`. The textarea is never disabled while sending (focus is no longer lost). Enter sends unless
`event.nativeEvent.isComposing` (IME). Height grows with content (`field-sizing: content` with a
`max-height`), and the draft is kept per session in `sessionStorage` (Memento) so a reload does not
lose it.

**4.4 Optimistic messages that can fail.** Extend the session reducer so a user message carries
`delivery: "sending" | "sent" | "failed"`, keyed by `clientMsgId`. The server echo reconciles by that
id; a failed send stays in the timeline with a Retry action and the draft restored. The reducer
stays pure and gains tests for reconcile, duplicate echo and failure. Event-sourcing is kept; the
UI only adds a local, reconcilable event.

**4.5 Tool rows that explain themselves.** `ToolCallRow` is a presenter over `ToolEvent`, which
already carries `function_args`, `status` and `result`. It shows arguments, a distinct failed state
(derive it from the result or an error field; if the backend does not mark failure, add the field
to `ToolEvent` in `types` and in `weebot/domain/models/event.py`, which is D6), a copy button, the
truncation notice with a way to see the rest, and the scrollable `<pre>` gets `tabIndex=0` and an
accessible name.

Tests: unit tests for the hook's pure part and the reducer; Playwright with the 2,000-event fixture
for the pill and for focus staying in the composer; axe on a populated session.
Acceptance: scrolling up while events stream is not interrupted; a failed send is visible and
retryable; the stream's key moments are announced; tool rows show arguments and failure.
Risk: medium for 4.4 (reducer contract). Mitigation: reducer tests first.

### Phase 5 — Rail, lists and states (findings 4, 12)

**5.1 Async state as a type.** `types/remote.ts`: `Remote<T> = idle | loading | error(message) |
ready(data)`. A `useRemote` hook replaces the separate `loading` and `error` booleans in
`useSessionList` and the pages. One `StateView` component renders skeleton, empty (with a helpful
action, e.g. example prompts on the home page), error (with Retry) or children. Every list route
gets a route-level `loading.tsx` and `error.tsx` (Next convention).

**5.2 Search that works.** A pure `filterSessions(sessions, query)` in `lib/` (title and prompt,
case and diacritics insensitive so Greek works), driven by `useDeferredValue`. For results beyond
the loaded page the rail calls the existing backend `GET /sessions/search` (debounced), so no new
endpoint is needed. The input becomes a controlled component with a clear button.

**5.3 One status component.** `StatusBadge` is the single home for status to `{label, icon, colour
token}`. The rail dot, the sessions page badge and the status event rows all use it, so status is
never colour-only (icon plus visible or screen-reader text). This also removes the duplicated status
maps.

**5.4 Confirm without `window.confirm`.** A `ConfirmDialog` on the `Dialog` primitive for delete,
with the session title in the prompt and focus on the safe action.

Tests: unit tests for `filterSessions` (including Greek) and `useRemote`; Playwright for empty,
loading, error and retry; axe.
Acceptance: typing in the rail filters; the app shows a clear error with Retry when the backend is
down; no blank or text-only loading state; no native `confirm()`.
Risk: low.

### Phase 6 — Visual system (findings 7, 8, 9)

**6.1 Text-safe status tokens.** Keep the status colours for fills and dots. Add `--status-*-text`
tokens for text, darker in the light theme so each reaches 4.5:1 (today green 2.28, amber 2.15, red
3.76 on white). A small script checks every foreground/background token pair in both themes and
fails below 4.5 (3 for non-text), and runs in Phase 0's lint job. Dark theme already passes (muted
7.34:1) and is the default.

**6.2 A type floor.** Introduce `text-2xs` (12 px) in `@theme` and replace every `text-[10px]` and
`text-[11px]`; `lint-ui` ratchets the old forms to zero. Do not go below 12 px for anything a user
must read; uppercase micro-labels become 12 px with tracking.

**6.3 Touch targets.** `buttonVariants` gets a coarse-pointer rule: under
`@media (pointer: coarse)` interactive sizes have `min-height: 44px`. Desktop density is unchanged.
The `h-7` mobile bar buttons are replaced by the real `size` tokens.

**6.4 Toast policy.** Errors do not auto-dismiss (they persist until dismissed); other toasts pause
their timer while hovered or focused and have a longer default. The region stays mounted so
announcements are reliable.

Tests: the contrast script; Playwright screenshots in both themes at 375 and 1280; axe contrast
rules.
Acceptance: axe contrast clean in both themes; no `text-[10px]` or `text-[11px]`; mobile controls
at least 44 px; error toasts persist.
Risk: low, visual. Review screenshots.

### Phase 7 — Performance: measure, then decide (finding 13)

This phase begins with a measurement and may stop there.

**7.1 Baseline.** Using the 2,000-event fixture, record scripting time per appended event and long
tasks with a Playwright trace, and record the first-load JS of `/` and `/sessions/[id]` from
`next build`. These become budgets (D3).

**7.2 Cheap, behaviour-neutral fixes first.** `React.memo` on row components (the reducer already
returns stable event objects), `content-visibility: auto` with `contain-intrinsic-size` on rows, and
`next/dynamic` with `ssr: false` for Monaco, reactflow and recharts, which are imported statically
today in `CodeBlock`, `PlanVisualizer` and `CostChart`.

**7.3 Virtualization only if a budget still fails.** If 2,000 rows miss the budget after 7.2, add
windowing with `@tanstack/react-virtual`. It complicates stick-to-bottom, anchoring and find-in-page,
so it is a last resort, not a default.

Acceptance: the budgets are recorded and enforced in CI; the heavy libraries are off the initial
bundle; no regression in Phase 4's behaviour.

### Phase 8 — Documentation and map

Update `weebot-ui/README.md` (structure, the layer rule, how to run the browser and a11y suites),
the `map/objects/interfaces/WebUI.md` card (new shell, route group, `Remote<T>`, status component)
and re-verify its citations, record the new ratchets in `tasks/quality/ceilings.toml`, and add an
Appendix to this file in the style of the 2026-10 plan: what landed, where it deviated.

## 4. Decisions

Each has a recommended default; the default is applied unless reversed.

- **D1 Title source.** Deterministic derivation at create and read time; the planner's title
  replaces it when it arrives. Rejected: an LLM-generated title on every create (cost, latency, can
  fail).
- **D2 Search scope.** Client filter over the loaded page, plus the existing `/sessions/search` for
  the rest. Rejected: a new search endpoint.
- **D3 Performance budgets.** Set from the Phase 7.1 baseline, then ratcheted. Not guessed now.
- **D4 Runtime validation of API payloads.** Typed accessors for `context` with small guards; no
  new dependency (`zod`) for now. Revisit if payload drift causes a second bug.
- **D5 Dock wiring.** A context-provided slot filled by the session page, not a parallel route:
  fewer moving parts, and the dock reads the same session the page already loaded.
- **D6 Tool failure.** If `ToolEvent` has no explicit failure signal, add one to the backend event
  and the UI type together rather than inferring failure from result text.

## 5. Test matrix

| Layer | Tool | What |
|---|---|---|
| Pure logic | vitest | `filterSessions`, stick-to-bottom threshold, composer reducer, session reducer (optimistic, reconcile, failure) |
| Primitives | vitest + Testing Library | contract test: emitted attributes match class selectors |
| Components | vitest + Testing Library | `StateView`, `StatusBadge`, `ConfirmDialog`, tool row |
| Backend | pytest | `derive_session_title`, `count_events` contract (SQLite and in-memory), create/list route |
| Browser | Playwright with stubbed API | empty, loaded, 2,000 events, failure, mobile, tablet, desktop |
| Accessibility | axe in Playwright | six routes, both themes, two widths |
| Debt | `lint-ui` ratchet | selectors, tiny text, `100vh`, `main` count, layer imports |
| Performance | Playwright trace, `next build` | scripting per event, first-load JS |

## 6. Definition of done

- All thirteen findings in section 2 have a test that failed before and passes after.
- `lint-ui`, the existing backend gates, `npm run lint`, `npm test`, `next build` and the browser
  suites pass in CI.
- The axe spec is green on every route in both themes at 375 and 1280.
- No ceiling was raised; the UI ceilings only went down.
- The map card and README describe what exists.

## 7. Risks and what is not covered

- The route-group move (3.1) is the largest structural change; it ships alone.
- Phase 7's value is unknown until measured; it may end at the measurement.
- Light-theme fixes assume light theme stays a supported theme; if it is dropped the work in 6.1
  shrinks.
- Not covered: a redesign, internationalisation of the UI strings, the CLI/REPL experience, and the
  `behavior` and `models` pages beyond the shared states, tokens and axe fixes in Phases 5 and 6.
- `@axe-core/playwright` and, conditionally, `@tanstack/react-virtual` are new dev or runtime
  dependencies and need a network install.

## Appendix A — Evidence ledger

| Item | Value | How obtained |
|---|---|---|
| Ops `Tabs` root `flex-direction` | `row`; tab list height 640 px; root has only `data-orientation=horizontal` | DOM inspection in the running app |
| Sessions with empty `title` | 9 of 9; `context.original_task` / `last_prompt` present | `GET /api/sessions` |
| `event_count` | 0 for all sessions | same call; source `len(session.events)` |
| Mobile "Sessions" bar height | 354 px | DOM measurement at the mobile preset |
| `<main>` elements | 2 | DOM count |
| Header plus top bar | 64 + 48 px | source and DOM |
| Contrast on white, light theme | green-500 2.28:1, amber-500 2.15:1, red-500 3.76:1, idle dot 3.23:1 | computed from the token values |
| Contrast, dark theme | muted on page 7.34:1, on surface 5.21:1, white on primary 5.70:1 | computed |
| `aria-live` regions | 1 in `src` | grep |
| 10 to 12 px text | 82 matches of `text-xs`, `text-[10px]`, `text-[11px]` | grep |
| `next/dynamic` / lazy imports | none; Monaco, reactflow, recharts, syntax highlighter imported statically | grep |
| Stick-to-bottom | `onScroll` attached to the content div, scroll events do not fire there | source, `ConversationPane.tsx:75`; not reproduced |
| Rail search | no `value`, no `onChange` | source, `SessionRail.tsx:34` |

## Appendix B — Alternatives rejected

- **A global `@custom-variant` alias for `data-horizontal`.** Hides the mismatch; its precedence over
  the built-in variant is unverified.
- **Server-side session titles from an LLM.** Cost and failure modes for a label.
- **Adopting a data-fetching library (React Query/SWR) for `Remote<T>`.** Reasonable later; today the
  surface is a handful of hooks and the WebSocket path would not use it.
- **Virtualizing the timeline first.** Highest complexity, unmeasured benefit.
- **Fixing `event_count` in the UI by counting loaded events.** Wrong for sessions not open, and the
  number belongs to the backend.

## Appendix C — Implementation record (2026-10-24)

Everything below was verified by tests that ran: `npm test` (vitest), `npx playwright test` (76 browser tests against a
production build with the API and socket stubbed), ESLint, `tsc`, pytest for the backend, and `make lint-ui`'s two scripts.
What was **not** verified is listed at the end.

### What landed, by phase

| Phase | Landed | Where |
|---|---|---|
| 0 Net | Playwright suite with a stubbed backend (`e2e/fixtures.ts`), served from its own build directory (`e2e/serve.mjs`); axe over 7 routes x 2 themes x 2 widths (`e2e/a11y.spec.ts`, new dev dependency `@axe-core/playwright`); primitives contract test; `lint-ui` ratchet with 6 counters; ESLint layer rules; CI job runs build and browser tests | `weebot-ui/e2e/`, `scripts/lint_ui_debt.py`, `tasks/quality/ceilings.toml`, `eslint.config.mjs`, `.github/workflows/architecture.yml` |
| 1 Primitives | `data-[orientation=...]` in tabs, scroll-area, separator. The contract test failed 4 ways on the old code and passes now. Ops tab list: 640 px -> 32 px (measured in the running app) | `components/ui/` |
| 2 Identity | `derive_session_title` (domain, pure); `_displayed_title` in the router decides; create stores it; the planner's `TitleEvent` is persisted and announced to the rail; `EventStorePort.count_events` (one grouped query per 500 ids) replaces `len(session.events)`; `Session.set_title` now keeps the memory index | `weebot/domain/services/session_title.py`, `routers/sessions.py`, `event_store.py`, `task_runner.py` |
| 3 Shell | `AppShell` (skip link, one `<main>`, `h-dvh`), one 48 px `AppBar` with a menu dialog below `lg`, `(console)` route group mounting `ConsoleShell` once, rail/dock as `Dialog` side sheets, palette rebuilt on `Dialog` with the combobox pattern, dock wired by a context slot (D5) | `components/shell/`, `providers/ShellProvider.tsx`, `app/(console)/` |
| 4 Conversation | `useStickToBottom` (IntersectionObserver + "Jump to latest"), `AnnouncerProvider`, composer reducer + `useComposer` (never disabled, IME-safe, per-session draft), optimistic messages with `delivery` and Retry, tool rows with arguments / failed state / copy / full result, `ToolEvent.is_error` (D6) | `hooks/`, `lib/`, `components/conversation/`, `weebot/domain/models/event.py`, `executor/_base.py` |
| 5 States | `Remote<T>`, `useRemote`, `StateView`, `StatusBadge`, `ConfirmDialog`, `filterSessions` (Greek-safe), working rail search, example prompts on the home page, `app/error.tsx` | `types/remote.ts`, `components/common/`, `lib/sessions.ts` |
| 6 Visual | `--status-*-fg` text tokens, light `muted-foreground` and `destructive` darkened, `check_ui_contrast.py` (58 pairs, both themes), no text under 12 px, 44 px targets on coarse pointers, toast policy (errors persist, others pause on hover/focus, 8 s) | `globals.css`, `components/ui/button.tsx`, `providers/ToastProvider.tsx` |
| 7 Performance | Measured, then fixed (below) | `e2e/perf.spec.ts`, `components/plan/LazyPlanVisualizer.tsx` |
| 8 Docs | `weebot-ui/README.md`, `map/objects/interfaces/WebUI.md` | |

### Measurements (production build, uncompressed JavaScript before the `load` event)

| Route | Before | After | Change |
|---|---|---|---|
| `/` | 884 KB | 748 KB | -136 |
| `/sessions/[id]` | 885 KB | 749 KB | -136 |
| `/ops` | 1245 KB | 715 KB | -530 |
| `/models`, `/behavior` | 662, 695 KB | unchanged | |

A live event on a 2,041-row timeline cost 2.8 ms of scripting before `React.memo` rows and 1.4 to 2.0 ms after (a 16 ms
frame is the bar), so **virtualization (7.3) was not needed and was not built**. Budgets in `e2e/perf.spec.ts` are the
after figures plus about 7 %.

Ceilings moved: `ui_viewport_height` 3 -> 0, `ui_main_landmarks` 2 -> 1, `ui_click_on_static` 2 -> 0,
`ui_tiny_text` 10 -> 0 (all at their targets; none was raised).

### Deviations from the plan

- **Corrections to the audit's own numbers.** Text under 12 px was 10 occurrences, not the 82 the audit counted (that
  figure included `text-xs`, which is 12 px). The plan's claim that `lib/` already imported no React was wrong: the
  command-registry hook lived in `lib/commands/`; it moved to `hooks/useRegisterCommands.ts`.
- **6.2:** no `text-2xs` token was added. `text-xs` is already 12 px, so the old forms were replaced by `text-xs`.
- **5.2:** the rail filters the loaded page (100 sessions) only. The `/sessions/search` fallback was not wired: its
  results are bookend records, not `Session` rows, so using them needs a mapping that this change did not justify.
  Revisit if anyone has more than 100 sessions.
- **5.1:** a root `app/error.tsx` was added; per-route `loading.tsx` files were not, because the pages are client
  components that render their own `StateView` loading state.
- **3.1/3.3:** the rail is a `<nav aria-label="Sessions">` and the dock a labelled region inside the one `<main>`, because
  axe flags an `<aside>` nested in `<main>`. The breakpoint for inline navigation is `lg` (1024 px), not `md`: at 768 px
  the bar overflowed (found by the browser test, fixed).
- **7.1:** first-load JavaScript is measured by response bodies before the `load` event. Measuring at `networkidle`
  was wrong: Link prefetches of other routes inflate it.
- **Dev compile flake:** running the axe suite against `next dev` produced `#__next_error__` pages on first compile of a
  route, so the suite builds and serves a production bundle by default (`E2E_DEV=1` opts back in).
- `CodeBlock` (and its Monaco/syntax-highlighter imports) has no importer. It is dead code; it was left alone.

### Not verified

- **Visual appearance.** The preview pane could not render frames in this environment, so no screenshot was taken or
  compared. Layout was checked by measured geometry (heights, overflow, focus, roles), not by eye. Review the light
  theme and the mobile layouts by hand.
- Real-device touch behaviour (the 44 px rule was tested with Chromium's coarse-pointer emulation).
- A screen reader. Roles, names and live regions were checked with axe and DOM assertions only.
- The stick-to-bottom fix against a real streaming run; it was tested with a 2,000-event fixture and injected socket events.
- `make lint-map`: the map card cites new files that are not committed yet, and 50 older citations already drifted at
  `HEAD` before this work (`_factories.py`, `settings.py` and `adapter_factory.py` moved in the Ollama commits). Both
  need a commit and `check_map_citations.py --fix` / a re-stamp of the card's `commit:` field.
