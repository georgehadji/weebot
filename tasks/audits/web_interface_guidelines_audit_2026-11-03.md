---
status: open
date: 2026-11-03
note: ~250 findings; fix plan in plans/web_guidelines_audit_2026_11_03_fix_plan.md
---

# weebot-ui Web Interface Guidelines audit — 2026-11-03

Against Vercel Web Interface Guidelines (`vercel-labs/web-interface-guidelines/command.md`).
Scope: all non-test `.tsx` / `.css` under `weebot-ui/src` (70 files, ~7k lines). Read-only.
Paths relative to `weebot-ui/src`. ~12 findings spot-verified by hand; all held.
Related (different lens, bug hunts): `tasks/audits/ui_defect_hunt_*.md`.

## Top systemic issues

1. **Bug** — `app/models/page.tsx:65,73` label says "Cost per 1K tokens" but renders `cost_per_1k_tokens * 1000` (a per-1M figure).
2. **No `color-scheme` / `theme-color` anywhere** (`app/layout.tsx`, `globals.css`, `ThemeProvider.tsx`) — native scrollbars, selects, inputs render light in dark theme.
3. **`CardTitle` is a `div`** (`components/ui/card.tsx:36`) — every page has an `h1` and nothing below; `h3`s skip levels.
4. **Async state never announced** — conversation log is `aria-live="off"`; errors, gaps, failed sends, tool status, Live/Offline, "Saved", plan progress have no `role=status|alert`.
5. **One-click high-stakes actions** — Approve once / Always allow / Decline, Approve plan, Interrupt, Continue, Clear API key, Auto mode toggle: no pending guard (double-send), no confirm/undo, no resolved state.
6. **`transition-all`** in `badge.tsx:8`, `progress.tsx:48`, `tabs.tsx:62`, `ToastProvider.tsx:126`.
7. **Number/date formatting not `Intl`** — `$` + `toFixed`, bare `toLocaleString()` masked by `suppressHydrationWarning`, `slice(11,19)` timestamps, manual plurals, no `tabular-nums` on any counter.
8. **Forms** — no `<form>` anywhere; inputs lack `name` / `autoComplete` / `spellCheck={false}` / `enterKeyHint`; several labelled by placeholder only.
9. **Scroll/touch** — no `overscroll-contain` on any scroll surface (dialog, dropdown, select, palette, rail, dock, feeds); no `touch-action: manipulation`; no safe-area insets (composer, toasts).
10. **URL state** — dock tab, ops/behavior tabs, session search, rail/dock open state all local.

## app/

### app/layout.tsx
- app/layout.tsx:15 - no `viewport` export → no `themeColor` / `colorScheme`
- app/layout.tsx:30 - `<html>` has no `color-scheme`

### app/globals.css
- app/globals.css:189,246 - `:root` / `.dark` missing `color-scheme: light|dark`
- app/globals.css:296-299 - body lacks `touch-action: manipulation`, `-webkit-tap-highlight-color`
- app/globals.css:106 - `@utility text-balance` redefines built-in; no heading uses `text-balance`/`text-pretty`

### ✓ app/error.tsx · app/(console)/layout.tsx · app/(console)/page.tsx · app/settings/behavior/page.tsx

### app/(console)/sessions/[id]/page.tsx
- app/(console)/sessions/[id]/page.tsx:88 - spinner svg `aria-label` without `role`; loading not in live region
- app/(console)/sessions/[id]/page.tsx:80 - "Loading session" → "Loading session…"
- app/(console)/sessions/[id]/page.tsx:64-67 - events fetch failure swallowed; empty history, no retry

### app/sessions/page.tsx
- app/sessions/page.tsx:18,76 - `limit: "100"` rendered via plain `.map()`, no virtualization/pagination
- app/sessions/page.tsx:83-88 - long `session.title` no `truncate`/`break-words` (min-w-0 at :81 useless alone)
- app/sessions/page.tsx:34-38 - "Failed to delete session" no next step; confirm button no pending state (:130)
- app/sessions/page.tsx:91 - `formatDistanceToNow` English-only → `Intl.RelativeTimeFormat`

### app/models/page.tsx
- app/models/page.tsx:65,73 - **per-1K label, per-1M value**; hardcoded `$…toFixed(2)`
- app/models/page.tsx:56 - tier shown by coloured dot only, no text/`aria-label`
- app/models/page.tsx:54-55 - title/dot flex row no `min-w-0`/`gap`
- app/models/page.tsx:58 - mono `model.id` no `break-all`/`truncate`; ids/names lack `translate="no"`
- app/models/page.tsx:84-85 - needless `suppressHydrationWarning`; `toLocaleString()` no locale
- app/models/page.tsx:51 - 58+ cards unvirtualized
- app/models/page.tsx:64 - `DollarSign` icon no `aria-hidden`

### app/settings/page.tsx
- app/settings/page.tsx:15-24 - `useState` init reads `localStorage` → controlled-input hydration mismatch
- app/settings/page.tsx:17,28-29 - `localStorage` no try/catch; throws when storage blocked
- app/settings/page.tsx:51-56,65-70 - URL inputs no `name`, `type="url"`, `autoComplete="off"`, `spellCheck={false}`, validation
- app/settings/page.tsx:76-78 - no `<form>` (Enter doesn't save); no unsaved-changes warning
- app/settings/page.tsx:78-83 - "Saved" no `role="status"`
- app/settings/page.tsx:97,109,121 - `<Label>` on text labelling no control
- app/settings/page.tsx:100,112,124 - scrollable `<pre>` not keyboard-focusable (`tabIndex={0}`)
- app/settings/page.tsx:147 - `ExternalLink` icon on internal link

### app/behavior/page.tsx
- app/behavior/page.tsx:157 - `Tabs defaultValue` reads `?tab=` once, never writes back
- app/behavior/page.tsx:31-37 - session ID input no `name`/`autoComplete`/`spellCheck`
- app/behavior/page.tsx:38-40 - "New Session" only generates demo ID → "Generate Demo ID"
- app/behavior/page.tsx:95-106 - download: no `res.ok`, no `.catch`, no feedback, no `URL.revokeObjectURL`
- app/behavior/page.tsx:78,138 - two `<pre>` share `aria-label="Example commands"` on generic role

### app/debug/page.tsx (dev-only)
- app/debug/page.tsx:22-23 - `<label>` no `htmlFor`, input no `id`
- app/debug/page.tsx:14 - `Date.now()` in `useState` init → hydration mismatch
- app/debug/page.tsx:32-37 - raw buttons, no hover/focus styles
- app/debug/page.tsx:42-59 - hardcoded hex; `#B6D39C`/`#F2A9A1` fail contrast in light theme
- app/debug/page.tsx:48,61 - log pane no `role="log"`; `key={i}`
- app/debug/page.tsx:59 - "No logs yet..." → "…"

### app/ops/page.tsx
- app/ops/page.tsx:113 - `scrollIntoView({behavior:"smooth"})` ignores reduced motion; yanks reader on every event
- app/ops/page.tsx:143 - tab state not in URL
- app/ops/page.tsx:228 - `$${totalCost.toFixed(2)}` → `Intl.NumberFormat`
- app/ops/page.tsx:226-243 - stat values no `tabular-nums`; :232-233 needless `suppressHydrationWarning`
- app/ops/page.tsx:122-124 - active-sessions fetch failure swallowed → shows "No sessions currently running"
- app/ops/page.tsx:264-274 - session ID plain text, should `Link` to `/sessions/{id}`
- app/ops/page.tsx:271-272 - "1 tool calls" not pluralised
- app/ops/page.tsx:324-326 - WS status no `aria-live`
- app/ops/page.tsx:328-333 - "Clear" vague, no `type`, no focus ring, no undo
- app/ops/page.tsx:339-363 - live log no `role="log"`; :346 `key={i}` on sliding window
- app/ops/page.tsx:349 - `timestamp.slice(11,19)` shows UTC → `Intl.DateTimeFormat`
- app/ops/page.tsx:357 - truncated JSON no `title`/expand
- app/ops/page.tsx:63 - `Skeleton` `aria-label` without role
- app/ops/page.tsx:415-421 - plan-ID input placeholder-only label, raw `<input>`/`<button>`, no `<form>`
- app/ops/page.tsx:420 - Enter fires `fetchPlan()` while loading → duplicate requests
- app/ops/page.tsx:390-400 - `!result.ok` silently ignored; :431 error `<p>` no `role="alert"`

## providers/

### ✓ AnnouncerProvider.tsx · ShellProvider.tsx · EventStreamProvider.tsx

- providers/ThemeProvider.tsx:51-54 - never sets `documentElement.style.colorScheme` / `theme-color` meta
- providers/ToastProvider.tsx:126 - `transition-all`
- providers/ToastProvider.tsx:84-88 - `fixed bottom-4 right-4 w-full` overflows left edge 16px on phones; no safe-area inset
- providers/ToastProvider.tsx:118-120 - `aria-live` mounted with content per toast (often missed); put it on persistent container :84
- providers/ToastProvider.tsx:148-154 - dismiss target ~14px; `X` icon no `aria-hidden`
- providers/ToastProvider.tsx:137,148 - buttons don't use `focus-ring`

## components/ui/

### ✓ avatar · input · label · separator · skeleton · switch · textarea · tooltip

- components/ui/alert.tsx:30 - `role="alert"` hardcoded on all variants; default should be `status`
- components/ui/alert.tsx:39 - `AlertTitle` is `div`
- components/ui/badge.tsx:8 - `transition-all`
- components/ui/button.tsx:43 - no default `type="button"` (submits enclosing forms)
- components/ui/button.tsx:23 - `lg` size missing `pointer-coarse:min-h-11`
- components/ui/button.tsx:40 - no `loading`/`aria-busy` prop; callers hand-roll
- components/ui/card.tsx:36 - `CardTitle` is `div`
- components/ui/dialog.tsx:56 - `DialogContent` no `max-h`/`overflow-y-auto`/`overscroll-contain`
- components/ui/dialog.tsx:97 - `DialogSheet` no `overflow-y-auto`/`overscroll-contain`
- components/ui/dropdown-menu.tsx:40 - popup no `max-h`/`overflow-y-auto`/`overscroll-contain`
- components/ui/progress.tsx:48 - `transition-all` on width → `scaleX` + `origin-left`
- components/ui/scroll-area.tsx:35 - viewport no `overscroll-contain`
- components/ui/select.tsx:44 - `focus:` not `focus-visible:`; differs from `focus-ring`
- components/ui/select.tsx:25 - `SelectValue` no `truncate`/`min-w-0`
- components/ui/select.tsx:70 - popup no `overscroll-contain`
- components/ui/tabs.tsx:62 - `transition-all`
- components/ui/tabs.tsx:77 - `TabsContent` `outline-hidden` without focus-visible replacement

## components/common, code, command, dashboard, models

### ✓ ConfirmDialog · StatusBadge

- components/common/StateView.tsx:12,29 - straight apostrophe in "Couldn't"
- components/common/StateView.tsx:30 - default "Loading" → "Loading…"
- components/code/CodeBlock.tsx:24 - `clipboard.writeText` no try/catch; :27 timeout not cleared on unmount
- components/code/CodeBlock.tsx:32 - Copy only renders when `filename` passed
- components/code/CodeBlock.tsx:46 - "Copied" not in live region; :42,44 icons no `aria-hidden`
- components/code/CodeBlock.tsx:50 - no `translate="no"`; scroll region not focusable
- components/code/CodeBlock.tsx:31-39 - hardcoded hex bypasses tokens
- components/command/CommandPalette.tsx:72 - input no `autoComplete="off"`/`spellCheck={false}`
- components/command/CommandPalette.tsx:100 - listbox no `overscroll-contain`
- components/command/CommandPalette.tsx:120 - shortcut `span` not `<kbd>`
- components/dashboard/CostChart.tsx:55,80,105,148,173 - `$` + `toFixed(4)` → `Intl.NumberFormat`
- components/dashboard/CostChart.tsx:66,67,175 - `toLocaleString()` no locale + `suppressHydrationWarning`
- components/dashboard/CostChart.tsx:55-173 - no `tabular-nums` on KPIs
- components/dashboard/CostChart.tsx:92,126 - charts no `role="img"`/`aria-label`/text alternative
- components/dashboard/CostChart.tsx:113,128 - Recharts JS animation ignores reduced motion (`isAnimationActive`)
- components/dashboard/CostChart.tsx:36,113,137 - hex palette; pie slices colour-only
- components/dashboard/CostChart.tsx:96,100 - raw date ticks, no currency `tickFormatter`
- components/dashboard/CostChart.tsx:126 - no empty state
- components/dashboard/CostChart.tsx:165-170 - legend name no `truncate`/`min-w-0`; swatch no `aria-hidden`
- components/dashboard/CostChart.tsx:89 - "Last 7 Days" hardcoded vs data length
- components/dashboard/MetricsPanel.tsx:27,45,58,69,80,93 - icons no `aria-hidden`
- components/dashboard/MetricsPanel.tsx:30-96 - no `tabular-nums`; :48,61,72 raw floats (`{cpuUsage}%`)
- components/dashboard/MetricsPanel.tsx:23 - polled metrics no `aria-live`
- components/dashboard/MetricsPanel.tsx:62 - `Progress` value not clamped
- components/models/RoleModelsPanel.tsx:53 - native `<select>` `bg-transparent`, no `color-scheme` → unreadable options in dark
- components/models/RoleModelsPanel.tsx:58 - `focus:` not `focus-visible`
- components/models/RoleModelsPanel.tsx:56 - `disabled={busy}` drops focus after change; no `aria-busy`
- components/models/RoleModelsPanel.tsx:60 - `row.default[0]` undefined → "Default · undefined"
- components/models/RoleModelsPanel.tsx:76 - `aria-label` uses raw `planner_sub`
- components/models/RoleModelsPanel.tsx:39 - "Could not save" no next step

## components/behavior

- components/behavior/BehaviorPanel.tsx:46 - Live/Polling status no `aria-live`
- components/behavior/BehaviorPanel.tsx:53,79 - "..." → "…"; session id no `translate="no"`
- components/behavior/BehaviorPanel.tsx:72 - `gridTemplateColumns:"1fr 1fr"` not responsive; use `minmax(0,1fr)`
- components/behavior/LiveFeed.tsx:30,33 - `toLocaleTimeString()` returns "Invalid Date", never throws → dead `catch`
- components/behavior/LiveFeed.tsx:41,56 - "..." → "…"
- components/behavior/LiveFeed.tsx:50 - no `role="log"`; no `overscroll-contain`
- components/behavior/LiveFeed.tsx:63 - key `${timestamp}-${index}` with prepend → full remount each event
- components/behavior/LiveFeed.tsx:69 - conflicting `w-3.5 w-4`; event type icon+colour only
- components/behavior/LiveFeed.tsx:70 - `min-w-[60px]` too narrow for time; no `tabular-nums`
- components/behavior/LiveFeed.tsx:71 - truncated path no `title`
- components/behavior/LiveFeed.tsx:66 - `bg-white/5` invisible in light theme; :27 `text-cyan-500` off-token
- components/behavior/RecentActions.tsx:128 - hand-rolled modal: no `role="dialog"`, focus trap, Escape, focus return, scroll lock; use `Dialog`
- components/behavior/RecentActions.tsx:87,103 - raw `<button>` no `type`, no focus-visible
- components/behavior/RecentActions.tsx:140-141 - `<label>` no `htmlFor`, textarea no `id`/`name`; no `<form>`
- components/behavior/RecentActions.tsx:35 - same dead "Invalid Date" catch
- components/behavior/RecentActions.tsx:99,104 - unbounded `.map`, index keys
- components/behavior/RecentActions.tsx:119,135 - truncated path no `title`; `slice(-40)` no ellipsis
- components/behavior/RecentActions.tsx:165 - "Submitting..." → "…"
- components/behavior/RecentActions.tsx:71,75 - errors no next step
- components/behavior/RecentActions.tsx:108 - `bg-white/10` invisible in light theme
- components/behavior/TrustBar.tsx:30 - "Loading trust score..." → "…" + `role="status"`
- components/behavior/TrustBar.tsx:47 - unrounded `%`, no `tabular-nums`
- components/behavior/TrustBar.tsx:55 - "1 overrides"; `toLocaleString()` no locale
- components/behavior/TrustBar.tsx:60-62 - bar not `aria-hidden`/`progressbar`; animates `width`

## components/conversation

### ✓ EventRenderer.tsx

- components/conversation/GapMarkerRow.tsx:5-9 - dropped-events warning not `role="status"`, inside `aria-live="off"` log → never announced
- components/conversation/GapMarkerRow.tsx:8 - manual plural; no `tabular-nums`
- components/conversation/MessageRow.tsx:16-26 - no `break-words` on `whitespace-pre-wrap`; parent no `min-w-0` → URLs overflow
- components/conversation/MessageRow.tsx:27-44 - "Sending…"/"Not sent" not announced
- components/conversation/MessageRow.tsx:38 - "Retry" → "Retry Sending"
- components/conversation/StepRow.tsx:8 - description no `min-w-0`/`break-words`
- components/conversation/StatusEventRow.tsx:15-18 - ErrorRow no `role="alert"`; no `break-words`/`min-w-0`; no next step
- components/conversation/StatusEventRow.tsx:26,49,83 - question / approval prompt / notification no `break-words`
- components/conversation/StatusEventRow.tsx:48,58 - tool name / allow_always value no `translate="no"`
- components/conversation/StatusEventRow.tsx:53-62 - Approve/Always/Decline: no pending guard (double-send), no resolved state; "Always allow" is persistent grant with one click
- components/conversation/StatusEventRow.tsx:75 - DoneRow not `role="status"`
- components/conversation/Composer.tsx:202-213 - textarea no `name`, `autoComplete="off"`, `enterKeyHint="send"`
- components/conversation/Composer.tsx:201-217 - no `<form>`; submit via keydown/onClick only
- components/conversation/Composer.tsx:208 - `rows={1}` no auto-grow (`field-sizing-content`)
- components/conversation/Composer.tsx:159 - fixed bottom, no `env(safe-area-inset-bottom)`
- components/conversation/Composer.tsx:214 - send button no spinner
- components/conversation/Composer.tsx:171,173-178 - mode chip / "Sending…" not announced
- components/conversation/Composer.tsx:189 - `aria-label="Auto mode"` vs visible "Auto" (label-in-name)
- components/conversation/Composer.tsx:192-197 - enabling Auto (skips approvals) has no confirm
- components/conversation/Composer.tsx:149-156 - no unsaved-draft warning on navigation
- components/conversation/Composer.tsx:64 - straight quotes + "..." in placeholder
- components/conversation/ConversationPane.tsx:173-184 - timeline `.map()` unvirtualized
- components/conversation/ConversationPane.tsx:152,186-191 - "Waiting for events…" / "Agent is working…" no `role="status"`
- components/conversation/ConversationPane.tsx:196-206 - jump button no safe-area offset; count no `tabular-nums`
- components/conversation/ConversationPane.tsx:211-229 - Continue no pending state; `h-7` beats pointer-coarse target
- components/conversation/ConversationPane.tsx:218 - `failureReason` no `break-words`
- components/conversation/ConversationPane.tsx:93 - fetch failure: `console.warn` only, no user feedback
- components/conversation/RunControls.tsx:36-45 - Interrupt (destructive) one click, no confirm/undo
- components/conversation/RunControls.tsx:28 - "Failed to interrupt session" + raw `e.message`, no next step
- components/conversation/ToolCallRow.tsx:44-48,91 - buttons no `type="button"`; no `aria-controls`
- components/conversation/ToolCallRow.tsx:56-60 - tool/function names no `translate="no"`
- components/conversation/ToolCallRow.tsx:61-70 - Running/Failed/Done not announced
- components/conversation/ToolCallRow.tsx:91 - "Copied" not announced; 1500ms timeout not cleared
- components/conversation/ToolCallRow.tsx:105 - count no `tabular-nums`

## components/shell

### ✓ AppShell.tsx (skip link present)

- components/shell/ConsoleShell.tsx:32-37 - rail/dock open state not in URL
- components/shell/ConsoleShell.tsx:31 - `size="sm"` toolbar buttons no pointer-coarse min height
- components/shell/ResponsivePanel.tsx:32 - `useMediaQuery` false on first paint → desktop mounts Dialog tree then swaps
- components/shell/AppBar.tsx:50-52 - `h1` only when `slots.title` set; rail `h2`s precede it
- components/shell/AppBar.tsx:56-65 - Live/Offline not announced
- components/shell/AppBar.tsx:72 - aria-label "Open command palette (Ctrl or Command K)" vs visible "K"
- components/shell/AppBar.tsx:98-107 - menu button no `aria-expanded`
- components/shell/AppBar.tsx:81,123 - "New session" → Title Case
- components/shell/SessionRail.tsx:125-148 - list unvirtualized
- components/shell/SessionRail.tsx:32-39 - search no `name`/`autoComplete="off"`; query not in URL
- components/shell/SessionRail.tsx:53 - no `overscroll-contain`
- components/shell/SessionRail.tsx:143 - model id no `translate="no"`
- components/shell/SessionRail.tsx:70-77 - "New" → "New Session"

## components/dock, plan, misc

### ✓ TrustTab.tsx

- components/dock/Dock.tsx:23 - `defaultValue="plan"` uncontrolled; resets on sheet remount, not in URL
- components/dock/Dock.tsx:30 - no `overscroll-contain`
- components/dock/CostTab.tsx:47-64 - `$` + `toFixed(4)`; "({windowHours}h)" hardcoded; no `tabular-nums`; "1 calls"
- components/dock/CostTab.tsx:62 - model id `truncate` + `title` only; no `min-w-0`/`translate="no"`
- components/dock/PlanTab.tsx:82 - "Loading plan" → "…"
- components/dock/PlanTab.tsx:89 - raw error, no retry, no `role="alert"`
- components/dock/PlanTab.tsx:94-96 - `&apos;` straight apostrophe
- components/dock/ToolsTab.tsx:14,21 - Map clone per event + reverse per render; unvirtualized
- components/dock/ToolsTab.tsx:29-36 - div pile, no list semantics
- components/dock/ToolsTab.tsx:32-33 - truncated function name no `min-w-0`/`title`/`translate="no"`
- components/dock/ToolsTab.tsx:43-60 - status not announced
- components/plan/LazyPlanVisualizer.tsx:12 - `aria-label` on Skeleton without role
- components/plan/PlanChecklist.tsx:27 - "N of M done" not announced (bar is aria-hidden)
- components/plan/PlanChecklist.tsx:30 - `transition-[width]` → `scaleX`
- components/plan/PlanVisualizer.tsx:36-50 - status icon + colour only, no text alternative
- components/plan/PlanVisualizer.tsx:42,105,122 - `animate-spin` + ReactFlow animated edges ignore reduced motion (JS)
- components/plan/PlanVisualizer.tsx:77 - `truncate` hides step text, no `title`
- components/plan/PlanVisualizer.tsx:154 - fixed `h-[500px]` overflows short viewports
- components/plan/PlanVisualizer.tsx:157 - `h3` without h2; no `text-balance`
- components/plan/PlanVisualizer.tsx:160-179 - canvas unreachable by keyboard (`elementsSelectable={false}`)
- components/ConnectionStatus.tsx:15 - `localStorage.getItem` no try/catch → breaks poll in privacy mode
- components/ConnectionStatus.tsx:46-53 - `useState` init reads sessionStorage → hydration mismatch
- components/ConnectionStatus.tsx:104-180 - status Alerts swap, all `role="alert"` (assertive)
- components/ConnectionStatus.tsx:107,117,123,142 - icons no `aria-hidden`
- components/ConnectionStatus.tsx:108,157,170 - "..." → "…"
- components/ConnectionStatus.tsx:155-162 - API key input: no label, `name`, `autoComplete`; placeholder-only; no `isComposing` check on Enter
- components/ConnectionStatus.tsx:163 - "Save Key" no pending; empty key silent no-op (:68)
- components/ConnectionStatus.tsx:131-132 - "Clear" removes API key, no confirm; label vague
- components/ConnectionStatus.tsx:168-172 - "Retrying connection..." stale while still in error
- components/ConnectionStatus.tsx:89-102 - 10s poll not paused when tab hidden
- components/PlanReviewCard.tsx:20 - icon no `aria-hidden`
- components/PlanReviewCard.tsx:22-23 - manual plural
- components/PlanReviewCard.tsx:36 - decimal marker + Circle icon duplicated
- components/PlanReviewCard.tsx:37 - description no `break-words`/`min-w-0`
- components/PlanReviewCard.tsx:43 - "Approve plan" no pending/double-click guard, stays actionable after approval
- components/PlanReviewCard.tsx:46-48 - no Reject action; "use the composer below" not linked/focused
