"""Constraint extraction — identifies critical instructions that must survive compaction."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Pattern, Tuple


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
    
    def has_critical_constraints(self, text: str) -> bool:
        """Quick check if text contains any critical (safety) constraints.
        
        Args:
            text: Text to check.
            
        Returns:
            True if any safety (priority 1) constraints found.
        """
        constraints = self.extract(text)
        return any(c.priority == 1 for c in constraints)
