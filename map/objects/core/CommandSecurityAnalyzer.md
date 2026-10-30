---
type: object
name: CommandSecurityAnalyzer (4-layer shell analyzer)
code: CommandSecurityAnalyzer, CommandRiskLevel, SecurityAssessment
cluster: core
universe: live
status: verified
verified: 2026-10-30
commit: 8e6d1cca
---

# CommandSecurityAnalyzer

A stateless, regex-and-statistics scanner that rates a shell command SAFE, SUSPICIOUS or DANGEROUS in four layers. It lives in `weebot/tools/`, not `weebot/core/`. `BashTool` calls it directly and the guard chain calls it through `AnalyzerAdapter`. It is a second, independent rule set next to `BashGuard`.

## Why this shape
Defense in depth for the one tool that takes free-form shell text (`weebot/tools/bash_security.py:1-17`). Each layer is cheap and synchronous, and none calls an LLM. A single module-level instance is reused (`:424-433`) because the class holds no state. Detections are data (`Rule` records with an id, level, layer and rationale, `:51-59`), and a golden corpus pins the calibration.

## Shape
- `CommandRiskLevel` has three levels, no BLOCKED (`:33-38`). `SecurityAssessment(risk_level, layer_triggered, reason, details)` (`:41-48`).
- `analyze(command)` (`:308-318`) runs layers 1 to 4 in order. It returns early only on DANGEROUS from layers 1 to 3; otherwise the layer 4 result is the answer.
  1. **Patterns** (`LAYER1_RULES`, `:65-158`; matching `:320-338`): 27 case-insensitive regexes. Base64 decode pipes, `eval $(`, pipe-to-shell, process substitution, download piped to a shell, hex escapes, nested backticks, and PowerShell `Invoke-Expression`, `iex`, `Net.WebClient...DownloadString`, hidden `Start-Process`, TCP reverse shell, reflective assembly load, encoded commands.
  2. **Behaviour** (`:346-363`): six download-then-execute regexes (`LAYER2_RULES`, `:162-205`), then three token-set combinations (`LAYER2_COMBINATIONS`, `:210-222`): download tool with shell or `chmod`, `base64`/`openssl` with `eval`/`exec`/`source`, `temp`/`tmp`/`mktemp` with `chmod`/`execute`.
  3. **Encoded payloads** (`:365-387`): each base64-looking run of 16+ characters is decoded (`:270-286`, UTF-16LE included); DANGEROUS if it decodes to a shell command, or if it is an opaque blob (`:289-297`): 40+ characters, not pure hex, has a digit or `+/=`, is not a path, raw Shannon entropy above 4.0 (`:229-232`).
  4. **Structure** (`:389-417`): more than 5 chain operators (20 when a PowerShell cmdlet is present or the command starts with `$`, `:241-248`) or a URL together with `|`, `&&`, `||` gives SUSPICIOUS. A short list of known-safe PowerShell pipelines (`:251-257`) skips both checks when the command has no `;` or `&` (`:392-395`).
- Layers 1 to 3 can only return SAFE or DANGEROUS. SUSPICIOUS comes from layer 4 alone.

How `BashTool` uses it (`weebot/tools/bash_tool.py:251-308`; a logged command is sanitised first, audit R23):
- DANGEROUS is final: the HMAC `security_override` token was retired by ADR-013 (F11), so a DENY is never approvable and an ASK is approved per call through the approval channel (`bash_tool.py:255-258, 271-277`).
- SUSPICIOUS is logged and the command continues (`:279-287`).
- An analyzer crash refuses the command (`:291-305`). If the analyzer could not be built at construction, a legacy check runs instead (`:149-161`, `:306-308`, check at `:189`).

Consequences (read from source, not run):
- SUSPICIOUS never stops anything. The code comment says "handled by the approval policy below" (`bash_tool.py:280-281`), but `ExecApprovalPolicy.evaluate` is called with the command and cwd only, never with this verdict (`:397`). `AnalyzerAdapter` likewise maps SUSPICIOUS to ALLOW with a note (`application/services/tool_guards.py:118-149`).
- The 1.2x entropy multiplier is gone (W3.6, F10). Hex digests and CamelCase identifiers pass; `tests/unit/fixes/test_f10_entropy_hex_digest.py` pins `git checkout <40-hex sha>` and `docker pull ...@sha256:<64-hex>`, and `tests/unit/tools/data/command_corpus.json` pins the rest of the calibration.
- The `temp`/`tmp`/`mktemp` combination flags any command that contains one of those words and `chmod` or `execute` as a word (`:221`).
- The `_layer4_semantic_llm_analysis` method, the unread `_DANGEROUS_OPERATORS` and the `bash_security -> model_selection` `.importlinter` exemption were deleted in W1.6.

## Connected to
- **Owned by** `BashTool` (`bash_tool.py:28-32, 97, 149-161`); the guard chain reaches it through `AnalyzerAdapter` for `bash` and `powershell` calls. `powershell` and `python_execute` do not call it themselves (see the BashGuard card).
- **Related:** `BashGuard` (separate regex set, four levels, run after this one), `ExecApprovalPolicy` (third gate).
- **Looks like but is not:** `BashGuard` (rates the same string with different rules; `RiskLevel` has BLOCKED, `CommandRiskLevel` does not); `EgressGuard` (data leaving the machine).

## If you change this
**Hits:** `BashTool` (every `bash` call), `AnalyzerAdapter` in the guard chain; tests `tests/unit/tools/test_bash_security_falsifying.py`, `tests/unit/fixes/test_f10_entropy_hex_digest.py`, `tests/unit/application/services/test_tool_guards.py`, the corpus `tests/unit/tools/data/command_corpus.json`.
**Does not hit:** `python_execute` tool; `BashGuard` ratings; egress classification.

## Surfaces
The "Security Error: ... Layer N triggered" text the agent sees on `bash`; log lines for SUSPICIOUS.

## See
`weebot/tools/bash_security.py`
