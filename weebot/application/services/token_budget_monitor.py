"""Token budget monitoring — visibility into context window usage."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime, timedelta

from weebot.domain.models.session import Session
from weebot.domain.models.event import AgentEvent, MessageEvent, ToolEvent


@dataclass
class TokenBreakdown:
    """Token usage breakdown by component."""
    system_prompt: int = 0
    conversation_history: int = 0
    tool_outputs: int = 0
    plan_context: int = 0
    user_facts: int = 0
    available: int = 0
    total_used: int = 0
    max_capacity: int = 128000
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "system_prompt": self.system_prompt,
            "conversation_history": self.conversation_history,
            "tool_outputs": self.tool_outputs,
            "plan_context": self.plan_context,
            "user_facts": self.user_facts,
            "available": self.available,
            "total_used": self.total_used,
            "max_capacity": self.max_capacity,
            "usage_percent": round((self.total_used / self.max_capacity) * 100, 1) if self.max_capacity > 0 else 0,
        }
    
    def get_largest_component(self) -> tuple[str, int]:
        """Get the component consuming the most tokens."""
        components = [
            ("system_prompt", self.system_prompt),
            ("conversation_history", self.conversation_history),
            ("tool_outputs", self.tool_outputs),
            ("plan_context", self.plan_context),
            ("user_facts", self.user_facts),
        ]
        return max(components, key=lambda x: x[1])


class TokenBudgetMonitor:
    """Monitors token budget usage for sessions.
    
    Provides visibility into what's consuming context window,
    helping users understand when and why to compact memory.
    """
    
    # Single source of truth: weebot/config/constants.py
    from weebot.config.constants import CHARS_PER_TOKEN
    
    # Max entries per session in _history to prevent unbounded growth.
    _MAX_HISTORY_PER_SESSION = 200
    # Max distinct sessions tracked to prevent memory leak.
    _MAX_SESSIONS = 500

    def __init__(self, warning_threshold: float = 0.75, critical_threshold: float = 0.90):
        """Initialize the token budget monitor.
        
        Args:
            warning_threshold: Usage ratio to trigger warning (default 0.75 = 75%).
            critical_threshold: Usage ratio to trigger critical alert (default 0.90 = 90%).
        """
        self.warning_threshold = warning_threshold
        self.critical_threshold = critical_threshold
        self._history: Dict[str, List[tuple[datetime, int]]] = {}  # session_id -> [(timestamp, tokens)]
    
    def analyze_session(self, session: Session, max_tokens: int = 128000) -> TokenBreakdown:
        """Analyze token usage breakdown for a session.
        
        Args:
            session: The session to analyze.
            max_tokens: Maximum context window size.
            
        Returns:
            TokenBreakdown with detailed usage by component.
        """
        breakdown = TokenBreakdown(max_capacity=max_tokens)
        
        for event in session.events:
            tokens = self._estimate_event_tokens(event)
            breakdown.total_used += tokens
            
            # Categorize by event type
            if isinstance(event, MessageEvent):
                if event.role == "system":
                    breakdown.system_prompt += tokens
                else:
                    breakdown.conversation_history += tokens
            elif isinstance(event, ToolEvent):
                breakdown.tool_outputs += tokens
            else:
                # Plan events, step events, etc.
                breakdown.plan_context += tokens
        
        # Facts from session context
        facts_text = str(session.get_facts())
        breakdown.user_facts = len(facts_text) // self.CHARS_PER_TOKEN
        
        breakdown.available = max_tokens - breakdown.total_used
        
        # Record history
        if session.id not in self._history:
            # Evict oldest session when at capacity
            if len(self._history) >= self._MAX_SESSIONS:
                oldest = next(iter(self._history))
                del self._history[oldest]
            self._history[session.id] = []
        # Prune oldest entries when per-session cap reached
        if len(self._history[session.id]) >= self._MAX_HISTORY_PER_SESSION:
            self._history[session.id] = self._history[session.id][1:]
        self._history[session.id].append((datetime.now(), breakdown.total_used))
        
        return breakdown
    
    def _estimate_event_tokens(self, event: AgentEvent) -> int:
        """Estimate tokens for an event.
        
        Args:
            event: The event to estimate.
            
        Returns:
            Estimated token count.
        """
        try:
            text = str(event)
        except (MemoryError, RecursionError):
            # str(event) on pydantic models can blow up if a field
            # contains a very large object. Fall back to event type name.
            text = type(event).__name__
        return len(text) // self.CHARS_PER_TOKEN
    
    def get_status(self, breakdown: TokenBreakdown) -> str:
        """Get status level based on usage.
        
        Args:
            breakdown: The token breakdown to evaluate.
            
        Returns:
            Status string: "normal", "elevated", "warning", or "critical".
        """
        usage_ratio = breakdown.total_used / breakdown.max_capacity if breakdown.max_capacity > 0 else 0
        
        if usage_ratio >= self.critical_threshold:
            return "critical"  # 90%+
        elif usage_ratio >= self.warning_threshold:
            return "warning"  # 75-90%
        elif usage_ratio >= 0.5:
            return "elevated"  # 50-75%
        return "normal"  # < 50%
    
    def should_compact(self, breakdown: TokenBreakdown) -> bool:
        """Recommend compaction based on usage.
        
        Args:
            breakdown: The token breakdown to evaluate.
            
        Returns:
            True if compaction is recommended.
        """
        if breakdown.max_capacity == 0:
            return False
        return breakdown.total_used / breakdown.max_capacity >= self.warning_threshold
    
    def get_recommendation(self, breakdown: TokenBreakdown) -> Optional[str]:
        """Get a recommendation based on usage.
        
        Args:
            breakdown: The token breakdown to evaluate.
            
        Returns:
            Recommendation string, or None if no action needed.
        """
        status = self.get_status(breakdown)
        largest = breakdown.get_largest_component()
        
        if status == "critical":
            return f"CRITICAL: Context window at {breakdown.to_dict()['usage_percent']:.0f}%. Start a new session immediately."
        elif status == "warning":
            return f"WARNING: Context window at {breakdown.to_dict()['usage_percent']:.0f}%. Consider using /compact. Largest component: {largest[0]} ({largest[1]:,} tokens)."
        elif status == "elevated":
            return f"Context usage at {breakdown.to_dict()['usage_percent']:.0f}%. Monitor for growth."
        return None
    
    def get_growth_rate(self, session_id: str, window_minutes: int = 10) -> float:
        """Calculate token growth rate (tokens per minute).
        
        Args:
            session_id: The session to analyze.
            window_minutes: Time window for calculating growth.
            
        Returns:
            Tokens per minute growth rate (0.0 if insufficient data).
        """
        history = self._history.get(session_id, [])
        if len(history) < 2:
            return 0.0
        
        cutoff = datetime.now() - timedelta(minutes=window_minutes)
        recent = [(t, tokens) for t, tokens in history if t >= cutoff]
        
        if len(recent) < 2:
            return 0.0
        
        first_tokens = recent[0][1]
        last_tokens = recent[-1][1]
        time_diff = (recent[-1][0] - recent[0][0]).total_seconds() / 60
        
        if time_diff <= 0:
            return 0.0
        
        return (last_tokens - first_tokens) / time_diff
    
    def estimate_time_to_limit(self, session_id: str, max_tokens: int = 128000) -> Optional[float]:
        """Estimate minutes until context limit is reached.
        
        Args:
            session_id: The session to analyze.
            max_tokens: Maximum context window size.
            
        Returns:
            Estimated minutes until limit, or None if not growing.
        """
        growth_rate = self.get_growth_rate(session_id)
        if growth_rate <= 0:
            return None
        
        history = self._history.get(session_id, [])
        if not history:
            return None
        
        current_tokens = history[-1][1]
        remaining = max_tokens - current_tokens
        
        if remaining <= 0:
            return 0.0
        
        return remaining / growth_rate
    
    def clear_history(self, session_id: str) -> None:
        """Clear history for a session.
        
        Args:
            session_id: The session to clear.
        """
        self._history.pop(session_id, None)
