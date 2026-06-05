"""Heuristic Analysis for tool selection."""
from typing import Dict, List

POWERSHELL_PRIORITY_KEYWORDS = [
    "file", "delete", "copy", "move", "directory", 
    "process", "kill", "system", "registry", "download"
]


class HeuristicRouter:
    """Analyzes tasks and routes to appropriate tool (PowerShell, Browser, Vane)."""
    
    @staticmethod
    def analyze_task(task: str) -> Dict[str, any]:
        """
        Returns:
            {
                "primary_tool": "powershell" | "browser" | "vane_search",
                "confidence": float,
                "reasoning": str,
                "suggested_sequence": List[str]
            }
        """
        task_lower = task.lower()
        
        # Scoring system
        ps_score = 0
        browser_score = 0
        vane_score = 0
        
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
        
        # VaneSearch indicators
        vane_indicators = [
            "cite", "citation", "academic", "paper", "research",
            "comprehensive research", "in-depth analysis", "sources",
            "evidence", "verifiable", "summarize with sources"
        ]
        
        for indicator in ps_indicators:
            if indicator in task_lower:
                ps_score += 1
        
        for indicator in browser_indicators:
            if indicator in task_lower:
                browser_score += 1
        
        for indicator in vane_indicators:
            if indicator in task_lower:
                vane_score += 2 # Higher weight for research tasks
        
        # Special cases: downloads can be either
        if "download" in task_lower:
            if "file from web" in task_lower or "url" in task_lower:
                browser_score += 0.5
            else:
                ps_score += 1
        
        # Decision
        max_score = max(ps_score, browser_score, vane_score)
        
        if max_score == ps_score and ps_score > 0:
            tool = "powershell"
            confidence = min(ps_score / (max_score + 0.1), 1.0)
            reasoning = f"Local system operations detected (score: {ps_score} vs browser: {browser_score}, vane: {vane_score})"
            sequence = ["powershell", "web_search", "vane_search"]
        elif max_score == vane_score and vane_score > 0:
            tool = "vane_search"
            confidence = min(vane_score / (max_score + 0.1), 1.0)
            reasoning = f"Research-oriented query detected (score: {vane_score} vs powershell: {ps_score}, browser: {browser_score})"
            sequence = ["vane_search", "web_search", "advanced_browser"]
        elif max_score == browser_score and browser_score > 0:
            tool = "browser"
            confidence = min(browser_score / (max_score + 0.1), 1.0)
            reasoning = f"Web-based operations detected (score: {browser_score} vs powershell: {ps_score}, vane: {vane_score})"
            sequence = ["web_search", "advanced_browser", "vane_search"]
        else: # Default to web_search if no strong indicators
            tool = "web_search"
            confidence = 0.5
            reasoning = "No strong indicators, defaulting to general web search."
            sequence = ["web_search", "vane_search", "advanced_browser"]
        
        return {
            "primary_tool": tool,
            "confidence": confidence,
            "reasoning": reasoning,
            "suggested_sequence": sequence
        }
