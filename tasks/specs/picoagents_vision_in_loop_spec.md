# Spec: Vision-in-the-Loop for Computer-Use / Browser Agents

**Status:** Phase 1 + Phase 2 implemented (unit-verified; smoke test PASSED)
**Date:** 2026-06-17

**Phase 1 landed:** `infrastructure/adapters/llm/_multimodal.py` (`build_image_message`,
`convert_messages`, `model_supports_vision`); both LLM adapters route through `convert_messages`;
`executor/_base.py` injects the latest screenshot when a tool result carries `base64_image`
(older images downgraded to placeholders); flag `WEEBOT_VISION_IN_LOOP` (default off) + capability
gate. Tests: `tests/unit/test_llm_multimodal.py`, `tests/unit/test_executor_vision_injection.py`
(22 new). Full unit suite green (1989 passed). **Deviation:** gated on `base64_image` presence
instead of a per-tool `emits_visual_state` marker (YAGNI, smaller blast radius). **Smoke test
passed** (`scripts/smoke_vision.py`): real 597 KB PNG captured, verified flag OFF suppresses
injection, flag ON injects image block, Anthropic wire format correct (source.type=base64,
media_type=image/png), and lifecycle correctly downgrades older screenshots to placeholders.
Remaining: full live API run against a native-app task where OCR fails.
**Origin:** Audit of `designing-multiagent-systems` (PicoAgents). After three verification
rounds, this is the **only** non-redundant capability that framework surfaced for weebot —
every other "gap" was already present in weebot, usually richer. See
`memory/picoagents_audit.md`.

---

## Problem

weebot captures screenshots but **never feeds them to the model as visual input**. Verified:

- `base64_image` exists only inside *tools* (`tools/advanced_browser.py`, `tools/computer_use.py`,
  `tools/screen_tool.py`, `tools/browser_inspector.py`) and DI wiring — never in the executor
  or LLM layer.
- `application/ports/llm_port.py` has **no** image/vision surface.
- Neither `infrastructure/adapters/llm/anthropic_adapter.py` nor `openai_adapter.py` constructs
  image content blocks (no `image_url`, no `source/base64`).
- `config/prompts/rules/browser.md` treats screenshots as **verification artifacts** ("take one
  after navigation"), not model input.

So the agent drives the browser/desktop **blind** — emitting CSS selectors or `(x,y)` coordinates
from DOM text and OCR text, never from *seeing* the page. OCR (`pytesseract`) is the current
substitute for vision.

**Where it hurts most:** the **desktop `pyautogui` path** (`tools/computer_use.py`). Native apps
have *no DOM at all*; weebot navigates them by OCR + keyword heuristics alone. This is exactly
where vision-grounding wins. The browser path (DOM + OCR) is the milder case.

## Non-goals

- Not replacing DOM/selector automation — vision *augments* it (selector first, vision fallback).
- Not adding a new orchestration flow. This is a capability on the existing executor loop.
- Not OCR removal — OCR stays as a cheap text path; vision is opt-in for visually complex targets.

---

## Design

### Canonical multimodal message shape (provider-neutral)

`LLMPort.chat(messages: List[Dict[str, Any]], ...)` already accepts arbitrary dicts — **no port
signature change**. Standardize a neutral content-block shape that adapters translate:

```python
{"role": "user", "content": [
    {"type": "text",  "text": "Page after click — current screen:"},
    {"type": "image", "data": "<base64>", "media_type": "image/png"},
]}
```

Plain-string `content` (today's common case) is untouched and still works on both providers.

### Phase 1 — Vision feedback (the core change)

1. **Adapter content conversion** (the real work — both adapters currently pass `messages`
   straight through):
   - Add `_convert_messages(messages)` to each adapter that maps list-content blocks:
     - **Anthropic** (`anthropic_adapter.py`, before `self._client.messages.create` at ~line 76):
       `image` → `{"type":"image","source":{"type":"base64","media_type":...,"data":...}}`
     - **OpenAI** (`openai_adapter.py`): `image` → `{"type":"image_url","image_url":{"url":"data:<mt>;base64,<data>"}}`
     - `text` block and string content pass through unchanged on both.
   - Keep it total: unknown block types degrade to a text placeholder, never raise.

2. **Executor injection hook** (`application/agents/executor/_base.py`):
   - Tool results are appended as `{"role":"tool", ...}` to `_conversation_buffer` (~line 1017).
     The next LLM call assembles `[system] + list(_conversation_buffer)` (~line 734).
   - When a `ToolResult.base64_image` is present **and** vision is enabled, append an additional
     `{"role":"user","content":[{type:image,...}]}` message right after the tool message, so the
     next call sees the screenshot.

3. **Gating** (`config/feature_flags.py`):
   - `vision_in_loop` flag (default off).
   - Capability check: only inject when the active model supports vision (extend the model
     registry/`model_selection.py` with a `supports_vision` bit; Claude models = true).
   - Tool opt-in: only tools that declare `emits_visual_state` (computer_use, advanced_browser,
     screen_tool) trigger injection — not every tool.

4. **Image lifecycle / token control** (critical — images are token-heavy and interact with the
   existing deque + token-threshold compression at ~line 321):
   - Keep at most the **last 1–2 screenshots** live. Before each call (or during compaction),
     strip `image` blocks from older multimodal messages, replacing with
     `{"type":"text","text":"[screenshot from step k omitted]"}`.
   - This is the same "drop stale heavy content" principle as `MemoryCompactor`, applied to images.

### Phase 2 — Structured observe→plan reflection (fast-follow, optional)

Port PicoAgents' `PageObservation` / `NextActionPlan` (see
`picoagents/.../_computer_use/_planning_models.py`) as a structured-output reflection step:

- `PageObservation`: `summary`, `key_elements`, `is_task_complete`, `confidence`.
- `NextActionPlan`: `action_type`, `selector`, `value`, `coordinates` (selector-with-coordinate
  fallback), `reasoning`, `expected_outcome`, `confidence`.
- Value: `expected_outcome` + `confidence` enable self-correction (compare expectation to the next
  screenshot) and dovetail with `TrajectoryMonitor`'s degenerate-pattern detection.

Lower priority — only worth it once Phase 1 proves vision helps on real targets.

---

## Files touched (Phase 1)

| File | Change |
|------|--------|
| `infrastructure/adapters/llm/anthropic_adapter.py` | add `_convert_messages` (image→Anthropic source block) |
| `infrastructure/adapters/llm/openai_adapter.py` | add `_convert_messages` (image→`image_url` data URL) |
| `application/agents/executor/_base.py` | inject multimodal message after tool results with `base64_image`; strip stale images in compaction |
| `config/feature_flags.py` | `vision_in_loop` flag |
| `application/services/model_selection.py` (+ registry) | `supports_vision` capability bit |
| `tools/base.py` | optional `emits_visual_state` marker on tools that return screenshots |

No change to `llm_port.py` signature.

## Verification

- **Unit:** mock LLM client; a tool returning `base64_image` ⇒ an `image` block appears in the
  messages handed to the adapter (and is absent when the flag is off / model lacks vision).
- **Golden:** `_convert_messages` produces correct provider-specific shapes for Anthropic vs OpenAI.
- **Lifecycle:** after N steps, only the latest 1–2 images survive; older ones are text placeholders.
- **Smoke (live):** desktop `pyautogui` path — give the agent a native-app task that OCR alone fails
  (e.g. click an unlabeled icon); confirm vision-enabled run succeeds where vision-off does not.

## Risks / open questions

- **Cost/latency:** images are expensive. Mitigated by 1–2-image cap + opt-in flag. Measure
  tokens/task via existing `HarnessMetrics.trajectory_efficiency` before/after.
- **Conditional value:** if weebot's real browser use is mostly well-structured web apps, DOM+OCR
  may suffice. Justification is strongest for desktop/canvas/visually-complex targets — validate the
  smoke test on those first.
- **Provider parity:** confirm the OpenAI adapter's target models are vision-capable; Anthropic/Claude
  is the primary path and is native-vision.
```
