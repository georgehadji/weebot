---
status: reference
date: 2026-10-31
---

# Wave 8 — Seams, fix-interaction and the program verdict

Execution record for W8 of [`tasks/specs/ui_defect_hunt_v71_execution_plan.md`](../specs/ui_defect_hunt_v71_execution_plan.md). W8 adds no new candidates. It checks how the fixes of W1–W7 interact, states the program's coverage, and proposes consolidations without implementing them.

## 1. What landed (branch `fix/ui-defect-hunt`)

| Wave | Report | Defects fixed | Commits |
|---|---|---|---|
| W1 | `ui_defect_hunt_w1_transport.md` | 3 (2026-10-25) | earlier |
| W2 | `ui_defect_hunt_w2_timeline.md` | 5 | `aad8c58f` |
| W3 | `ui_defect_hunt_w3_composer.md` | 3, then W3-6 | `0466da6f`, `6166004e` |
| W4 | `ui_defect_hunt_w4_api.md` | 4 | `bdbc1b30` |
| W5 | `ui_defect_hunt_w5_data.md` | 5, then R4 and R6b (four `/ops` tests), then D10 | `0b41ef01`, `e0968027`, `325d12c9` |
| W6 | `ui_defect_hunt_w6_shell.md` | 4, then D14, G6, G8 | `3a91aad7`, `1becc1c7` |
| W7 | `ui_defect_hunt_w7_primitives.md` | 3 | `cffe2082` |

That is 34 defects fixed. The severity of each is in its wave report.

Backend fixes the hunt surfaced:
- W2-4: the SSE drop notice has an id (`8a2fa517`).
- D10: a delete publishes a `deleted` presence frame (`325d12c9`).
- Presence frames reach only their owner's rails (`9732e8aa`). This was found while fixing D10: every rail received every user's session ids, titles and statuses.

## 2. Fix-interaction check (Phase 5, across waves)

Each shared file or shared piece of state that more than one fix touched:

| Shared state | Fixes | Interaction | Evidence |
|---|---|---|---|
| `ConversationPane.tsx` | W2 (`mergeHistory`, `isRendered`), W3-6 (`stateRef`, `settleDelivery` returns the row state) | Independent: W3-6 reads the row state that `mergeHistory` produces and does not change the merge. | `ConversationPane.test.tsx` and `Composer.test.tsx` both green after W3-6 |
| `useComposer.ts` | W3-1 (run-failure toast), W3-2 (`retry` action), W3-6 (echo wins) | W3-6 returns early, before the W3-1 toast, when the row is already sent. That is intended: no failure toast for a delivered message. | `useComposer.test.tsx`: the D7 toast test and the W3-6 test both pass |
| `ToastProvider.tsx` | W6 G5 (ref-counter ids), W6 G6 (hover or focus hold) | Disjoint: ids versus the timer. | `ToastProvider.w6.test.tsx` 6/6 |
| `useToast` consumers | W3-1 now needs a `ToastProvider` above `useComposer` | The app tree has one (`app/layout.tsx`). Tests that render the hook must provide one. | W3 report §5 |
| `lib/api.ts` | W4 (D4 classification, 422 detail, `openSocket` token guard), W5 F5 (`RecentActions` posts through `getApiBase()`) | W5 uses W4's `getApiBase`; no conflict. | `api.test.ts`, `behavior.test.tsx` |
| `useSessionList` | D10 (`deleted` rows dropped), the presence-owner fix (backend) | The backend now sends a rail only its owner's frames; the UI still drops `deleted` ones. | `sessions/page.test.tsx`, `test_presence_reaches_only_its_owner.py` |
| `useRemote` | W5 F1 (newest response wins), W5 `/ops` follow-up (health and metrics each own a `useRemote`) | The `/ops` follow-up relies on F1, so a slow poll cannot overwrite a newer one. | `useRemote.ordering.test.ts`, `ops/page.test.tsx` |

No pair of fixes undoes another. Every proof test from every wave passes together: 36 files, 271 tests.

## 3. Seams the spec names (proposals, not implemented)

1. **Three live-transport owners** (`EventStreamProvider`, `ops/page.tsx`, `useBehavior`), each with its own reconnect policy and its own notion of "connected". Propose moving `/ops` and behavior onto the provider's pool, so one reconnect and backoff policy feeds every "Live" indicator. W5's `/ops` reconnect is a fixed 3 s with no ceiling.
2. **Readers of the backend URL keys** with different fallbacks (W4's table):
   - REST falls back to the `/api` proxy, while the SSE fallback goes straight to `ENDPOINTS.api`. On a LAN viewer, the SSE fallback therefore points at the viewer's own `localhost:8000`.
   - `useBehavior` ignores `weebot_ws_url`.
   - Saving the settings page pins the default origin and moves REST off the proxy.

   Propose one `getBackendUrls()` in `lib/api.ts` that every reader uses.
3. **The session-status vocabulary in four places** (`StatusBadge`, `SessionRail.isActive`, `Composer`'s `MODE_LABEL`, `applyPresence`'s cast). Presence now also carries `deleted`. Propose one `SessionStatus` union and one map from status to label and tone.
4. **Two sources for the session list.** The rail is live via presence; `/sessions` polls every 5 s. D10 made deletes converge. Propose that the page reads `useSessionList` too.
5. **No key can be set in the shipped UI.** `ConnectionStatus`, the only writer of `weebot_api_key`, is mounted nowhere (W4). This needs an owner decision: mount it in Settings, or delete it.

## 4. Program coverage statement (§8.3)

```
Surface audited:            W1-W7, regions R1-R7 each (see the wave reports)
Surface NOT audited:        app/behavior/page.tsx (N1: no res.ok on the self-knowledge download);
                            the /ops Quick Stats card (still falls back to 0) and active sessions
                            (swallowed load error); the generated-but-not-investigated candidates
                            in each wave report (W3-11..13, W5 R7b/N2/N3, W6 G2/G7/G9/G14/G15)
Defect classes covered:     C1-C10
Architecture census basis:  VF from the Phase 0 census (spec section 2) plus each wave's map
Confirmed defects:          34 fixed; severity per defect in each wave report. Open: W3-5, which
                            is GUARDED (holds only while callers key the pane)
Re-attributed to owner:     3 (W2-4 SSE id, D10 presence frame, W3-6 echo-then-error)
Residual UNKNOWN:           everything browser-only: layout and paint, real IntersectionObserver
                            timing, real Safari IME, StrictMode double mount of the providers,
                            reconnect races across the three socket stacks, the axe and perf gates.
                            The Playwright suite cannot launch a browser on this host.
Clean-claim scope:          "Regions R1-R7 of waves W1-W7 were audited for classes C1-C10, and no
                            VERIFIED defect remains unfixed except the guarded W3-5." NOT "the
                            frontend is bug-free".
Highest-value next hunt:    the three socket stacks under real network faults (Playwright with
                            page.routeWebSocket on a browser-capable host), then seam 2 (URL
                            readers).
```

## 5. Definition of done (§8.4)

| Item | Result |
|---|---|
| Every wave has a report with a coverage statement or `PARTIAL` | Yes: W1-W7. W6 was marked PARTIAL, and its three unfixed defects were then fixed. |
| Every VERIFIED defect has a proof test that fails at its parent | Yes. Each wave report and follow-up states the failing run. |
| `npm run lint`, `npx tsc --noEmit`, `npm test`, `npx next build`, `make lint-ui` | Green on 2026-10-31: 36 test files, 271 tests; 11 static pages built; UI debt counters at ceiling; 58 contrast pairs at 4.5:1 or above |
| No ceiling raised, no exemption, no dependency added | Yes |
| Browser gates run once on a capable host | **Not done.** Chromium cannot launch here; this needs a CI job or a local browser host. |

**Verdict:** the program is complete except the browser gates, which are blocked by the host.
