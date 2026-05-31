#!/usr/bin/env python3
"""Weebot Behavior Reporting - Analysis and reporting on agent actions."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from weebot.core.behavior_tracker import LEDGER_DIR, TRUST_FILE, WEEBOT_DIR, SELF_KNOWLEDGE_FILE

logger = __import__("logging").getLogger(__name__)

# Regex patterns for parsing ledger entries
ENTRY_HEADER = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]$")
OVERRIDE_MARKER = re.compile(r"^\[OVERRIDE\]")
ACTION_LINE = re.compile(r"^ACTION\s+(\w+)\s+(.+)$")
INITIATED_LINE = re.compile(r"^INITIATED\s+(.+)$")
REASON_LINE = re.compile(r"^REASON\s+(.+)$")
DEST_LINE = re.compile(r"^DEST\s+(.+)$")
SESSION_COMMENT = re.compile(r"<!-- session:(\S+) agent:(\S+) -->")


@dataclass
class LedgerEntry:
    """Parsed ledger entry."""
    timestamp: str
    date: str
    action: str
    path: str
    initiated: str  # "by user" or "autonomous"
    session_id: str
    agent_version: str
    is_override: bool = False
    override_reason: Optional[str] = None
    dest_path: Optional[str] = None  # For moved files
    watcher_died: bool = False


class LedgerParser:
    """Parser for ledger markdown files."""
    
    @staticmethod
    def parse_entry(lines: List[str]) -> Optional[LedgerEntry]:
        """Parse a single entry from lines."""
        if not lines:
            return None
        
        # Parse header
        header_match = ENTRY_HEADER.match(lines[0])
        if not header_match:
            return None
        
        timestamp = header_match.group(1)
        date = timestamp[:10]
        
        entry = LedgerEntry(
            timestamp=timestamp,
            date=date,
            action="",
            path="",
            initiated="",
            session_id="",
            agent_version="",
        )
        
        # Check for override marker
        first_content = lines[1] if len(lines) > 1 else ""
        if OVERRIDE_MARKER.match(first_content):
            entry.is_override = True
            # Remove override marker from processing
            lines = [lines[0]] + lines[2:]
        
        # Parse content lines
        for line in lines[1:]:
            if line.startswith("ACTION"):
                match = ACTION_LINE.match(line)
                if match:
                    entry.action = match.group(1)
                    entry.path = match.group(2)
            elif line.startswith("INITIATED"):
                match = INITIATED_LINE.match(line)
                if match:
                    entry.initiated = match.group(1)
            elif line.startswith("REASON"):
                match = REASON_LINE.match(line)
                if match:
                    entry.override_reason = match.group(1)
            elif line.startswith("DEST"):
                match = DEST_LINE.match(line)
                if match:
                    entry.dest_path = match.group(1)
            elif "WATCHER STOPPED" in line:
                entry.watcher_died = True
            elif line.startswith("<!--"):
                match = SESSION_COMMENT.match(line)
                if match:
                    entry.session_id = match.group(1)
                    entry.agent_version = match.group(2)
        
        return entry
    
    @staticmethod
    def parse_file(md_file: Path) -> List[LedgerEntry]:
        """Parse all entries from a markdown file."""
        entries = []
        current_lines = []
        
        for line in md_file.read_text().splitlines():
            if line == "" and current_lines:
                # End of entry
                entry = LedgerParser.parse_entry(current_lines)
                if entry:
                    entries.append(entry)
                current_lines = []
            else:
                current_lines.append(line)
        
        # Handle last entry
        if current_lines:
            entry = LedgerParser.parse_entry(current_lines)
            if entry:
                entries.append(entry)
        
        return entries


class BehaviorReporter:
    """Generates reports on agent behavior."""
    
    def __init__(self):
        self.parser = LedgerParser()
    
    def _get_all_entries(self) -> List[LedgerEntry]:
        """Get all entries from all ledger files."""
        entries = []
        for md_file in sorted(LEDGER_DIR.glob("*.md")):
            entries.extend(self.parser.parse_file(md_file))
        return entries
    
    def _get_entries_for_date(self, date_str: str) -> List[LedgerEntry]:
        """Get entries for a specific date."""
        md_file = LEDGER_DIR / f"{date_str}.md"
        if md_file.exists():
            return self.parser.parse_file(md_file)
        return []
    
    def get_today_report(self) -> Dict:
        """Generate report for today."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self.get_date_report(today)
    
    def get_date_report(self, date_str: str) -> Dict:
        """Generate report for a specific date."""
        entries = self._get_entries_for_date(date_str)
        
        # Filter out watcher died events
        normal_entries = [e for e in entries if not e.watcher_died]
        
        if not normal_entries:
            return {
                "date": date_str,
                "total_actions": 0,
                "actions_by_type": {},
                "last_action": None,
                "summary": "No activity recorded today."
            }
        
        # Count by action type
        action_counts = Counter(e.action for e in normal_entries if e.action)
        
        # Get last action
        last = normal_entries[-1]
        
        # Count autonomous vs user-initiated
        autonomous = sum(1 for e in normal_entries if e.initiated == "autonomous")
        user_initiated = sum(1 for e in normal_entries if e.initiated == "by user")
        overrides = sum(1 for e in normal_entries if e.is_override)
        
        # Generate summary
        action_summary = ", ".join(f"{count} {action}" for action, count in action_counts.most_common())
        
        summary_parts = [f"The agent performed {len(normal_entries)} action{'s' if len(normal_entries) != 1 else ''} today: {action_summary}."]
        
        if autonomous and user_initiated:
            summary_parts.append(f"{autonomous} were autonomous and {user_initiated} were user-initiated.")
        elif autonomous:
            summary_parts.append(f"All {autonomous} were autonomous -- none sanctioned by the user.")
        else:
            summary_parts.append(f"All {user_initiated} were user-initiated.")
        
        if overrides:
            summary_parts.append(f"{overrides} action{'s' if overrides != 1 else ''} was marked as override.")
        
        return {
            "date": date_str,
            "total_actions": len(normal_entries),
            "actions_by_type": dict(action_counts),
            "autonomous_count": autonomous,
            "user_initiated_count": user_initiated,
            "override_count": overrides,
            "last_action": {
                "action": last.action,
                "path": last.path,
                "timestamp": last.timestamp
            },
            "summary": " ".join(summary_parts)
        }
    
    def get_recent_actions(self, count: int = 10, session_id: Optional[str] = None) -> List[LedgerEntry]:
        """Get recent actions, optionally filtered by session."""
        entries = self._get_all_entries()
        
        # Filter out watcher died
        entries = [e for e in entries if not e.watcher_died]
        
        # Filter by session if specified
        if session_id:
            entries = [e for e in entries if e.session_id == session_id]
        
        # Sort by timestamp (newest first)
        entries.sort(key=lambda e: e.timestamp, reverse=True)
        
        return entries[:count]
    
    def get_session_summary(self, session_id: str) -> Dict:
        """Get summary for a specific session."""
        entries = self._get_all_entries()
        session_entries = [e for e in entries if e.session_id == session_id and not e.watcher_died]
        
        if not session_entries:
            return {
                "session_id": session_id,
                "total_actions": 0,
                "summary": "No actions recorded for this session."
            }
        
        action_counts = Counter(e.action for e in session_entries if e.action)
        
        return {
            "session_id": session_id,
            "total_actions": len(session_entries),
            "actions_by_type": dict(action_counts),
            "start_time": min(e.timestamp for e in session_entries),
            "end_time": max(e.timestamp for e in session_entries),
        }
    
    def get_trust_report(self) -> Dict:
        """Get full trust report."""
        try:
            trust_data = json.loads(TRUST_FILE.read_text())
        except (json.JSONDecodeError, FileNotFoundError):
            trust_data = {"score": 1.0, "total": 0, "overrides": 0, "last_updated": ""}
        
        entries = self._get_all_entries()
        normal_entries = [e for e in entries if not e.watcher_died]
        
        score_pct = int(trust_data.get("score", 1.0) * 100)
        
        return {
            "score_percentage": score_pct,
            "score": trust_data.get("score", 1.0),
            "total_actions": trust_data.get("total", 0),
            "overrides": trust_data.get("overrides", 0),
            "last_updated": trust_data.get("last_updated", ""),
            "status": "trusted" if score_pct >= 90 else "review" if score_pct >= 70 else "supervision"
        }
    
    def format_console_report(self, date_str: Optional[str] = None) -> str:
        """Format a report for console display."""
        if date_str is None:
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        
        report = self.get_date_report(date_str)
        trust = self.get_trust_report()
        
        border = "━" * 50
        lines = [
            border,
            f"  WEEBOT BEHAVIOR REPORT  ·  {report['date']}",
            border,
            "",
            f"  TODAY      {report['total_actions']} action{'s' if report['total_actions'] != 1 else ''} recorded",
            "",
        ]
        
        if report['last_action']:
            last = report['last_action']
            lines.extend([
                f"  LAST       {last['action']} {Path(last['path']).name}",
                f"             {last['timestamp']}",
                "",
            ])
        
        lines.extend([
            f"  TRUST      {trust['score_percentage']}%",
            f"             {trust['total_actions']} total actions",
            f"             {trust['overrides']} override{'s' if trust['overrides'] != 1 else ''}",
            "",
            border,
            "  SUMMARY:",
            "",
        ])
        
        # Wrap summary text
        summary = report.get('summary', 'No summary available.')
        words = summary.split()
        line = "  "
        for word in words:
            if len(line) + len(word) + 1 > 48:
                lines.append(line)
                line = "  " + word
            else:
                line += " " + word if line != "  " else word
        if line != "  ":
            lines.append(line)
        
        lines.extend(["", border])
        
        return "\n".join(lines)


class SelfKnowledgeGenerator:
    """Generates agent self-knowledge from behavioral history."""
    
    def __init__(self):
        self.reporter = BehaviorReporter()
    
    def generate(self) -> str:
        """Generate self-knowledge markdown."""
        trust = self.reporter.get_trust_report()
        recent = self.reporter.get_recent_actions(5)
        
        # Analyze patterns
        all_entries = self.reporter._get_all_entries()
        normal_entries = [e for e in all_entries if not e.watcher_died]
        
        action_counts = Counter(e.action for e in normal_entries if e.action)
        
        # Most touched files
        file_counts = Counter(e.path for e in normal_entries)
        top_files = file_counts.most_common(5)
        
        content = f"""# Weebot Self-Knowledge

> Generated: {datetime.now(timezone.utc).isoformat()}  
> This file contains your behavioral history. Read it to understand your patterns and improve.

## Trust Profile

- **Current Score:** {trust['score_percentage']}%
- **Status:** {trust['status'].upper()}
- **Total Actions:** {trust['total_actions']:,}
- **Overrides:** {trust['overrides']}
- **Last Updated:** {trust['last_updated'][:19] if trust['last_updated'] else 'Never'}

## Recent Activity

| Time | Action | Path |
|------|--------|------|
"""
        
        for entry in recent:
            path_display = entry.path
            if len(path_display) > 40:
                path_display = "..." + path_display[-37:]
            content += f"| {entry.timestamp[11:19]} | {entry.action} | `{path_display}` |\n"
        
        content += "\n## Action Patterns\n\n"
        if action_counts:
            for action, count in action_counts.most_common(10):
                bar = "█" * int(count / max(action_counts.values()) * 20)
                content += f"- **{action}:** {count} {bar}\n"
        else:
            content += "_No patterns recorded yet._\n"
        
        content += "\n## Frequently Modified Files\n\n"
        if top_files:
            for path, count in top_files:
                display_path = path if len(path) < 50 else "..." + path[-47:]
                content += f"- `{display_path}` ({count} times)\n"
        else:
            content += "_No file patterns recorded yet._\n"
        
        content += f"""
## Recommendations

{self._generate_recommendations(trust, normal_entries)}

## Lessons from Overrides

"""
        
        # List override reasons
        overrides = [e for e in normal_entries if e.is_override and e.override_reason]
        if overrides:
            for entry in overrides[-5:]:  # Last 5 overrides
                content += f"- [{entry.timestamp[:10]}] {entry.override_reason}\n"
        else:
            content += "_No overrides recorded. Keep up the good work!_\n"
        
        content += """
---

## How to Use This File

1. **Read before acting** - Check your recent activity to avoid repeating mistakes
2. **Notice patterns** - If you keep modifying the same files, consider why
3. **Respect overrides** - If a user corrected you, learn from it
4. **Maintain trust** - High trust score means more autonomy

*This file is updated automatically. Do not edit manually.*
"""
        
        return content
    
    def _generate_recommendations(self, trust: Dict, entries: List[LedgerEntry]) -> str:
        """Generate personalized recommendations."""
        recs = []
        
        score = trust['score_percentage']
        if score >= 95:
            recs.append("✓ Your trust score is excellent. You have demonstrated reliable behavior.")
        elif score >= 80:
            recs.append("⚠ Your trust score is good but could be improved. Review any overrides to understand corrections.")
        else:
            recs.append("⚠ Your trust score needs improvement. Consider asking for user confirmation on significant changes.")
        
        if trust['overrides'] > 0:
            recs.append(f"📋 You have {trust['overrides']} override(s). Carefully review what went wrong to avoid repeating mistakes.")
        
        # Pattern-based recommendations
        action_counts = Counter(e.action for e in entries if e.action)
        if action_counts.get("deleted", 0) > action_counts.get("created", 0) * 2:
            recs.append("⚠ You delete files more often than you create them. Be careful not to remove important code.")
        
        if len(entries) > 100 and trust['overrides'] == 0:
            recs.append("✓ You have many actions with no overrides. Your reliability is high.")
        
        return "\n\n".join(recs) if recs else "_No specific recommendations at this time._"
    
    def save(self) -> Path:
        """Generate and save self-knowledge file."""
        content = self.generate()
        WEEBOT_DIR.mkdir(parents=True, exist_ok=True)
        SELF_KNOWLEDGE_FILE.write_text(content, encoding="utf-8")
        return SELF_KNOWLEDGE_FILE
    
    def get_content(self) -> str:
        """Get current self-knowledge or generate new."""
        if SELF_KNOWLEDGE_FILE.exists():
            return SELF_KNOWLEDGE_FILE.read_text(encoding="utf-8")
        return self.generate()


if __name__ == "__main__":
    # Demo
    reporter = BehaviorReporter()
    print(reporter.format_console_report())
    print("\n")
    
    gen = SelfKnowledgeGenerator()
    print(gen.generate()[:2000])
