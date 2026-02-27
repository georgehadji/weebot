"""Heuristic Analysis for tool selection."""
from typing import Dict, List

POWERSHELL_PRIORITY_KEYWORDS = [
    "file", "delete", "copy", "move", "directory", 
    "process", "kill", "system", "registry", "download"
]


class HeuristicRouter:
    """Analyzes tasks and routes to appropriate tool (PowerShell vs Browser)."""
    
    @staticmethod
    def analyze_task(task: str) -> Dict[str, any]:
        """
        Returns:
            {
                "primary_tool": "powershell" | "browser",
                "confidence": float,
                "reasoning": str,
                "suggested_sequence": List[str]
            }
        """
        task_lower = task.lower()
        
        # Scoring system
        ps_score = 0
        browser_score = 0
        
        # PowerShell indicators
        ps_indicators = [
            "file", "folder", "directory", "delete", "copy", "move",
            "process", "kill", "stop", "system", "registry", "install",
            "download to", "save to disk", "workspace", "log", "event viewer"
        ]
        
        # Browser indicators
        browser_indicators = [
            "website", "webpage", "url", "click", "form", "login",
            "browser", "chrome", "edge", "navigate to", "scrape",
            "extract from site", "online", "web search"
        ]
        
        for indicator in ps_indicators:
            if indicator in task_lower:
                ps_score += 1
        
        for indicator in browser_indicators:
            if indicator in task_lower:
                browser_score += 1
        
        # Special cases: downloads can be either
        if "download" in task_lower:
            if "file from web" in task_lower or "url" in task_lower:
                browser_score += 0.5
            else:
                ps_score += 1
        
        # Decision
        if ps_score > browser_score:
            tool = "powershell"
            confidence = min(ps_score / (ps_score + browser_score + 0.1), 1.0)
            reasoning = f"Local system operations detected (score: {ps_score} vs {browser_score})"
            sequence = ["powershell", "browser"]
        else:
            tool = "browser"
            confidence = min(browser_score / (ps_score + browser_score + 0.1), 1.0)
            reasoning = f"Web-based operations detected (score: {browser_score} vs {ps_score})"
            sequence = ["browser", "powershell"]
        
        return {
            "primary_tool": tool,
            "confidence": confidence,
            "reasoning": reasoning,
            "suggested_sequence": sequence
        }
