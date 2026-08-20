"""Constraint extraction — identifies critical instructions that must survive compaction."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Pattern, Tuple


# Word-level tokenizer for check_step. Substring matching was the source of
# the gate's measured false positives ("all" matching inside "install").
_WORD_RE: Pattern = re.compile(r"[a-z0-9_]+")

# Function words carry no evidence that a step violates a constraint, but they
# are common enough to reach the match quorum on their own.
_STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "the", "to", "of", "in", "on", "for", "with", "and", "or",
    "any", "all", "my", "your", "our", "it", "its", "that", "this", "these",
    "those", "is", "are", "be", "been", "from", "at", "by", "into", "onto",
    "as", "if", "then", "than", "when", "while", "do", "does", "not", "no",
})


@dataclass
class Constraint:
    """A critical constraint extracted from context."""
    text: str
    constraint_type: str  # "negative", "positive", "safety"
    priority: int  # 1 = highest (safety), 2 = negative, 3 = positive


class ConstraintExtractor:
    """Extracts constraints that must be preserved during memory compaction.
    
    Based on MEMORY_ARTICLE findings that summarization can lose critical
    negative constraints ("DO NOT delete files") causing safety violations.
    """
    
    # Patterns for critical constraints (order matters - earlier = higher priority)
    PATTERNS: List[Tuple[Pattern, str, int]] = [
        # Safety-critical (priority 1)
        (re.compile(r"(?i)(?:safety|security|guardrail|credential|password|secret|token|api[_-]?key)\s*[:\-]?\s*([^\n.]+)"), "safety", 1),
        (re.compile(r"(?i)(?:never\s+(?:expose|share|log|print|send)\s+(?:credentials?|passwords?|secrets?|tokens?|api[_-]?keys?))"), "safety", 1),
        (re.compile(r"(?i)(?:do\s+not\s+(?:expose|share|log|print|send)\s+(?:credentials?|passwords?|secrets?|tokens?|api[_-]?keys?))"), "safety", 1),
        
        # Negative constraints (priority 2) - "DO NOT", "Never", etc.
        (re.compile(r"(?i)(?:do\s+not|don't|never|forbid|prohibit|avoid)\s+([^\n.]+)"), "negative", 2),
        (re.compile(r"(?i)(?:must\s+not|shall\s+not|cannot|can't)\s+([^\n.]+)"), "negative", 2),
        
        # Positive requirements (priority 3)
        (re.compile(r"(?i)(?:always|must|required|critical|essential|mandatory)\s+([^\n.]+)"), "positive", 3),
        (re.compile(r"(?i)(?:you\s+(?:must|have\s+to|need\s+to|should))\s+([^\n.]+)"), "positive", 3),
    ]
    
    def extract(self, text: str) -> List[Constraint]:
        """Extract all constraints from text.
        
        Args:
            text: The text to analyze for constraints.
            
        Returns:
            List of extracted constraints, sorted by priority (highest first).
        """
        constraints = []
        seen_texts = set()  # Deduplicate
        
        for pattern, ctype, priority in self.PATTERNS:
            for match in pattern.finditer(text):
                constraint_text = match.group(0).strip()
                # Normalize for deduplication
                normalized = constraint_text.lower().strip(".!; ")
                if normalized not in seen_texts:
                    seen_texts.add(normalized)
                    constraints.append(Constraint(
                        text=constraint_text,
                        constraint_type=ctype,
                        priority=priority
                    ))
        
        # Sort by priority (lower number = higher priority)
        return sorted(constraints, key=lambda c: c.priority)
    
    def format_constraints(self, constraints: List[Constraint]) -> str:
        """Format constraints for inclusion in compacted context.
        
        Args:
            constraints: List of constraints to format.
            
        Returns:
            Formatted constraint block string, or empty string if no constraints.
        """
        if not constraints:
            return ""
        
        lines = ["[CRITICAL CONSTRAINTS - DO NOT VIOLATE]"]
        current_priority = None
        
        for c in constraints:
            if c.priority != current_priority:
                current_priority = c.priority
                if c.priority == 1:
                    lines.append("  SAFETY:")
                elif c.priority == 2:
                    lines.append("  PROHIBITIONS:")
                else:
                    lines.append("  REQUIREMENTS:")
            lines.append(f"    • {c.text}")
        
        lines.append("[/CRITICAL CONSTRAINTS]")
        return "\n".join(lines)
    
    def check_step(self, step_description: str, constraints: List[Constraint]) -> List[Constraint]:
        """Return constraints that the step description appears to violate.

        Only negative and safety constraints (priority <= 2) are checked;
        positive requirements are not enforced here because partial progress
        is acceptable. Uses key-token matching — no LLM calls.

        Matching is whole-token, not substring, and stopwords are dropped
        before the vote. The previous ``tok in step_lower`` test counted
        "all" as a match inside "install" and let function words like "the"
        and "to" carry half the quorum on their own; measured against a real
        run it fired on 3 of 6 benign steps. This gate pauses the flow and
        asks the user, so a false positive is not free — see
        tasks/specs/side_constraint_integrity_plan.md Phase 5.4 defect 2.
        """
        step_tokens = {self._stem(t) for t in _WORD_RE.findall(step_description.lower())}

        violations: List[Constraint] = []
        for c in constraints:
            if c.priority > 2:
                continue
            action_match = re.search(
                r"(?:do\s+not|don't|never|must\s+not|shall\s+not|cannot|can't|avoid)\s+(.+)",
                c.text, re.IGNORECASE,
            )
            if not action_match:
                continue
            prohibited_phrase = action_match.group(1).strip().rstrip(".!;").lower()
            key_tokens = [
                self._stem(t)
                for t in _WORD_RE.findall(prohibited_phrase)
                if t not in _STOPWORDS
            ][:5]
            if not key_tokens:
                continue
            matched = sum(1 for tok in key_tokens if tok in step_tokens)
            # Majority of content tokens, rounding up: a single incidental
            # word shared with the step is not evidence of a violation.
            if matched >= max(1, (len(key_tokens) + 1) // 2):
                violations.append(c)
        return violations

    @staticmethod
    def _stem(token: str) -> str:
        """Crude singular/plural fold so "API keys" matches "API key".

        Not a real stemmer and not worth one here — the only disagreement
        this needs to survive is a trailing ``s`` between a constraint and a
        step description written by different authors.
        """
        if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
            return token[:-1]
        return token

    def has_critical_constraints(self, text: str) -> bool:
        """Quick check if text contains any critical (safety) constraints.
        
        Args:
            text: Text to check.
            
        Returns:
            True if any safety (priority 1) constraints found.
        """
        constraints = self.extract(text)
        return any(c.priority == 1 for c in constraints)
