"""Task-model router — selects the best model per step based on task category.

Classifies a step description into one of: coding, file_ops, research,
review, planning, security, summarization, or general.  Each category
gets a purpose-tuned model instead of the one-size-fits-all cascade.

Never uses qwen3-coder for non-coding tasks.
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Optional


class TaskCategory(Enum):
    CODING = "coding"
    FILE_OPS = "file_ops"
    RESEARCH = "research"
    REVIEW = "review"
    PLANNING = "planning"
    SECURITY = "security"
    SUMMARIZATION = "summarization"
    GENERAL = "general"


# ── Category → best model ──────────────────────────────────────────

CATEGORY_MODEL: dict[TaskCategory, str] = {
    TaskCategory.CODING: "x-ai/grok-build-0.1",
    TaskCategory.FILE_OPS: "minimax/minimax-m3",
    TaskCategory.RESEARCH: "nvidia/nemotron-3-ultra-550b-a55b:free",
    TaskCategory.REVIEW: "x-ai/grok-4.3",
    TaskCategory.PLANNING: "nvidia/nemotron-3-ultra-550b-a55b:free",
    TaskCategory.SECURITY: "x-ai/grok-4.3",
    TaskCategory.SUMMARIZATION: "minimax/minimax-m3",
    TaskCategory.GENERAL: "nvidia/nemotron-3-ultra-550b-a55b:free",
}

# ── Keyword patterns ───────────────────────────────────────────────

_PATTERNS: dict[TaskCategory, list[re.Pattern]] = {
    TaskCategory.CODING: [
        re.compile(r"\b(code|coding|refactor|implement|debug|fix|patch|rewrite|overhaul|convert)\b", re.I),
        re.compile(r"\b(write|build|create|generate|develop|design)\s+(a|the|new)?\s*(html|css|js|javascript|python|typescript|react|vue|svelte|node|django|flask|fastapi|sql|database|schema|migration|docker|kubernetes|terraform|app|api|endpoint|route|component|page|site|script|function|class|module)\b", re.I),
        re.compile(r"\b(write|build|create|generate|develop|design)\s+(a|the|new)\s", re.I),
    ],
    TaskCategory.FILE_OPS: [
        re.compile(r"\b(view|list|read|open|cat|ls|dir|show|display)\s+(the\s+)?.*(file|directory|folder|path|dir|workspace|tasks|content)\b", re.I),
        re.compile(r"\b(create|write|make)\s+(a|the|new)?\s*(file|directory|folder|dir)\b", re.I),
        re.compile(r"\b(list|count|scan|enumerate)\s+(all|every)\s+(python\s+)?files?\b", re.I),
        re.compile(r"\b(str_replace|insert|edit|rename|copy|move|delete|remove)\b", re.I),
        re.compile(r"\b(check|see|verify|confirm)\s+(if|whether|that)\s+(.*file|.*exists|.*created|.*written|.*saved)\b", re.I),
        re.compile(r"\b(get-childitem|get-content|ls\s+-la|dir\s+/|find\s+\.)\b", re.I),
    ],
    TaskCategory.RESEARCH: [
        re.compile(r"\b(research|investigate|explore|discover|gather|collect|scrape|crawl|browse)\b", re.I),
        re.compile(r"\b(search|find|look\s+(up|into))\s+(for|the|a|an|relevant|information|papers?|articles?)\b", re.I),
        re.compile(r"\b(web\s*search|browser_inspector|advanced_browser|curl|fetch|http)\b", re.I),
        re.compile(r"\b(compare|analyze|synthesize|benchmark|competitor|market|trend)\b", re.I),
    ],
    TaskCategory.PLANNING: [
        re.compile(r"\b(plan|design|architecture|blueprint|outline|structure|define|spec|specification|brief)\b", re.I),
        re.compile(r"\b(create\s+(plan|roadmap|strategy)|task\s*(breakdown|decomposition))\b", re.I),
    ],
    TaskCategory.SECURITY: [
        re.compile(r"\b(vulnerability|exploit|injection|xss|csrf)\b", re.I),
        re.compile(r"\b(security|auth|authentication|authorization|permission|encrypt|decrypt|hash|token|api\s*key|secret|password|credential|sanitize|escape)\b", re.I),
    ],
    TaskCategory.REVIEW: [
        re.compile(r"\b(review|audit|critique|inspect|evaluate|assess)\s+(the|this|code|for|security|quality)\b", re.I),
        re.compile(r"\b(code\s*review|security\s*(audit|review)|quality\s*(check|review)|best\s*practice|convention|standard)\b", re.I),
        re.compile(r"\b(find\s+(bugs|issues|vulnerabilities|problems)|identify\s+(issues|problems|bugs))\b", re.I),
        re.compile(r"\b(unit\s*test|integration\s*test|e2e\s*test|test\s+coverage)\b", re.I),
        re.compile(r"\b(code\s*review|security\s*(audit|review)|quality|best\s*practice|convention|standard)\b", re.I),
    ],
    TaskCategory.PLANNING: [
        re.compile(r"\b(plan|design|architecture|blueprint|outline|structure|define|spec|specification|brief)\b", re.I),
        re.compile(r"\b(create\s+(plan|roadmap|strategy)|task\s*(breakdown|decomposition))\b", re.I),
    ],
    TaskCategory.SECURITY: [
        re.compile(r"\b(security|vulnerability|exploit|injection|xss|csrf|auth|authentication|authorization|permission|encrypt|decrypt|hash|token|api\s*key|secret|password|credential)\b", re.I),
        re.compile(r"\b(sandbox|isolate|quarantine|block|deny|allow|policy|guard|validate|sanitize|escape)\b", re.I),
    ],
    TaskCategory.SUMMARIZATION: [
        re.compile(r"\b(summarize|summary|recap|wrap\s*up|conclusion|report)\b", re.I),
        re.compile(r"\b(provide\s+a?\s*(summary|recap|overview|report)|what\s+(was|happened|did|we))\b", re.I),
    ],
}


# ── Classify ────────────────────────────────────────────────────────

def classify_step(description: str) -> TaskCategory:
    """Classify *description* into the best-matching TaskCategory.

    Scoring: each matching keyword adds 1 point per category.
    The highest-scoring category wins.  Ties break in priority order:
    SECURITY > REVIEW > CODING > PLANNING > RESEARCH > FILE_OPS > SUMMARIZATION.
    Falls back to GENERAL if no keywords match.
    """
    scores: dict[TaskCategory, int] = {}
    for cat, patterns in _PATTERNS.items():
        total = sum(1 for p in patterns if p.search(description))
        if total:
            scores[cat] = total

    if not scores:
        return TaskCategory.GENERAL

    priority = [
        TaskCategory.CODING,
        TaskCategory.SECURITY,
        TaskCategory.SUMMARIZATION,
        TaskCategory.REVIEW,
        TaskCategory.PLANNING,
        TaskCategory.RESEARCH,
        TaskCategory.FILE_OPS,
    ]
    best, best_score = TaskCategory.GENERAL, -1
    for cat in priority:
        s = scores.get(cat, 0)
        if s > best_score:
            best, best_score = cat, s
    return best if best_score > 0 else TaskCategory.GENERAL


def model_for_step(description: str) -> str:
    """Return the best model for a step's description."""
    cat = classify_step(description)
    return CATEGORY_MODEL[cat]


def category_for_step(description: str) -> str:
    """Return the category name for a step's description."""
    return classify_step(description).value
