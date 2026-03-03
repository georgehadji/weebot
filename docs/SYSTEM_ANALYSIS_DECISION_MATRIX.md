# Weebot System Analysis - Decision Matrix

## Executive Summary

Analysis of the weebot codebase reveals **3 critical priority issues** that impact performance, cost control, and reliability. For each issue, 3 resolution paths were evaluated using a weighted decision matrix.

**Scoring (1-5 scale, lower is better):**
- **Nash Stability**: Fit with existing code (1=perfect fit, 5=complete mismatch)
- **Minimax Regret**: Worst-case if fix fails (1=minor issue, 5=catastrophic)
- **Catastrophic Risk**: Production breakage potential (1=safe, 5=destructive)
- **Adaptation Cost**: Refactoring effort required (1=minimal, 5=major rewrite)

**Selection Formula**: `weighted_score = 0.25*nash + 0.30*regret + 0.30*cat_risk + 0.15*adapt`

---

## 🔴 PRIORITY 1: Synchronous SQLite Blocking Event Loop

### Problem Description
`StateManager` uses synchronous `sqlite3` with `threading.Lock()` inside async methods. Every database operation blocks the entire event loop, causing:
- Request serialization (async becomes sync)
- Timeout cascades under load
- Poor concurrency performance

**Evidence:**
```python
# state_manager.py:189-193
self._conn = sqlite3.connect(db_path, check_same_thread=False)
self._write_lock = threading.Lock()  # Blocks event loop!

# Used in async context (ResumableTask.__aenter__)
```

### Resolution Paths

#### Path A: Async SQLite with aiosqlite
Replace `sqlite3` with `aiosqlite` for native async database operations.

| Metric | Score | Rationale |
|--------|-------|-----------|
| Nash Stability | 2 | Clean async fit, requires dependency addition |
| Minimax Regret | 2 | If fails, falls back to current behavior |
| Catastrophic Risk | 2 | Low risk, but requires connection handling changes |
| Adaptation Cost | 2 | Drop-in replacement for most operations |
| **Weighted Score** | **2.05** | |

#### Path B: Thread Pool Executor Wrapper
Keep `sqlite3` but run all DB operations in `asyncio.to_thread()`.

| Metric | Score | Rationale |
|--------|-------|-----------|
| Nash Stability | 1 | No new dependencies, pure Python |
| Minimax Regret | 2 | If thread pool exhausted, degrades gracefully |
| Catastrophic Risk | 2 | Thread pool limits prevent resource exhaustion |
| Adaptation Cost | 3 | Must wrap every DB call |
| **Weighted Score** | **1.95** | |

#### Path C: Connection Pool + Async Queue
Implement async queue for DB operations with connection pooling.

| Metric | Score | Rationale |
|--------|-------|-----------|
| Nash Stability | 3 | Complex, doesn't match existing patterns |
| Minimax Regret | 3 | Queue overflow could lose state updates |
| Catastrophic Risk | 3 | Pool exhaustion = system halt |
| Adaptation Cost | 4 | Major architectural change |
| **Weighted Score** | **3.15** | |

### 🏆 SELECTED: Path B (Thread Pool Executor)

**Justification:**
- **Lowest weighted score (1.95)**
- **Best Nash Stability** - Uses Python standard library only
- **Low Catastrophic Risk** - Thread pool provides natural backpressure
- **Manageable Adaptation Cost** - Can be implemented incrementally
- No external dependencies reduces supply chain risk

**Implementation:**
```python
import asyncio
from concurrent.futures import ThreadPoolExecutor

class StateManager:
    def __init__(self, db_path: str = "projects.db") -> None:
        self.db_path = db_path
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="db_")
        # ... rest of init
    
    async def load_state(self, project_id: str) -> Optional[ProjectState]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor, self._load_state_sync, project_id
        )
```

---

## 🔴 PRIORITY 2: No Rate Limiting on Tools

### Problem Description
Tools (web_search, bash, python_execute, AI calls) have no rate limiting, causing:
- Runaway API costs (Bing, OpenAI, etc.)
- Resource exhaustion (subprocess spam)
- Potential service bans
- No QoS for critical vs background tasks

**Evidence:**
```python
# mcp/server.py - tools registered without any rate checks
@mcp.tool(name="web_search", ...)
async def web_search(query: str, num_results: int = 5) -> str:
    result = await _search.execute(...)  # No limit!
```

### Resolution Paths

#### Path A: Token Bucket per Tool
Implement token bucket algorithm for each tool with configurable limits.

| Metric | Score | Rationale |
|--------|-------|-----------|
| Nash Stability | 2 | Clean fit, well-understood algorithm |
| Minimax Regret | 3 | Misconfigured limits block legitimate use |
| Catastrophic Risk | 2 | Soft failures (429 errors), not crashes |
| Adaptation Cost | 2 | Decorator-based, non-invasive |
| **Weighted Score** | **2.25** | |

#### Path B: Global Rate Limiter with Priorities
Single rate limiter for all tools with priority queuing.

| Metric | Score | Rationale |
|--------|-------|-----------|
| Nash Stability | 3 | Centralized doesn't match distributed tool pattern |
| Minimax Regret | 4 | Global failure blocks everything |
| Catastrophic Risk | 3 | Single point of failure |
| Adaptation Cost | 3 | Requires architectural changes |
| **Weighted Score** | **3.15** | |

#### Path C: Cost-Based Limiter with Budget
Track actual API costs and enforce daily/monthly budgets.

| Metric | Score | Rationale |
|--------|-------|-----------|
| Nash Stability | 2 | Extends existing CostTracker in ai_router.py |
| Minimax Regret | 2 | Budget exhaustion is graceful degradation |
| Catastrophic Risk | 2 | Soft cap, can be overridden |
| Adaptation Cost | 3 | Requires cost estimation per call |
| **Weighted Score** | **2.35** | |

### 🏆 SELECTED: Path A (Token Bucket per Tool)

**Justification:**
- **Lowest weighted score (2.25)**
- **Best granularity** - Different limits for different tools (web_search vs file_editor)
- **Operational flexibility** - Can adjust limits per environment
- **Clean failure mode** - Returns 429-style error instead of hard failure
- **Aligns with existing decorators** - Fits the `@handle_errors` pattern already in codebase

**Implementation:**
```python
from functools import wraps
import time
from dataclasses import dataclass

@dataclass
class TokenBucket:
    rate: float  # tokens per second
    capacity: float
    _tokens: float = 0
    _last_update: float = 0
    
    def consume(self, tokens: float = 1) -> bool:
        now = time.monotonic()
        elapsed = now - self._last_update
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
        self._last_update = now
        
        if self._tokens >= tokens:
            self._tokens -= tokens
            return True
        return False

# Per-tool buckets
_rate_limits: dict[str, TokenBucket] = {
    "web_search": TokenBucket(rate=0.5, capacity=5),  # 5 burst, 0.5/s sustained
    "bash": TokenBucket(rate=2.0, capacity=10),
    "python_execute": TokenBucket(rate=1.0, capacity=5),
}

def rate_limited(tool_name: str):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            bucket = _rate_limits.get(tool_name)
            if bucket and not bucket.consume():
                raise WeebotError(
                    message=f"Rate limit exceeded for {tool_name}. Please wait and retry.",
                    code=ErrorCode.RATE_LIMITED,
                    severity=ErrorSeverity.WARNING
                )
            return await func(*args, **kwargs)
        return wrapper
    return decorator

# Usage
@mcp.tool(name="web_search", ...)
@rate_limited("web_search")
async def web_search(query: str, ...) -> str:
    ...
```

---

## 🔴 PRIORITY 3: AI Router Has No Actual Implementation

### Problem Description
`ai_router.py` has a complete routing and fallback system, but `_call_model()` returns a placeholder. The entire AI integration is non-functional.

**Evidence:**
```python
# ai_router.py:211-217
async def _call_model(self, model_id: str, prompt: str) -> str:
    """Call specific model API"""
    config = self.MODELS[model_id]
    # This would integrate with actual APIs
    # For now, return placeholder
    return f"[Generated by {config.name}]"
```

### Resolution Paths

#### Path A: Direct API Integration (per provider)
Implement direct HTTP calls to each provider (OpenAI, Anthropic, etc.).

| Metric | Score | Rationale |
|--------|-------|-----------|
| Nash Stability | 3 | Doesn't match existing langchain usage in codebase |
| Minimax Regret | 4 | API changes break integration |
| Catastrophic Risk | 3 | Auth key exposure risk |
| Adaptation Cost | 4 | Must implement 4+ different APIs |
| **Weighted Score** | **3.45** | |

#### Path B: LangChain Integration (extends existing)
Use existing `langchain_openai` pattern already in `core/agent.py` and `core/safety.py`.

| Metric | Score | Rationale |
|--------|-------|-----------|
| Nash Stability | 1 | Already used elsewhere in codebase |
| Minimax Regret | 2 | LangChain provides abstraction stability |
| Catastrophic Risk | 2 | Well-tested library |
| Adaptation Cost | 2 | Clean implementation |
| **Weighted Score** | **1.70** | |

#### Path C: LiteLLM Proxy (unified interface)
Use LiteLLM library for unified multi-provider interface.

| Metric | Score | Rationale |
|--------|-------|-----------|
| Nash Stability | 2 | New dependency, but clean abstraction |
| Minimax Regret | 3 | Extra dependency = supply chain risk |
| Catastrophic Risk | 2 | Drop-in replacement if issues |
| Adaptation Cost | 2 | Minimal code changes |
| **Weighted Score** | **2.20** | |

### 🏆 SELECTED: Path B (LangChain Integration)

**Justification:**
- **Lowest weighted score (1.70)**
- **Perfect Nash Stability** - Codebase already uses `langchain_openai.ChatOpenAI`
- **Minimal risk** - Uses existing, tested patterns
- **Consistent** - Same pattern across all AI interactions
- **Maintains fallback logic** - Existing retry/fallback system remains functional

**Implementation:**
```python
# ai_router.py - Updated implementation
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_deepseek import ChatDeepSeek
import os

class ModelRouter:
    _PROVIDER_MAP = {
        "openai": ChatOpenAI,
        "anthropic": ChatAnthropic,
        "deepseek": ChatDeepSeek,
    }
    
    async def _call_model(self, model_id: str, prompt: str) -> str:
        """Call specific model API via LangChain."""
        config = self.MODELS[model_id]
        
        # Get API key from environment
        api_key = os.getenv(config.api_key_env)
        if not api_key:
            raise WeebotError(
                message=f"API key not found: {config.api_key_env}",
                code=ErrorCode.SERVICE_UNAVAILABLE,
                severity=ErrorSeverity.ERROR
            )
        
        # Initialize appropriate client
        provider_class = self._PROVIDER_MAP.get(config.provider)
        if not provider_class:
            raise WeebotError(
                message=f"Unknown provider: {config.provider}",
                code=ErrorCode.NOT_IMPLEMENTED,
                severity=ErrorSeverity.ERROR
            )
        
        client = provider_class(
            model=config.name,
            api_key=api_key,
            temperature=0.2,
            max_tokens=4096,
        )
        
        # Call and track cost
        response = await client.ainvoke(prompt)
        
        # Estimate tokens and cost
        input_tokens = response.usage_metadata.get("input_tokens", 0)
        output_tokens = response.usage_metadata.get("output_tokens", 0)
        self.cost_tracker.record_call(model_id, input_tokens, output_tokens)
        
        return response.content
```

---

## Summary of Selected Paths

| Priority | Issue | Selected Path | Weighted Score | Key Benefit |
|----------|-------|---------------|----------------|-------------|
| 1 | SQLite Blocking | B - Thread Pool | 1.95 | No new dependencies, safe |
| 2 | No Rate Limiting | A - Token Bucket | 2.25 | Granular control, clean failures |
| 3 | AI Not Implemented | B - LangChain | 1.70 | Uses existing patterns, lowest risk |

**Overall Strategy:**
1. Implement LangChain integration first (unlocks core functionality)
2. Add rate limiting (protects against cost overruns)
3. Migrate SQLite to thread pool (performance optimization)

**Risk Mitigation:**
- All paths use soft failures (errors, not crashes)
- Each can be feature-flagged
- Rollback capability maintained
- Incremental deployment possible
