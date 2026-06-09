# Weebot Skills Gap Analysis

**Date:** 2026-06-08  
**Source:** aipoch/medical-research-skills (556 skills, MIT license)  
**Format compatibility:** ✅ `SkillRegistry._parse_skill()` parses the YAML-frontmatter SKILL.md format natively (7/10 test files confirmed)

---

## 1. Current Inventory — What Weebot Has (9 skills)

| Skill | Domain | What it does |
|-------|--------|-------------|
| `berb-research` | Research | 23-stage autonomous research pipeline (idea → paper, $0.40-0.70) |
| `competitive_analysis` | Business | Swarm-based competitive landscape analysis |
| `design-taste-frontend` | Design | Anti-slop frontend for landing pages and portfolios |
| `git-best-practices` | Dev | Conventional commits, branching, secrets safety |
| `multi_llm_orchestrator` | Dev | Route specs across 52 LLMs for multi-file builds |
| `reasoner` | Reasoning | 24 reasoning methods, 46 presets, 90+ models |
| `skill-author` | Meta | Guide for writing high-quality weebot skills |
| `web_research` | Research | Web research with browser tools and search engines |
| `clone_website` | Dev | Reverse-engineer and rebuild any website as React components |

**Coverage gaps:** Weebot has NO skills for:
- 📚 Literature search, systematic review, citation management
- ✍️ Academic writing, manuscript preparation, journal submission
- 📊 Data analysis pipelines (beyond raw Python execution)
- 🧪 Study design, hypothesis generation, power analysis
- 📄 PDF extraction, bibliography formatting, reference management
- 📈 Spreadsheet/data manipulation (CSV/Excel)

---

## 2. Gap Matrix

| Domain | Weebot skills | Medical-research skills available | Gap severity |
|--------|-------------|----------------------------------|-------------|
| **Literature discovery** | `web_research` (web search only) | 129 Evidence Insight skills (PubMed, Semantic Scholar, CrossRef, multi-database collection, citation chasing) | 🔴 Critical |
| **Academic writing** | None | 112 skills (submission preflight, journal matching, abstract optimization, methods writing, R&R workflow) | 🔴 Critical |
| **Data analysis** | `reasoner` (reasoning only, no data pipelines) | 141 skills (preprocessing, visualization, statistics, ML, bioinformatics) | 🟡 High |
| **Study design** | None | 63 Protocol Design skills (hypothesis design, sample size, methodology planning) | 🟡 High |
| **Document processing** | None | Multiple (PDF extraction, bibliography formatting, spreadsheet ops, PPT generation) | 🟡 High |
| **Meta/quality** | `skill-author` | `skill-auditor` (audit any skill for quality) | 🟢 Low |
| **Frontend/design** | `design-taste-frontend`, `clone_website` | None applicable | ✅ Covered |
| **Dev/engineering** | `multi_llm_orchestrator`, `git-best-practices` | None applicable | ✅ Covered |

---

## 3. Top 20 Recommended Skills to Adopt

Ranked by domain-agnostic utility × uniqueness vs. weebot's current skills.

### Tier 1 — Immediate high value (literature + writing)

| # | Skill | Source | What it gives weebot |
|---|-------|--------|---------------------|
| 1 | **biomedical-search-strategy-builder** | Evidence Insight | Build professional search strategies for any academic database (PubMed, Embase, WoS). Generalizes to any domain. |
| 2 | **literature-extensive-read** | Evidence Insight | PDF-to-Markdown + structured summarization of academic papers. Weebot can read any PDF paper now. |
| 3 | **systematic-review-screener** | Evidence Insight | PRISMA-compliant abstract screening workflow. Weebot can conduct systematic literature reviews. |
| 4 | **arxiv-preflight** | Academic Writing | Submission-readiness check before arXiv upload. Any CS/ML paper benefits. |
| 5 | **paper-sprint-review** | Academic Writing | Scrum-inspired R&R workflow (docx/tex/md/PDF). Automates the revision process. |
| 6 | **citation-network** | Evidence Insight | Build and visualize citation networks. Identifies key papers and emerging hotspots. |
| 7 | **journal-skills** | Evidence Insight | Recommends target journals based on paper topic and PubMed distribution. |
| 8 | **multi-database-literature-collector** | Evidence Insight | Cross-database literature collection with source metadata preservation. |
| 9 | **bib-formatter** | Other | Convert between RIS, BibTeX, plain text, and CSL-JSON — works for any reference list. |
| 10 | **method-writing** | Academic Writing | Generate reproducible Methods sections from protocols and workflows. |

### Tier 2 — Data & document processing

| # | Skill | Source | What it gives weebot |
|---|-------|--------|---------------------|
| 11 | **spreadsheet-ops** | Other | CSV/Excel processing — merge, clean, statistics, formulas. Weebot currently has no spreadsheet skills. |
| 12 | **graph-interpretation** | Academic Writing | Interpret scientific graphs, write figure captions. Useful for any data visualization task. |
| 13 | **matplotlib** | Data Analysis | Comprehensive plotting with fine-grained control. Complements spreadsheet-ops. |
| 14 | **pdf-extract-experimental-materials** | Evidence Insight | Extract structured data from PDFs into CSV tables. Generalizes beyond medical. |
| 15 | **meta-abstract-screener** | Data Analysis | Title/abstract screening with structured Yes/No/Maybe decisions for literature filtering. |

### Tier 3 — Research design & quality

| # | Skill | Source | What it gives weebot |
|---|-------|--------|---------------------|
| 16 | **aim-and-hypothesis-designer** | Protocol Design | Design primary aims, secondary aims, and testable hypotheses from broad research ideas. |
| 17 | **research-proposal-generator** | Protocol Design | Generate comprehensive research proposals with hypothesis, mechanism, and budget. |
| 18 | **skill-auditor** | skill-auditor | Audit any agent skill for quality. Weebot can self-audit its own skills. |
| 19 | **research-grants** | Protocol Design | Write competitive grant proposals (NSF, NIH, DARPA formats). |
| 20 | **academic-highlight-generator** | Academic Writing | Generate Elsevier/SCI Highlights from manuscripts. |

---

## 4. Skills to EXCLUDE

The following categories should NOT be imported — they're too medical-domain-specific and would add noise:

- **All bioinformatics/genomics skills** (~100 skills): differential-expression, GSEA, WGCNA, ceRNA, CIBERSORT, scRNA-seq, ChIP-seq, variant-calling, etc. These require domain-specific R/Bioconductor tools.
- **Disease-specific clinical skills** (~50 skills): clinical-cohort, diagnostic-accuracy, survival-analysis (oncology-specific), FAERS pharmacovigilance, etc.
- **Persona/character skills** (~15 skills): bianque, mendel, etc. — these are role-play entities, not task skills.

**Recommended filter:** Import only from the `awesome-med-research-skills/` subdirectory (curated, quality-gated subset) and only the categories listed in the Top 20 above. Skip `scientific-skills/Data Analysis` entirely (141 bioinformatics skills).

---

## 5. Implementation Plan

### Step 1 — Copy curated skills (immediate, no code changes)

```bash
# Copy only the domain-agnostic skills from the curated set
cp -r ~/.weebot/skills/medical-research/awesome-med-research-skills/Evidence\ Insight \
     ~/.weebot/skills/medical-research/awesome-med-research-skills/Academic\ Writing \
     ~/.weebot/skills/ --parents
```

The `SkillRegistry._default_paths()` already scans `~/.weebot/skills/` for SKILL.md files. The `load_all()` fix (applied earlier) ensures skills are loaded at startup.

### Step 2 — Convert to weebot native format (optional, for better integration)

Weebot's `SkillConverter` (at `weebot/application/skills/skill_converter.py`) can convert Manus/OpenClaw-format SKILL.md files to weebot's `manifest.json` + `prompt.md` format. This enables tiering, approval gating, and emoji metadata.

```python
from weebot.application.skills.skill_converter import SkillConverter
converter = SkillConverter()
converter.convert_directory("~/.weebot/skills/Evidence Insight/", output="weebot/skills/builtin/")
```

### Step 3 — Reindex

Restart weebot. The `BM25SkillRetriever` will rebuild its index with the new skills. Verify with:

```python
registry = SkillRegistry()
registry.load_all()
print(f"Loaded {len(registry._skills)} skills")
```

### Step 4 — Test

Run a literature review task through weebot and verify that relevant skills are retrieved and injected into the executor's system prompt:

```
"Find the 5 most cited recent papers on attention mechanisms in transformers and summarize them"
```

Should trigger: `biomedical-search-strategy-builder`, `literature-extensive-read`, `multi-database-literature-collector`.

---

## 6. Summary

| Metric | Value |
|--------|-------|
| Current weebot skills | 9 |
| Medical-research skills available | 556 |
| Domain-agnostic skills identified | 203 |
| **Recommended to adopt** | **20** (Tier 1–3 above) |
| Skills to exclude | ~350 (bioinformatics, clinical, personas) |
| Format compatibility | ✅ Native — no conversion needed |
| Security risk | ✅ Low (audited separately) |
| Effort to adopt | ~5 minutes (copy files + restart) |
