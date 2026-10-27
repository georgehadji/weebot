---
type: object
name: CommandSecurityAnalyzer (4-layer shell analyzer)
code: CommandSecurityAnalyzer, CommandRiskLevel, SecurityAssessment
cluster: core
universe: live
status: verified
verified: 2026-10-27
commit: 7d1ce324
---

# CommandSecurityAnalyzer

A stateless, regex-and-statistics scanner that rates a shell command SAFE, SUSPICIOUS or DANGEROUS in four layers. It lives in `weebot/tools/`, not `weebot/core/`, and only `BashTool` calls it. It is a second, independent rule set next to `BashGuard`.

## Why this shape
Defense in depth for the one tool that takes free-form shell text (`weebot/tools/bash_security.py:1-13`). Each layer is cheap and synchronous; an LLM-based fourth layer was written and then left unwired (`:184-186`, `:191-263`). A single module-level instance is reused (`:491-500`) because the class holds no state.

## Shape
- `CommandRiskLevel` has three levels, no BLOCKED (`:25-30`). `SecurityAssessment(risk_level, layer_triggered, reason, details)` (`:33-40`).
- `analyze(command)` (`:160-189`) runs layers 1 to 4 in order. It returns early only on DANGEROUS from layers 1 to 3; otherwise the layer 4 result is the answer.
  1. **Patterns** (`:57-97`, `:265-278`): 25 regexes, case-insensitive. Base64 decode pipes, `eval $(`, pipe-to-shell, process substitution, download piped to a shell, hex escapes, nested backticks, and PowerShell `Invoke-Expression`, `iex`, `Net.WebClient...DownloadString`, hidden `Start-Process`, TCP reverse shell, reflective assembly load.
  2. **Behaviour** (`:280-323`): six download-then-execute regexes on the lower-cased command (`:285-293`), then three keyword-set combinations over a token set (`:128-137`, `:305-321`): download tool with shell, `base64`/`openssl` with `eval`/`exec`, `temp`/`tmp` with `chmod`.
  3. **Entropy** (`:325-392`): Shannon entropy of base64-looking strings; DANGEROUS above 4.0 (`:140-143`). Three overlapping loops: strings of 40+ characters that decode to shell keywords, any whitespace token of 20+ characters in the base64 alphabet, any 40+ character run.
  4. **Structure** (`:394-435`): more than 5 chain operators (20 when a PowerShell cmdlet is present or the command starts with `$`) or a URL together with `|`, `&&`, `||` gives SUSPICIOUS. A short list of known-safe PowerShell pipelines skips both checks (`:151-158`, `:411-413`).
- Layers 1 to 3 can only return SAFE or DANGEROUS (`:269-278`, `:297-323`, `:351-392`). SUSPICIOUS comes from layer 4 alone.

How `BashTool` uses it (`weebot/tools/bash_tool.py:250-316`):
- DANGEROUS is final: the HMAC `security_override` token was retired by ADR-013 (F11), so a DENY is never approvable and an ASK is approved per call through the approval channel (`bash_tool.py:253-256`).
- SUSPICIOUS is logged and the command continues (`:281-291`).
- An analyzer crash refuses the command (`:293-307`). If the analyzer could not be imported at construction, a legacy check runs instead (`:145-154`, `:308-310`).

Consequences (read from source, not run):
- SUSPICIOUS never stops anything. The code comment says "handled by the approval policy below" (`bash_tool.py:288-289`), but `ExecApprovalPolicy.evaluate(command)` is called with the command only, never with this verdict (`:393`).
- Fixed in W3.6 (F10): the 1.2x entropy multiplier is gone. Layer 3 now refuses a base64 run only if it decodes to a shell command, or if it is a 40-character-plus run that is not pure hex, has a digit or `+/=`, is not a path, and has raw entropy above 4.0 bits/char (`bash_security.py:224-229`, `:296-304`, `:372-394`). Hex digests and CamelCase identifiers pass; `tests/unit/fixes/test_f10_entropy_hex_digest.py` pins `git checkout <40-hex sha>` and `docker pull ...@sha256:<64-hex>`. The false-positive test (`tests/unit/tools/test_bash_security_falsifying.py:229-240`) uses its own command list and does not catch this.
- Layer 2's combination targets `|`, `.` and `+x` can never match, because the token set is built with a word-only regex (`:128-137`, `:305`). The `temp`/`tmp` combination flags any command that contains those words and `chmod` or `execute`.
- The known-safe PowerShell allowlist is matched with `re.search` anywhere in the command (`:411-413`), so one safe-looking pipeline in a long command skips the chain-length and URL-chain checks for all of it. Layers 1 to 3 still run.
- Rewritten 2026-10-22 (plan W3.6). The entropy, layer 2 and allowlist notes above describe `f00ea38`.
  - Rules are now data (`LAYER1_RULES`, `LAYER2_RULES`, `LAYER2_COMBINATIONS`).
  - Layer 3 flags base64 that decodes to a shell command (UTF-16LE included), or opaque 40+ char blobs that are not hex, identifiers or paths. There is no 1.2x multiplier.
  - The PowerShell allowlist matches from the start, with no `;` or `&`.
  - Calibration is pinned by `tests/unit/tools/data/command_corpus.json`.
- Deleted 2026-10-22 (W1.6): the uncalled `_layer4_semantic_llm_analysis`, the unread `_DANGEROUS_OPERATORS`, and the docstring's timeout claim. The `.importlinter` exemption for `bash_security -> model_selection` went with them. Line numbers in this card are from `f00ea38`.

## Connected to
- **Owned by** `BashTool` (`bash_tool.py:26-28, 90, 144`); no other tool uses it. `powershell` and `python_execute` do not call it (see the BashGuard card).
- **Related:** `BashGuard` (separate regex set, four levels, run after this one), `ExecApprovalPolicy` (third gate), `weebot/config/constants.py` (`TEMPERATURE_DETERMINISTIC`, used only by the unwired LLM layer).
- **Looks like but is not:** `BashGuard` (rates the same string with different rules; `RiskLevel` has BLOCKED, `CommandRiskLevel` does not); `EgressGuard` (data leaving the machine).

## If you change this
**Hits:** `BashTool` (every `bash` call), the override-token flow, tests `tests/unit/tools/test_bash_security_falsifying.py`.
**Does not hit:** `powershell` and `python_execute` tools; `BashGuard` ratings; egress classification.

## Surfaces
The "Security Error: ... Layer N triggered" text the agent sees on `bash`; log lines for SUSPICIOUS.

## See
`weebot/tools/bash_security.py`
