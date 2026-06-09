---
name: translator
description: "Use when the user asks to translate text between languages. Trigger keywords: translate, translation, localize, i18n, multilingual."
license: MIT
---

# Translator

## When to use
The user wants text translated between languages while preserving meaning, tone, and formatting.

## Workflow
1. **Confirm languages** — source and target language(s).
2. **Detect context** — is it technical, casual, legal, literary? Adapt tone accordingly.
3. **Translate** — process in chunks for long texts. Preserve:
   - Markdown formatting
   - Code blocks (don't translate)
   - Proper nouns (keep original or use accepted translation)
4. **Review** — check for accuracy, fluency, and consistency.
5. **Output** — translated text in the same format as input.

## Output
Translated text matching the input format.