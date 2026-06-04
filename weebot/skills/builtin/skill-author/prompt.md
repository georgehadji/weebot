---
name: skill-author
description: >
  Guide for writing high-quality weebot skills. Covers description writing,
  Progressive Disclosure, why-first principle, generalisation over overfitting,
  and trigger validation. When asked to create or improve a skill, use this
  skill to follow the methodology below. Does NOT cover domain analysis or
  team architecture — those are handled by harness generation.
metadata:
  emoji: 📝
---

# Skill Authoring Guide

Use this guide whenever you are asked to **create a new skill** or **improve an existing skill**. Follow the methodology in order — skipping steps leads to low-quality skills.

## Step 1: Description Writing (The Trigger)

The description is the **only** mechanism that triggers a skill. Write it to be **pushy** — LLMs are conservative about triggering skills.

### Rules

1. Describe **what the skill does** + **concrete trigger scenarios**
2. Include boundary conditions — what should NOT trigger this skill
3. Be slightly "pushy": use phrases like "MUST use this skill when..."

### Good Example

```yaml
description: >
  PDF file reading, text/table extraction, merge, split, rotate, watermark,
  encrypt/decrypt, OCR — ALL PDF operations. When the user mentions .pdf
  files or requests PDF output, you MUST use this skill. Particularly useful
  for conversion/editing/analysis beyond simple 'read this PDF'.
```

### Bad Example

```
description: "Processes data."
```

## Step 2: Progressive Disclosure Structure

Organise the skill directory with the 3-tier loading system:

```
skill-name/
├── SKILL.md              # < 500 lines — always loaded on trigger
├── manifest.json         # Name, version, dependencies
└── references/           # < loaded only on demand via get_reference()
    ├── advanced.md       # Optional: advanced configuration
    └── faq.md            # Optional: common edge cases
```

### When to Split into References

| Condition | Action |
|-----------|--------|
| SKILL.md exceeds 500 lines | Move detailed sections to `references/` files |
| Content is domain-specific (e.g. AWS vs GCP details) | Split into domain-specific reference files |
| If 300+ lines, add a Table of Contents at the top | Reference file must have ToC |

### Referencing from SKILL.md

```markdown
## Advanced Configuration
See [advanced.md](references/advanced.md) for advanced options.
Load only if the user asks about non-default configuration.
```

## Step 3: Why-First Body Writing

### Principle: Explain *why*, not just *what*

**Bad (rule without reason):**
```
ALWAYS use pdfplumber for tables. NEVER use PyPDF2.
```

**Good (reason drives correct behaviour):**
```
Use pdfplumber for table extraction. PyPDF2 is optimised for text and
does not preserve row/column structure. pdfplumber recognises cell
boundaries and returns structured data.
```

### Generalisation over Overfitting

When a test reveals a failure, fix the **principle**, not the specific case.

**Overfitted fix:**
```
If the column is named "Q4 Revenue", convert it to numeric.
```

**Generalised fix:**
```
If a column name contains "revenue", "amount", or "quantity" keywords,
attempt numeric conversion. Keep the original value if conversion fails.
```

### Tone: Imperative

Use "do X", "do not Y" — not "you should" or "it is recommended".

### Context is a Shared Resource

Every sentence must justify its token cost:
- "Does the LLM already know this?" → DELETE
- "Would the LLM make mistakes without this?" → KEEP
- "Would one example replace three sentences?" → USE AN EXAMPLE

## Step 4: Script Bundling

When testing reveals repeated code, bundle it.

| Signal | Action |
|--------|--------|
| Same helper script created in 3/3 test runs | Bundle in `scripts/` subdirectory |
| Same `pip install`/`npm install` every time | Add dependency installation step to the skill body |
| Same multi-step approach repeated | Document as standard procedure |
| Same workaround applied after same error | Document known issue + fix in the skill |

## Step 5: Output Format Definition

If output structure matters, include a template:

```markdown
## Report Structure
Follow this template exactly:

# [Title]
## Summary
## Key Findings
## Recommendations
```

## What NOT to Include

- README, CHANGELOG, or installation docs for humans
- Meta-info about skill creation process (test results, iteration history)
- General knowledge the LLM already has
- Domain analysis or team architecture (that is harness generation)
