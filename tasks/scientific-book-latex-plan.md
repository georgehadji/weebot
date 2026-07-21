# Plan: Greek Scientific Book Generation via LaTeX

**Status:** Draft
**Owner:** weebot core
**Date:** 2026-07-21
**Goal:** Enable weebot to produce a complete scientific book **in Greek** — with math
equations, tables, images, code listings, and bibliography — as a compiled PDF via a
LaTeX toolchain, authored primarily by **Claude Opus 4.8** (with a strong fallback tier).

---

## 1. Objective & Success Criteria

weebot accepts a book specification (topic, audience, structure, language = Greek) and
produces:

1. A **compiled PDF** of a multi-chapter scientific book in Greek.
2. The **LaTeX source tree** (`main.tex`, per-chapter files, `figures/`, `refs.bib`).

A run is considered **successful** only when all of the following hold:

- **0 LaTeX errors** (compilation succeeds with `latexmk -xelatex`).
- **All cross-references resolve** — no undefined `\ref`, `\cref`, or `\cite`.
- **Zero missing-glyph warnings** — Greek text, math, and code all render (font coverage
  gate). This is the single most important correctness check for Greek.
- **Structure is sane** — front matter (title, TOC), main matter chapters, bibliography.

Non-goals (this plan): print-shop typesetting polish, EPUB export, collaborative editing.
Those are follow-ups once the pipeline is solid.

---

## 2. What Already Exists (Reuse, Don't Rebuild)

Grounded in the current codebase:

| Capability | Location | How we reuse it |
|---|---|---|
| Plan-Act-**Update** state machine (*"failure triggers an automated plan update"*) | `weebot/application/flows/` (`PlanActFlow`) | The *compile → parse errors → fix → recompile* self-heal loop is exactly this pattern. |
| Markdown skills | `weebot/skills/builtin/<name>/SKILL.md` | New `scientific-book` skill encodes Greek-LaTeX conventions. |
| Isolated execution | `weebot/infrastructure/sandbox/` (`docker_linux.py`, `modal_backend.py`, `wsl2.py`) | Run the TeX Live toolchain here; **required** for `minted` shell-escape (see §4). |
| Shell safety | `weebot/core/bash_guard.py` (SAFE/SUSPICIOUS/DANGEROUS/BLOCKED) | Every `latexmk`/`xelatex` invocation passes through this gate. |
| Greek detection | `weebot/application/services/language_detector.py` | Already detects Greek and injects it into the system prompt. |
| Model routing / task profiles | `weebot/config/model_refs.py`, `weebot/config/model_quality_profiles.yaml` | Add a first-class `AUTHORING`/`LATEX` profile → Opus 4.8. |
| Structured output contract | `weebot/models/structured_output.py` (Pydantic) | New book domain models validate here. |

**Important gap:** In `config/model_refs.py` the Anthropic/Opus references are currently
*aliased away* to non-Anthropic models
(`MODEL_DEFAULT_ANTHROPIC = "qwen/qwen3.7-max"`, `MODEL_PRICE_CLAUDE_OPUS = "x-ai/grok-4.3"`).
Opus 4.8 must be wired as a **real** first-class model via the Anthropic adapter for this
feature.

---

## 3. Toolchain Decision (Greek + LaTeX)

This is the make-or-break foundation.

- **Engine: XeLaTeX** (LuaLaTeX acceptable). **Not pdfLaTeX** — Unicode Greek is far more
  robust with `fontspec` + `polyglossia` than with `babel` + `inputenc`.
- **Language:** `polyglossia` with `\setmainlanguage{greek}` (loads Greek hyphenation).
  `\setotherlanguage{english}` for mixed-language technical terms.
- **Fonts (must cover Greek + math + monospace):**
  - Main/serif: **GFS Didot** or **Noto Serif** (full Greek coverage).
  - Mono (code): **Noto Sans Mono** or **DejaVu Sans Mono** (Greek-capable, for comments).
  - Math: a Greek-aware math font policy (see risk R1).
- **Math:** `amsmath`, `mathtools`, `amssymb`.
- **Tables:** `booktabs`, `longtable`, `tabularx` (responsive/multi-page tables).
- **Figures:** `graphicx` for raster/vector assets; `tikz` + `pgfplots` for reproducible
  native figures (preferred — no external asset dependency, deterministic).
- **Code:** **`minted`** (decision below), driver `Pygments`.
- **Bibliography:** `biblatex` + `biber` (Greek-aware sorting/locale).
- **References:** `hyperref` + `cleveref` (Greek-localized ref names).
- **Class:** KOMA-Script `scrbook` (better i18n/typography than stock `book`).
- **Build:** `latexmk -xelatex -shell-escape` (multi-pass, runs biber automatically).

### Code listings decision: `minted` (sandbox-only)

`listings` mishandles UTF-8 Greek in comments by default. We use **`minted`** for superior
Greek + syntax-highlighting quality via Pygments. `minted` requires `-shell-escape`, which
is a security concern — therefore:

- `minted`/`-shell-escape` compilation runs **only inside the sandbox**
  (`infrastructure/sandbox/`), never on the host.
- The compile command is gated through `bash_guard`; the shell-escape flag is allowed
  **exclusively** on the sandbox execution path and blocked elsewhere.
- Pygments is baked into the TeX Live image (§Phase 0).

---

## 4. Architecture Placement (Clean/Hexagonal)

Dependencies point inward: `Interfaces → Infrastructure → Application → Domain`.

```
Domain        weebot/domain/models/book.py
              Book, Part, Chapter, Section, BookAsset (figure|table|listing),
              CompileResult, CompileError  — all Pydantic, pure, no I/O.

Application   weebot/application/flows/book_generation_flow.py
              BookGenerationFlow  (reuses PlanAct pattern)
              weebot/application/services/book_composer.py
              Outline → preamble → per-chapter draft → assemble → compile → heal.

Infrastructure  weebot/infrastructure/document/latex_compiler.py
              LatexCompilerService — runs latexmk in sandbox via bash_guard,
              multi-pass + biber, parses .log into structured CompileError list.
              weebot/infrastructure/document/log_parser.py
              Deterministic .log → structured errors (undefined ref, missing
              package, missing glyph, overfull box).

Interfaces    cli/main.py  → `book` command group
              weebot/interfaces/web/  → Book panel (outline, live log, PDF preview)

Skill         weebot/skills/builtin/scientific-book/SKILL.md

Config        weebot/config/model_refs.py + model_quality_profiles.yaml
              AUTHORING/LATEX profile → claude-opus-4-8 (+ fallback tier)
```

---

## 5. Generation Pipeline

The interesting design — a bounded, self-healing loop.

**Phase 0 — Toolchain & model foundation**
- Build a **TeX Live Docker image** (scheme-medium + Greek fonts GFS/Noto + Pygments +
  biber) wired into `infrastructure/sandbox/`. Pin the image digest for reproducibility.
- Wire **`claude-opus-4-8`** as a first-class model via the Anthropic adapter. Add an
  `AUTHORING`/`LATEX` task profile in `model_refs.py` + `model_quality_profiles.yaml`
  routing to Opus 4.8, fallback → Qwen 3.7 Max / GLM 5.2. LaTeX correctness rewards the
  strongest model, so this profile does **not** cascade to budget tiers first.

**Phase 1 — Spec intake & outline**
- Capture spec (topic, audience, `--lang el`, target length, feature flags).
- LLM emits a **structured book outline** (parts → chapters → sections) validated against
  the `Book` Pydantic model. Human-in-the-loop review optional here.

**Phase 2 — Locked preamble**
- Emit a **fixed, tested Greek-scientific preamble** from template (`scrbook` + polyglossia
  + fontspec + amsmath + booktabs + minted + tikz + biblatex + hyperref + cleveref).
- The LLM fills **content only** — it never authors the fragile preamble (mitigates R3).

**Phase 3 — Per-chapter drafting**
- Draft chapters as **parallel, context-isolated** LLM calls (per the repo's subagent
  strategy — keeps main context clean).
- Each call outputs **body-only `.tex`** (no preamble), honoring a shared label convention
  (`chap:`, `sec:`, `fig:`, `tab:`, `eq:`, `lst:`) so cross-refs resolve after assembly.
- Figures: prefer LLM-authored **TikZ/pgfplots** (reproducible); otherwise emit a figure
  spec → asset pipeline (e.g. matplotlib) → `figures/`.

**Phase 4 — Assembly**
- Build `main.tex`: `\frontmatter` (title page, TOC) → `\mainmatter` (`\include` chapters)
  → `\backmatter` (`\printbibliography`). Merge per-chapter `.bib` fragments into `refs.bib`.

**Phase 5 — Compile & self-heal (the Plan-Act-Update loop)**
- `LatexCompilerService` compiles in the sandbox (`latexmk -xelatex -shell-escape`).
- `log_parser` turns the `.log` into a **structured error list**.
- Structured errors are fed back to Opus 4.8 (or a deterministic fixer for known patterns)
  → produce a minimal patch → recompile.
- **Bounded to ~5 iterations**; on exhaustion, surface the residual errors to the user.

**Phase 6 — QA gates & output**
- Enforce the §1 success criteria (0 errors, refs resolved, **0 missing glyphs**, sane
  structure).
- Emit PDF + source tarball to `Output/<book-slug>/`.

---

## 6. Interfaces

- **CLI** (`cli/main.py`):
  - `python -m cli.main book create "θέμα" --lang el --out ./Output/mybook`
  - `python -m cli.main book resume <session_id>`
  - `python -m cli.main book compile <path>` (recompile an existing source tree)
- **Web UI** (`weebot/interfaces/web/`): a Book panel showing the outline tree, the live
  compile log, and an inline PDF preview.

---

## 7. Testing & Validation

- **Golden CI test:** compile a minimal Greek document containing **math + table + figure +
  code listing**; assert a PDF is produced and the log has **zero missing-glyph warnings**.
  This is the canary for the whole Greek toolchain.
- **Unit tests:** `log_parser` (fixture `.log` files → expected structured errors); outline
  schema validation; preamble template renders.
- **Integration test:** end-to-end 2-chapter book from spec → PDF inside the sandbox.
- **Import-linter:** ensure new modules respect the layer boundaries (`.importlinter`).

---

## 8. Risks & Mitigations

| ID | Risk | Mitigation |
|---|---|---|
| **R1** | Greek glyphs in **math mode** (`\text{}` vs `textgreek`/`upgreek` vs math font) render wrong or missing. | Define an explicit math-font + Greek-variable policy in the skill; the golden test asserts glyph coverage in a math block. |
| **R2** | `minted` `-shell-escape` is a security surface. | Runs **only** in the sandbox; shell-escape allowed on the sandbox path exclusively and blocked on host via `bash_guard`. |
| **R3** | LLM emits a fragile/incorrect preamble. | Preamble is a **locked, tested template**; LLM fills content only. |
| **R4** | Self-heal loop fails to converge / loops forever. | Hard iteration cap (~5); deterministic fixers for common patterns; surface residual errors to the user. |
| **R5** | Opus 4.8 not truly wired (current Anthropic refs are aliased to other models). | Phase 0 makes `claude-opus-4-8` first-class via the Anthropic adapter before anything else depends on it. |
| **R6** | TeX Live image bloat / slow builds. | scheme-medium + only required packages/fonts; pinned digest; cache the image. |

---

## 9. Phase Sequencing (Suggested)

1. **Phase 0** — image + Opus 4.8 wiring (foundation; unblocks everything).
2. **Proof-of-concept** — `scientific-book` skill + locked Greek preamble + compiler service
   producing **one real Greek PDF** with math/table/figure/code. Proves the toolchain.
3. **Phases 1–5** — domain models, outline, drafting, assembly, self-heal loop.
4. **Phase 6 + Interfaces + Tests** — QA gates, CLI/Web, golden CI test.

The proof-of-concept (step 2) is the highest-value early milestone: it de-risks the entire
Greek toolchain before the orchestration is built.
