---
status: open
date: 2026-11-03
note: fixes the 2026-11-03 Web Interface Guidelines audit of weebot-ui (~250 findings); ten phases, foundations first; follows on from specs/ui_ux_remediation_plan.md (done)
---

# weebot-ui: plan to fix the Web Interface Guidelines audit of 2026-11-03

## Context

The audit at [audits/web_interface_guidelines_audit_2026-11-03.md](../audits/web_interface_guidelines_audit_2026-11-03.md) checked all 70 UI files in `weebot-ui/src` against Vercel's Web Interface Guidelines. It produced about 250 `file:line` findings. This plan fixes all of them. Fixing all of them does not mean applying the audit's suggested fix to every line. Where the suggested fix conflicts with how the UI is already designed, the plan follows the existing design and says why (see "Findings resolved by design, not by the literal fix").

It follows on from [specs/ui_ux_remediation_plan.md](../specs/ui_ux_remediation_plan.md), the 2026-10-24 plan, which is done. That plan built the layers and helpers listed below (`Remote<T>`, `useRemote`, `AnnouncerProvider`, `ConfirmDialog`, `StateView`). This plan reuses them.

All paths below are relative to `weebot-ui/src`. Audit line numbers were taken on 2026-11-03 and may have shifted a line or two since. Before editing a finding, confirm it against the current code.

Fact checked while planning: the backend's `cost_per_1k_tokens` values really are per 1K tokens (`weebot/config/model_catalog.py`: `0.006`, `0.0014`). So `app/models/page.tsx:73` (`× 1000`) shows the price per 1M tokens, and only the label is wrong.

## The UI architecture this plan keeps

The frontend already has clear layers. Every fix goes in the lowest layer that owns the behaviour, so the fix is made once and not copied into every caller.

| Layer | Path | Owns | Paradigm already in use |
|---|---|---|---|
| Types | `types/` | Data shapes: `Remote<T>`, statuses | Discriminated unions, so impossible states cannot be represented |
| Pure core | `lib/` | Rules with no React or DOM: reducer, endpoints, announce policy, scroll maths | Functional core: pure functions, unit-tested |
| Hooks | `hooks/` | Bridges to the outside world: fetch, storage, media queries, WebSocket | Imperative shell (`useSyncExternalStore`, `useRemote`) |
| Providers | `providers/` | App-wide singletons: theme, toast, announcer, event stream, shell slots | Context as Mediator and Singleton |
| Primitives | `components/ui/` | Look and behaviour of base controls (base-ui + cva) | Compound components, variant maps |
| Shared composites | `components/common/` | `ConfirmDialog`, `StateView`, `StatusBadge`, `statusInfo` | Composition; Strategy table in `status.ts` |
| Features | `components/<feature>/` | Feature views | Presentational components fed by hooks |
| Routes | `app/` | Page wiring, metadata, layout | Container components |

Rules this plan sticks to:

1. **One owner per behaviour.** A default that is wrong everywhere (button `type`, `CardTitle` element, `transition-all`, overscroll) is fixed in `components/ui/`, not at each call site.
2. **Pure logic goes in `lib/` with a unit test.** Formatting, pluralising and date parsing are pure functions, not inline JSX expressions.
3. **External state is read through `useSyncExternalStore`.** That covers storage, media queries and URL state. `Composer.tsx:75-111` and `hooks/useMediaQuery.ts` already do this. The plan extracts that pattern; it does not invent a new one.
4. **Remote data stays `Remote<T>` via `useRemote`.** A swallowed fetch error becomes `status: "error"` and is rendered by `StateView`.
5. **There is one announcer.** `AnnouncerProvider` is the Mediator between events and assistive technology. Transient news goes through `useAnnounce()` / `lib/announce.ts`. The conversation log stays `aria-live="off"`, by design.
6. **No new runtime dependency** unless a measured check fails (see Phase 8).

## Design patterns chosen per module

| Module | Problem from the audit | Pattern | Why this one |
|---|---|---|---|
| `lib/format.ts` (new) | `$`+`toFixed`, bare `toLocaleString()`, `slice(11,19)`, manual plurals, dead "Invalid Date" catches | Pure functions over a **Flyweight** cache of `Intl.*` formatters, keyed by locale and options | `Intl` objects are expensive to build and safe to share. Pure functions are trivial to test |
| `hooks/useIntlContext.ts` (new) | `suppressHydrationWarning` hides server/client locale and time-zone mismatches | `useSyncExternalStore` with a **server snapshot** (`en-US`, `UTC`) and a client snapshot (`navigator.language`, resolved time zone) | Hydration matches exactly, then the client re-renders in the user's locale. No `headers()` call in the root layout, so routes stay static |
| `lib/storage.ts` (new) | Six files read `localStorage`/`sessionStorage` directly; three have no try/catch; two read storage in `useState` initialisers | **Adapter** (safe read/write that never throws) plus a typed key registry; `hooks/useStoredValue.ts` as an **Observer** store, generalised from `Composer.tsx:75-111` | One place handles privacy mode and quota errors. Same-tab listeners plus the `storage` event keep every reader in sync |
| `lib/settings.ts` (new) | `getApiBase` logic copied in `lib/api.ts:7`, `ConnectionStatus.tsx:15`, `EventStreamProvider.tsx:91`, `ops/page.tsx:43` | **Repository** for connection settings (`backendUrl()`, `wsUrl()`, `apiKey()`), built on `lib/storage.ts` | Deletes three copies of the same logic, so one fix reaches every reader |
| `hooks/useAsyncAction.ts` (new) | Approve, Approve plan, Interrupt, Continue, Save Key, Delete: double-send, no pending or resolved state | A small **state machine** `idle → pending → done | error`, as a discriminated union like `Remote<T>`. Re-entry is blocked with a ref, so two clicks in the same tick cannot both fire | A state flag alone lets the second click through before the re-render. A ref guard does not |
| `components/ui/button.tsx` | No default `type`; no `loading`; `lg` misses the coarse-pointer target | Safe defaults in the primitive (`type="button"`); a `loading` prop that sets `aria-busy`, shows a spinner and blocks clicks with `aria-disabled` | `aria-disabled` keeps focus on the button. Plain `disabled` drops focus, which is the `RoleModelsPanel.tsx:56` bug |
| `components/common/ConfirmDialog.tsx` | Confirm closes at once and cannot show a pending or failed action | Extend it: `onConfirm` may return a Promise. The dialog stays open with a loading button while pending, closes on success, and shows the error inline on failure | Every destructive action gets the same safe flow from one component |
| `components/ui/card.tsx`, `alert.tsx` | `CardTitle` and `AlertTitle` are `div`s; `Alert` is always `role="alert"` | **Polymorphic slot**: base-ui's `render` prop / `useRender`, with a semantic default (`h2` for `CardTitle`, `h3` for `AlertTitle`). `role` derives from `variant` (destructive: `alert`; others: `status`) | Fixes the heading outline on every page at once. Callers can still choose the level |
| `providers/ThemeProvider.tsx` + `app/layout.tsx` + `globals.css` | No `color-scheme` or `theme-color` | Declarative CSS first (`color-scheme` on `:root` / `.dark`), a `viewport` export with `themeColor` per media query, and the provider syncing `<meta name="theme-color">` when the user overrides the theme | CSS covers first paint; JS only handles the override |
| `hooks/useUrlState.ts` (new) | Tab, search and dock state is lost on reload and cannot be shared | The URL is the **single source of truth**: `useSearchParams` to read, `router.replace(…, { scroll: false })` to write; tabs become controlled components | Back/forward and deep links work. No state is duplicated in React |
| `lib/session-reducer.ts` | `ToolsTab.tsx:14,21` clones a Map per event and reverses it per render | Move the tool-call index into the existing **reducer** state (pure) | Derived state belongs in the reducer that already folds events. `ToolsTab` becomes a plain view |
| Live lists (ops log, LiveFeed, debug, RecentActions) | `key={i}` / `${timestamp}-${index}` on sliding windows remount every row | Stable identity assigned once **at ingestion** (a monotonic counter in the producer) | Keys must describe the item, not its position |
| Charts (`CostChart`), `PlanVisualizer` | Colour-only meaning, JS animation ignores reduced motion, canvas unreachable by keyboard | **Text alternative** next to every graphic: `role="img"` + summary `aria-label` + an `sr-only` table (charts); the existing `PlanChecklist` is the accessible equivalent of the graph. `isAnimationActive` / `animated` follow `useMediaQuery("(prefers-reduced-motion: reduce)")` | A11y comes from a parallel text view, not from making SVG internals focusable |
| `RecentActions.tsx:128` | Hand-made modal with no dialog semantics | **Reuse** `components/ui/dialog.tsx` (adapter over base-ui) | Focus trap, Escape, focus return and scroll lock come for free |

## Findings resolved by design, not by the literal fix

These audit lines are fixed, but not the way the audit line suggests. The reason in each case is the existing architecture.

- **Timeline rows are not given `role="status"` or `role="alert"`** (GapMarkerRow, ErrorRow, DoneRow, MessageRow send state, ToolCallRow status). The log is `aria-live="off"` on purpose (`lib/announce.ts` header): a busy stream would otherwise be read row by row. Instead:
  - `announcementFor()` in `lib/announce.ts` gets cases for gap markers (`"N events were dropped"`).
  - `useComposer` announces send failure (`"Message not sent. Retry Sending is available."`).
  - Errors, failed steps, failed tools and `done` are already announced.
  - Running and done tool statuses stay silent on purpose: announcing them would be the noise the design avoids. Extend `lib/announce.test.ts` to cover the new cases.
- **Plan progress "N of M done"** (`PlanChecklist.tsx:27`) is already announced per step by `announcementFor` (`Step completed: …`). Do not add a second live region. Give the bar `role="progressbar"` with `aria-valuenow`/`aria-valuemax` instead of `aria-hidden`, so it can be read on demand.
- **Rail and dock open state in the URL** (`ConsoleShell.tsx:32-37`): skipped. Panel visibility is per-device chrome, not shareable state, and the URL would change on every toggle. The dock **tab** does go in the URL (Phase 7).
- **Interrupt gets no confirm dialog** (`RunControls.tsx:36-45`). Interrupt is the emergency stop for a runaway agent, and a confirm step slows it down. It gets the pending guard and a resolved state, and **Continue** is its undo. First verify in the backend that Continue resumes an interrupted run. If it does not, use `ConfirmDialog` instead.
- **Approve once / Decline get no confirm.** They are the answer the user was asked for. They get the pending guard and a resolved state ("Approved" / "Declined" replaces the buttons). Only **Always allow** gets a confirm, because it grants a lasting permission.
- **Composer unsaved-draft warning** (`Composer.tsx:149-156`): skipped. The draft already persists in sessionStorage per session (`hooks/useComposer.ts:13`), so nothing is lost when the user navigates away.

## Phases

Each phase is one PR. Phases 0-2 must land first, in order. Phases 3-9 depend on 1 and 2 but are independent of each other, and can run in parallel when they touch different files (the file sets are listed in each phase). Phase 10 runs last.

Every phase ends with: `npm run lint`, `npx tsc --noEmit`, `npm test` (vitest) and `npm run test:e2e` in `weebot-ui/`, all green.

### Phase 0: models page cost label (bug, ~3 lines)

- `app/models/page.tsx:65`: change the label to "Cost per 1M tokens". Keep `× 1000`, which is correct for a per-1M display.
- `app/models/page.tsx:73`: format the figure with `formatCurrency` once Phase 1 lands. Until then, leave the expression unchanged.
- Test: a component test renders one model with `cost_per_1k_tokens: 0.006` and expects "per 1M" next to "$6.00".

### Phase 1: foundations in `lib/` and `hooks/` (no visible change)

New files, each with a unit test next to it:

1. `lib/format.ts` with these functions:
   - `formatCurrency(n, ctx, { precision })`
   - `formatNumber(n, ctx)` and `formatPercent(n, ctx)` (clamps and rounds)
   - `formatDateTime(iso, ctx, style)` and `formatTime(iso, ctx)`, both returning `null` for an invalid date via `Number.isNaN(d.getTime())`
   - `formatRelative(iso, ctx)` (`Intl.RelativeTimeFormat`, replacing date-fns `formatDistanceToNow`)
   - `plural(n, ctx, { one, other })` (`Intl.PluralRules`)

   All of them share one `Map` cache of formatters (Flyweight).
2. `hooks/useIntlContext.ts`: `useSyncExternalStore` returning `{ locale, timeZone }`. The server snapshot is `{ "en-US", "UTC" }`; the client snapshot is `navigator.language` and `Intl.DateTimeFormat().resolvedOptions().timeZone`. A `shortcut:` comment notes that non-en-US users see one en-US frame at hydration, and that the fix is a locale cookie if that ever matters.
3. `lib/storage.ts`:
   - `STORAGE_KEYS` registry: `weebot_theme`, `weebot_backend_url`, `weebot_ws_url`, `weebot_api_key`, `weebot_execution_mode`, and the draft-key prefix.
   - `readStored(area, key)`, `writeStored(area, key, value | null)` and `subscribeStored(area, key, listener)`. All are wrapped in try/catch and never throw.
4. `hooks/useStoredValue.ts`: `useSyncExternalStore(subscribeStored, read, () => serverFallback)`. Extract it from `Composer.tsx:75-111`, then make Composer use it.
5. `lib/settings.ts`: `backendUrl()`, `wsUrl()`, `apiKey()`, `setApiKey()`, `setConnection()`. These replace `lib/api.ts:7-20`, `ConnectionStatus.tsx:14-25`, `EventStreamProvider.tsx:80-92` and `ops/page.tsx:43`.
6. `hooks/useAsyncAction.ts`: `run(...args)` returns the promise. State is `{ status: "idle" | "pending" | "done" | "error", error? }`, guarded by a ref. `reset()` is optional.
7. `hooks/useUrlState.ts`: `useUrlState(key, fallback)` returns `[value, setValue]`, writes with `replace`, and removes the param when it equals the fallback.
8. `hooks/usePageVisible.ts`: `useSyncExternalStore` on `visibilitychange`. It pauses the `ConnectionStatus.tsx:89-102` poll and can be passed to `useRemote` callers that poll.
9. Reduced motion: no new hook. Use `useMediaQuery("(prefers-reduced-motion: reduce)")`.

Tests: one formatter cache hit; invalid ISO returns `null`; `plural` gives `en` one/other; storage read/write survive a throwing `Storage` stub; `useAsyncAction` fires once on a double `run()` in the same tick; `useUrlState` round-trips.

### Phase 2: primitives and global CSS (`components/ui/`, `app/layout.tsx`, `app/globals.css`, `providers/`)

- `button.tsx:43`: default `type="button"`; add a `loading` prop (spinner with `aria-hidden`, `aria-busy`, `aria-disabled`, click blocked). `:23`: add `pointer-coarse:min-h-11` to `lg`.
- `card.tsx:36`: `CardTitle` renders `h2` by default and takes a `render` prop to change the level. Then audit the heading levels per page. Every route gets one `h1`, either from `AppBar` (`shell/AppBar.tsx:50-52`: always render an `h1`, falling back to the route name) or from the page. Section cards are `h2`; nested cards are `h3`. That covers `PlanVisualizer.tsx:157`.
- `alert.tsx:30`: `role` comes from `variant` (`destructive` → `alert`, others → `status`) and can be overridden. `:39`: `AlertTitle` becomes `h3` via `render`.
- Remove `transition-all`:
  - `badge.tsx:8`: `transition-colors`.
  - `tabs.tsx:62`: `transition-[color,background-color,box-shadow]`.
  - `progress.tsx:48`: animate `transform: scaleX()` with `origin-left` instead of `width`.
  - `ToastProvider.tsx:126`: `transition-[opacity,transform]`.

  Apply the same scaleX treatment to `PlanChecklist.tsx:30` and `TrustBar.tsx:60-62`. `TrustBar` also gets `role="progressbar"` or `aria-hidden` plus a text value.
- Add `overscroll-contain` to the dialog (`:56`, and `DialogSheet :97` with `overflow-y-auto`), the dropdown popup (`:40`, plus `max-h-(--available-height) overflow-y-auto`), the select popup (`:70`) and the scroll-area viewport (`:35`). Every scroll surface built on these inherits it. Surfaces not built on them get the class directly: `CommandPalette.tsx:100`, `SessionRail.tsx:53`, `Dock.tsx:30`, `LiveFeed.tsx:50`.
- `dialog.tsx:56`: `max-h-[calc(100dvh-2rem)] overflow-y-auto`.
- `select.tsx:44`: `focus:` → the `focus-ring` utility. `:25`: `SelectValue` gets `truncate min-w-0`.
- `tabs.tsx:77`: `TabsContent` gets `focus-ring` in place of the bare `outline-hidden`.
- `globals.css`:
  - `color-scheme: light` on `:root` (`:189`) and `color-scheme: dark` on `.dark` (`:246`).
  - On `body` (`:296`): `touch-action: manipulation` and `-webkit-tap-highlight-color: transparent`.
  - Delete the `@utility text-balance` redefinition (`:106`); Tailwind v4 ships `text-balance`/`text-pretty`. Apply `text-balance` to `h1`/`h2` in the base layer.
  - Add `pb-safe` / `bottom-safe` utilities: `env(safe-area-inset-bottom)`.
- `app/layout.tsx:15`: `export const viewport = { themeColor: [{ media: "(prefers-color-scheme: light)", color: … }, { media: "(prefers-color-scheme: dark)", color: … }], colorScheme: "dark light" }`. The colours come from the `--background` tokens.
- `ThemeProvider.tsx:51-54`: on change, set `document.documentElement.style.colorScheme` and update `meta[name=theme-color]`. Read and write through `lib/storage.ts`.
- `ToastProvider.tsx`:
  - `:84-88`: `inset-x-4 bottom-[calc(1rem+env(safe-area-inset-bottom))] sm:left-auto sm:right-4 sm:w-96`; no `w-full` overflow.
  - Move `aria-live="polite"` to the persistent container (`:84`) and take it off each toast (`:118-120`).
  - `:148-154`: the dismiss button becomes `Button size="icon-xs"`, which gets the coarse-pointer target, the focus ring and an `aria-hidden` icon. Do the same for the action button at `:137`.
- `ConfirmDialog.tsx`: `onConfirm` returns `void | Promise<void>`. Use `useAsyncAction` internally, a `loading` confirm button, and an inline error that keeps the dialog open.

Tests: Button renders `type="button"` and blocks a click while `loading`; ConfirmDialog stays open and shows the error when `onConfirm` rejects; ThemeProvider sets `style.colorScheme`.

### Phase 3: mechanical sweeps (one pass per concern, split by file group)

These are rule-driven edits with no design choice. Split them by folder so parallel workers never touch the same file. Each sweep comes from the audit lines listed under its file in the coverage table below.

1. **Formatting → `lib/format.ts`.** Covers:
   - `app/models/page.tsx:73,84-85`
   - `app/ops/page.tsx:228,232-233,271-272,349`
   - `app/sessions/page.tsx:91`
   - `CostChart.tsx:55-175`, including currency `tickFormatter` and date ticks at `:96,100`
   - `MetricsPanel.tsx:48,61,72`
   - `TrustBar.tsx:47,55`
   - `CostTab.tsx:47-64`
   - `GapMarkerRow.tsx:8`, `PlanReviewCard.tsx:22-23`
   - `LiveFeed.tsx:30-33`, `RecentActions.tsx:35`

   Delete every `suppressHydrationWarning` that only covered a formatted number, and the dead "Invalid Date" catches. Add `tabular-nums` to every counter and KPI (`ops/page.tsx:226-243`, `MetricsPanel.tsx:30-96`, `CostChart`, `ConversationPane.tsx:196-206`, `ToolCallRow.tsx:105`, `LiveFeed.tsx:70`). The time column at `LiveFeed.tsx:70` loses `min-w-[60px]` and uses `tabular-nums` with a width in `ch`.
2. **Storage → `lib/storage.ts` / `lib/settings.ts`.** Covers:
   - `app/settings/page.tsx:15-29`: `useStoredValue`; the initialiser no longer reads storage.
   - `ConnectionStatus.tsx:15,46-53`
   - `ops/page.tsx:43`
   - `lib/api.ts`, `EventStreamProvider.tsx:80-92`
   - `Composer.tsx:75-111`, `ThemeProvider.tsx:19,39`

   Leave `THEME_INIT_SCRIPT` in `layout.tsx:22` inline: it runs before React and already has try/catch.
3. **Copy.** Change `...` to `…` in:
   - `StateView.tsx:30`
   - `sessions/[id]/page.tsx:80`, `PlanTab.tsx:82`
   - `BehaviorPanel.tsx:53`, `LiveFeed.tsx:41,56`
   - `RecentActions.tsx:165`, `TrustBar.tsx:30`
   - `ConnectionStatus.tsx:108,157,170`
   - `debug/page.tsx:59`, `Composer.tsx:64`

   Change straight to curly quotes in `StateView.tsx:12,29`, `PlanTab.tsx:94-96` and `Composer.tsx:64`. Retitle these labels:

   | Location | Old label | New label |
   |---|---|---|
   | `AppBar.tsx:81,123` | "New session" | "New Session" |
   | `SessionRail.tsx:70-77` | "New" | "New Session" |
   | `MessageRow.tsx:38` | "Retry" | "Retry Sending" |
   | `behavior/page.tsx:38-40` | "New Session" | "Generate Demo ID" |
   | `ConnectionStatus.tsx:131` | "Clear" | "Remove API Key" |
   | `ops/page.tsx:328` | "Clear" | "Clear Log" |
4. **Decorative icons get `aria-hidden`.** Covers:
   - `models/page.tsx:64`, `MetricsPanel.tsx:27,45,58,69,80,93`
   - `ConnectionStatus.tsx:107,117,123,142`, `PlanReviewCard.tsx:20`
   - `CodeBlock.tsx:42,44`, `ToastProvider.tsx`
   - `CostChart.tsx:165-170` swatches

   Remove the duplicate Circle icon at `PlanReviewCard.tsx:36`. `models/page.tsx:56` tier dot gets visible or `sr-only` tier text.
5. **`translate="no"` on identifiers.** Covers:
   - `models/page.tsx:58`, `StatusEventRow.tsx:48,58`
   - `ToolCallRow.tsx:56-60`, `SessionRail.tsx:143`
   - `CostTab.tsx:62`, `ToolsTab.tsx:32-33`
   - `BehaviorPanel.tsx:79`, `CodeBlock.tsx:50`
6. **Overflow.**
   - `min-w-0` + `break-words` on `MessageRow.tsx:16-26`, `StepRow.tsx:8`, `StatusEventRow.tsx:15-18,26,49,83`, `ConversationPane.tsx:218` and `PlanReviewCard.tsx:37`.
   - `truncate` + `title` on `sessions/page.tsx:83-88`, `models/page.tsx:54-58`, `LiveFeed.tsx:71`, `RecentActions.tsx:119,135`, `ops/page.tsx:357`, `PlanVisualizer.tsx:77`, `CostTab.tsx:62` and `ToolsTab.tsx:32-33`.
   - Replace `slice(-40)` with a CSS `truncate` and `direction: rtl` for path tails.
   - `minmax(0,1fr)` grid on `BehaviorPanel.tsx:72`; fix the `w-3.5 w-4` conflict on `LiveFeed.tsx:69` and give the event type a text label.
7. **Theme tokens.** Replace `bg-white/5` and `bg-white/10` (`LiveFeed.tsx:66`, `RecentActions.tsx:108`) with `bg-muted`. Replace `text-cyan-500` (`LiveFeed.tsx:27`) with a status token. `CodeBlock.tsx:31-39` and `debug/page.tsx:42-59` get hex colours → tokens; the debug light-theme contrast is part of this. `CostChart.tsx:36,113,137` get hex colours → `var(--chart-N)` tokens, added to `globals.css` if missing.
8. **Skeleton and spinner semantics.** `ops/page.tsx:63`, `LazyPlanVisualizer.tsx:12` and `sessions/[id]/page.tsx:88` get one `role="status"` wrapper with `sr-only` "Loading …" text, instead of an `aria-label` on a role-less element. `TrustBar.tsx:30` and `StateView.tsx:30` loading text get the same wrapper.

### Phase 4: announcements and live regions

Follow the policy in "Findings resolved by design". Other changes:

- `lib/announce.ts`: add a `gap` case (`GapMarkerRow.tsx:5-9`). `useComposer` announces send failure (`MessageRow.tsx:27-44`, `Composer.tsx:171-178`). Announce the mode change when the user flips Auto (`Composer.tsx:171`).
- Status outside the timeline is announced on **transition only**, not on mount, via `useAnnounce` in an effect keyed on the status. This covers:
  - `AppBar.tsx:56-65` Live/Offline
  - `BehaviorPanel.tsx:46` Live/Polling
  - `ops/page.tsx:324-326` WebSocket status
  - `MetricsPanel.tsx:23`: threshold crossings only; the polled values themselves stay silent
  - `ToolsTab.tsx:43-60`: failure only, through the existing `tool` case
- One-shot feedback is announced: "Saved" (`settings/page.tsx:78-83`), "Copied" (`CodeBlock.tsx:46`, `ToolCallRow.tsx:91`), "Waiting for events…" / "Agent is working…" (`ConversationPane.tsx:152,186-191`), and the plan load error (`PlanTab.tsx:89`). The plan load error renders through `StateView`, which owns the error role, with a retry button.
- Real logs get `role="log"` (polite by default; this is their purpose): `ops/page.tsx:339-363`, `LiveFeed.tsx:50`, `debug/page.tsx:48,61`.
- `ConnectionStatus.tsx:104-180`: only the error state is `variant="destructive"` (`role="alert"`). Connecting and connected become `status`. Replace the stale "Retrying connection…" text (`:168-172`) with the next retry time, or "Retrying now".
- Form validation errors get `role="alert"` inline: `ops/page.tsx:431`, and the new validation messages from Phase 6.

Tests: extend `lib/announce.test.ts`. Add a component test that toggling AppBar Live → Offline calls `announce` once and the mount calls it zero times.

### Phase 5: high-stakes actions (`useAsyncAction` + `ConfirmDialog`)

| Action | File | Guard | Confirm / undo | Resolved state |
|---|---|---|---|---|
| Approve once, Decline | `StatusEventRow.tsx:53-62` | `useAsyncAction`, `loading` button | None (it is the requested answer) | Buttons replaced by "Approved" / "Declined" text |
| Always allow | `StatusEventRow.tsx:53-62` | Same | `ConfirmDialog` naming the tool and that the grant lasts beyond this session | "Always allowed: `<tool>`" |
| Approve plan | `PlanReviewCard.tsx:43` | Same | None | Card becomes read-only, "Plan approved" |
| Request changes (new) | `PlanReviewCard.tsx:46-48` | n/a | n/a | Focuses the composer via the existing shell slot or ref (no new backend endpoint). Replaces the "use the composer below" text |
| Interrupt | `RunControls.tsx:36-45` | Same | Continue is the undo (verify first, see above) | "Interrupted"; error at `:28` gets a next step ("Try again, or reload the session") and no raw `e.message` |
| Continue | `ConversationPane.tsx:211-229` | Same; `h-7` → `size="sm"` so the coarse-pointer target applies | None | Hidden once the run resumes |
| Auto mode on | `Composer.tsx:192-197` | n/a | `ConfirmDialog` when **enabling** only ("Auto skips approval prompts for tool calls") | Mode chip; `aria-label` matches the visible "Auto" (`:189`) |
| Remove API Key | `ConnectionStatus.tsx:131-132` | n/a | `ConfirmDialog`, destructive | Toast "API key removed" |
| Save Key | `ConnectionStatus.tsx:163` | `loading` | n/a | Empty key shows an inline validation error, not a silent no-op (`:68`) |
| Delete session | `sessions/page.tsx:130` | `ConfirmDialog` async (Phase 2) | Already confirms | Error at `:34-38` gets a next step |
| Clear Log | `ops/page.tsx:328-333` | n/a | Undo via `ToastAction` (keep the cleared lines for 5 s) | Empty log state |
| RoleModels change | `RoleModelsPanel.tsx:56` | `aria-busy` + `aria-disabled` instead of `disabled` (keeps focus) | n/a | Error at `:39` gets a next step |

Tests: a component test for StatusEventRow (a double click sends one reply, then "Approved" shows) and for Composer (enabling Auto opens the confirm, disabling does not).

### Phase 6: forms

Every text entry that submits becomes a `<form onSubmit>` with a submit `Button type="submit"`. Enter then works natively, and `isComposing` is handled by the browser. This replaces the hand-written keydown handlers.

| Form | File | Input attributes | Extra |
|---|---|---|---|
| Composer | `Composer.tsx:201-217` | `name="message"`, `autoComplete="off"`, `enterKeyHint="send"`, `field-sizing-content` + `max-h` (`:208`) | Keep Enter = send, Shift+Enter = newline as a keydown that calls `form.requestSubmit()`. Spinner on send via `loading` (`:214`). Safe-area padding (`:159`) |
| Settings | `settings/page.tsx:51-83` | `name`, `type="url"`, `autoComplete="off"`, `spellCheck={false}`; validation with `new URL()` and an inline `role="alert"` error | `beforeunload` guard while dirty. `<Label>` without a control (`:97,109,121`) becomes plain text or `dt`. Scrollable `<pre>` gets `tabIndex={0}` + `aria-label` (`:100,112,124`). Drop `ExternalLink` on the internal link (`:147`) |
| API key | `ConnectionStatus.tsx:155-162` | Visible `<Label htmlFor>`, `name="api-key"`, `type="password"`, `autoComplete="off"`, `spellCheck={false}` | The form fixes Enter during IME composition |
| Plan ID | `ops/page.tsx:415-421` | `Input` + `Label`, `name`, `spellCheck={false}` | Submit button `loading`; the guard blocks duplicate fetches (`:420`); `!result.ok` becomes an error state (`:390-400`) |
| Session ID | `behavior/page.tsx:31-37` | `name`, `autoComplete="off"`, `spellCheck={false}` | n/a |
| Override note | `RecentActions.tsx:140-141` | `<Label htmlFor>` + textarea `id`/`name` | Inside the new `Dialog` (Phase 9) |
| Session search | `SessionRail.tsx:32-39` | `name="q"`, `type="search"`, `autoComplete="off"` | URL state in Phase 7 |
| Command palette | `CommandPalette.tsx:72` | `autoComplete="off"`, `spellCheck={false}` | Shortcut `span` → `<kbd>` (`:120`) |
| Debug | `debug/page.tsx:22-37` | `htmlFor`/`id`; raw buttons → `Button` | Dev-only, lowest priority |

### Phase 7: URL state (`useUrlState`)

- Dock tab: `?dock=plan|tools|cost|trust` (`dock/Dock.tsx:23`). This fixes the reset when the sheet remounts.
- Ops tab: `?tab=` (`ops/page.tsx:143`). Behavior tab: make the existing `?tab=` read two-way (`behavior/page.tsx:157`).
- Session search: `?q=`, written with a debounced `replace` (`SessionRail.tsx:32-39`). `filterSessions` in `lib/sessions.ts` stays the pure filter.
- Wrap each `useSearchParams` consumer in a `Suspense` boundary, as Next 16 requires for static routes.
- Rail and dock open state: skipped, see "resolved by design".

Tests: an e2e that opens `/sessions/x?dock=cost`, sees the Cost tab, reloads and still sees it.

### Phase 8: long lists and performance

The CSS-first approach needs no new dependency:

1. Add a `content-visibility: auto` utility with `contain-intrinsic-size`. Apply it to rows and cards in `sessions/page.tsx:76`, `models/page.tsx:51`, the `ConversationPane.tsx:173-184` timeline, `SessionRail.tsx:125-148` and `ToolsTab`. This skips off-screen layout and paint. It is not virtualisation, but the lists here are at most a few hundred items.
2. `sessions/page.tsx:18`: replace the fixed `limit: "100"` with a "Load More" button, if the `/sessions` endpoint accepts an offset or cursor. Check `weebot/interfaces/web` first. If it does not, keep 100 and show "Showing the latest 100".
3. `ToolsTab.tsx:14,21`: move the tool-call index into `lib/session-reducer.ts` state. Add a reducer test.
4. Stable keys at ingestion: `ops/page.tsx:346`, `LiveFeed.tsx:63`, `RecentActions.tsx:99,104`, `debug/page.tsx:48`.
5. `ops/page.tsx:113`: replace the `scrollIntoView({ behavior: "smooth" })` on every event with the existing `useStickToBottom` hook. It only follows when the reader is at the bottom, and it scrolls `auto` under reduced motion.
6. `ConnectionStatus.tsx:89-102`: pause the poll while `usePageVisible()` is false.
7. `ResponsivePanel.tsx:32`: pass `serverValue={true}` (desktop) to `useMediaQuery`, so desktop hydrates without mounting the Dialog tree first.

**Gate for adding `@tanstack/react-virtual`:** only if `e2e/perf.spec.ts`, extended with a 1,000-event timeline, still fails its budget after steps 1-5. In that case, virtualise the timeline only.

### Phase 9: per-module leftovers

- **`CostChart.tsx`:**
  - Wrap each chart in `figure` + `role="img"` + an `aria-label` summary, with an `sr-only` data table (`:92,126`).
  - `isAnimationActive={!reducedMotion}` (`:113,128`).
  - Pie legend shows the percentage as text, so meaning is not colour-only.
  - Empty state through `StateView` (`:126`).
  - The "Last N days" title derives from the data (`:89`).
  - Legend gets `truncate min-w-0` (`:165-170`).
- **`MetricsPanel.tsx:62`:** clamp the `Progress` value to 0-100 inside `Progress` itself (primitive owns it).
- **`PlanVisualizer.tsx`:**
  - Status text in each node (`sr-only`), so it is not icon+colour only (`:36-50`).
  - `animate-spin` → `motion-safe:animate-spin`; `animated` edges follow reduced motion (`:42,105,122`).
  - `h-[500px]` → `h-[min(500px,70dvh)]` (`:154`).
  - Canvas wrapper becomes `role="img"` with `aria-label` "Plan graph, N steps. The checklist lists the same steps." (`:160-179`).
- **`RecentActions.tsx`:** the modal (`:128`) uses `components/ui/dialog`; raw buttons (`:87,103`) become `Button`; errors (`:71,75`) get a next step.
- **`CodeBlock.tsx`:**
  - try/catch on `clipboard.writeText` with a failure message (`:24`).
  - Clear the timeout on unmount (`:27`); same fix in `ToolCallRow.tsx:91`.
  - Copy button shows even without a `filename` (`:32`).
  - `tabIndex={0}` on the scroll region (`:50`).
- **`ToolCallRow.tsx:44-48`:** `aria-controls` on the expand button (`type` is already covered by the Button default once it uses `Button`). **`ToolsTab.tsx:29-36`:** `ul`/`li`.
- **`ConversationPane.tsx:93`:** a fetch failure becomes a `Remote` error with retry, not just `console.warn`. **`sessions/[id]/page.tsx:64-67`:** same.
- **`ConversationPane.tsx:196-206`:** jump button gets a safe-area offset.
- **`ops/page.tsx`:**
  - `122-124`: fetch failure shows an error, not "No sessions currently running".
  - `264-274`: session ID becomes `Link` to `/sessions/{id}`.
- **`behavior/page.tsx`:**
  - `95-106`: download checks `res.ok`, shows a toast on failure and calls `URL.revokeObjectURL`.
  - `78,138`: unique `aria-label`s, plus `role="region"` or `figure`.
- **`RoleModelsPanel.tsx`:**
  - `53,58`: replace the native `<select>` with the house `Select` primitive, which also fixes the dark-mode options and the `focus:` ring.
  - `60`: "Default · undefined" becomes "Default", or the model name when present.
  - `76`: map `planner_sub` to a readable label in the role-label table.
- **`AppBar.tsx`:** `:72` aria-label starts with the visible text ("K, open command palette"); `:98-107` gets `aria-expanded`.
- **`ConsoleShell.tsx:31`:** toolbar buttons keep `size="sm"`, which already carries `pointer-coarse:min-h-11`. Confirm on a touch emulator, then close.
- **`debug/page.tsx:14`:** `Date.now()` moves out of the `useState` initialiser into an effect.

### Phase 10: regression guards and verification

1. **Lint guards.** These ratchet like the repo's other gates: add only, never loosen. Use ESLint `no-restricted-syntax` in `eslint.config.mjs`, scoped to `src/**` except `lib/format.ts`:
   - JSX text containing `...`
   - String literals containing `transition-all`
   - `.toFixed(` and `.toLocaleString(` outside `lib/format.ts`
   - Direct `localStorage` / `sessionStorage` outside `lib/storage.ts` and the layout's init script
2. **`e2e/a11y.spec.ts`** already runs axe on every route in both themes at 375 and 1280 px. Add the `heading-order` and `region` rules to the check. Add one assertion that `getComputedStyle(document.documentElement).colorScheme` matches the theme.
3. New e2e cases:
   - Approve double click sends one request.
   - Deep-link `?dock=`.
   - Toast fits within 375 px.
   - Composer submit through the form.
4. Manual pass in the browser preview, dark and light, at 375 and 1280 px:
   - Native scrollbars and select options are dark in dark mode.
   - Headings outline correctly.
   - With reduced motion emulated, nothing animates.
5. Full gate: `npm run lint && npx tsc --noEmit && npm test && npm run test:e2e` in `weebot-ui/`, then `make check` at the repo root (tasks index drift).

## Execution notes

- Subagents follow the memory rule: `model: "haiku"` for the Phase 3 mechanical sweeps and the Phase 6 attribute edits; `model: "sonnet"` for Phases 1, 2, 4, 5, 7, 8 and 9. Never inherit the parent model.
- Phase 3 can run as up to four parallel workers over disjoint folders:
  1. `app/`
  2. `components/conversation` + `components/shell`
  3. `components/behavior`, `dashboard`, `dock` and `plan`
  4. `components/ui` leftovers, `common`, `code`, `models` and `providers`
- Each worker starts by re-reading its audit lines, because they may have shifted.
- Commit per phase with Conventional Commits (`fix(ui): …`, `refactor(ui): …`).
- After writing or changing this file, run `python scripts/gen_tasks_index.py` so `tasks/_index.md` does not drift.

## Coverage: every audit file to its phases

| Audit file | Phases |
|---|---|
| app/layout.tsx | 2 |
| app/globals.css | 2 |
| app/(console)/sessions/[id]/page.tsx | 3.3, 3.8, 9 |
| app/sessions/page.tsx | 3.1, 3.6, 5, 8 |
| app/models/page.tsx | 0, 3.1, 3.4, 3.5, 3.6, 8 |
| app/settings/page.tsx | 3.2, 4, 6 |
| app/behavior/page.tsx | 3.3, 6, 7, 9 |
| app/debug/page.tsx | 3.3, 3.7, 4, 6, 8, 9 |
| app/ops/page.tsx | 3.1, 3.2, 3.3, 3.6, 3.8, 4, 5, 6, 7, 8, 9 |
| providers/ThemeProvider.tsx | 2, 3.2 |
| providers/ToastProvider.tsx | 2, 3.4 |
| components/ui/* (alert, badge, button, card, dialog, dropdown-menu, progress, scroll-area, select, tabs) | 2 |
| components/common/StateView.tsx | 3.3, 3.8 |
| components/code/CodeBlock.tsx | 3.4, 3.5, 3.7, 4, 9 |
| components/command/CommandPalette.tsx | 2, 6 |
| components/dashboard/CostChart.tsx | 3.1, 3.4, 3.7, 9 |
| components/dashboard/MetricsPanel.tsx | 3.1, 3.4, 4, 9 |
| components/models/RoleModelsPanel.tsx | 5, 9 |
| components/behavior/BehaviorPanel.tsx | 3.3, 3.5, 3.6, 4 |
| components/behavior/LiveFeed.tsx | 2, 3.1, 3.3, 3.6, 3.7, 4, 8 |
| components/behavior/RecentActions.tsx | 3.1, 3.3, 3.6, 3.7, 6, 8, 9 |
| components/behavior/TrustBar.tsx | 2, 3.1, 3.3, 3.8 |
| components/conversation/GapMarkerRow.tsx | 3.1, 4 |
| components/conversation/MessageRow.tsx | 3.3, 3.6, 4 |
| components/conversation/StepRow.tsx | 3.6 |
| components/conversation/StatusEventRow.tsx | 3.5, 3.6, 4, 5 |
| components/conversation/Composer.tsx | 3.2, 3.3, 4, 5, 6 (draft warning skipped by design) |
| components/conversation/ConversationPane.tsx | 3.1, 3.6, 4, 5, 8, 9 |
| components/conversation/RunControls.tsx | 5 |
| components/conversation/ToolCallRow.tsx | 3.1, 3.5, 4, 9 |
| components/shell/ConsoleShell.tsx | 9 (open state skipped by design) |
| components/shell/ResponsivePanel.tsx | 8 |
| components/shell/AppBar.tsx | 2, 3.3, 4, 9 |
| components/shell/SessionRail.tsx | 2, 3.3, 3.5, 6, 7, 8 |
| components/dock/Dock.tsx | 2, 7 |
| components/dock/CostTab.tsx | 3.1, 3.5, 3.6 |
| components/dock/PlanTab.tsx | 3.3, 4 |
| components/dock/ToolsTab.tsx | 3.5, 3.6, 4, 8, 9 |
| components/plan/LazyPlanVisualizer.tsx | 3.8 |
| components/plan/PlanChecklist.tsx | 2, 4 |
| components/plan/PlanVisualizer.tsx | 2, 3.6, 9 |
| components/ConnectionStatus.tsx | 3.2, 3.3, 3.4, 4, 5, 6, 8 |
| components/PlanReviewCard.tsx | 3.1, 3.4, 3.6, 5 |

Not verified while writing this plan: whether Continue resumes an interrupted run (Phase 5), and whether `/sessions` supports an offset (Phase 8). Each is checked at the start of its phase.
