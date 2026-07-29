# Weebot × CatchMe Integration — Implementation Plan

> **Version:** 1.0  
> **Date:** 2026-04-21  
> **Status:** Planning Complete — Ready for Execution  
> **Estimated Duration:** 4-6 weeks (single developer)  
> **Target Weebot Version:** v2.8.0  

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Architecture Overview](#2-architecture-overview)
3. [Phase 1: Foundation & Context Enrichment Layer](#3-phase-1-foundation--context-enrichment-layer)
4. [Phase 2: Retrieval Adapter & Browser Enhancement](#4-phase-2-retrieval-adapter--browser-enhancement)
5. [Phase 3: Cost Optimization & Vision Pipeline](#5-phase-3-cost-optimization--vision-pipeline)
6. [Phase 4: Hierarchical Planning & Polish](#6-phase-4-hierarchical-planning--polish)
7. [Security & Privacy Considerations](#7-security--privacy-considerations)
8. [Testing Strategy](#8-testing-strategy)
9. [Risk Register](#9-risk-register)
10. [Appendix: File Inventory](#10-appendix-file-inventory)

---

## 1. Executive Summary

This plan details the safe, incremental integration of **CatchMe** (personal digital footprint recorder) capabilities into **Weebot** (production-grade AI agent framework). The integration follows weebot's existing Clean/Hexagonal Architecture patterns and maintains backward compatibility.

### Integration Roadmap

```
Phase 1 (Week 1-2):  Foundation + Context Enrichment  →  Immediate UX boost
Phase 2 (Week 2-3):  Retrieval Adapter + Browser      →  Enhanced capabilities  
Phase 3 (Week 3-4):  Cost Optimization + Vision       →  Production hardening
Phase 4 (Week 4-6):  Hierarchical Planning + Polish   →  Architectural evolution
```

### Key Principles

- **Optional Integration:** CatchMe is never required — graceful degradation if unavailable
- **Privacy First:** All sensitive data (screenshots, keystrokes) stays in CatchMe's local storage
- **Security Boundary:** Weebot only reads *summarized* context, never raw keystrokes
- **Clean Architecture:** New code lives in `integrations/` following existing port/adapter patterns
- **Test Coverage:** Every new module has ≥90% test coverage (matching weebot's standard)

---

## 2. Architecture Overview

### 2.1 Current Weebot Architecture (Simplified)

```
┌─────────────────────────────────────────────────────────────────┐
│                        INTERFACES LAYER                          │
│   (CLI, Web UI, API endpoints)                                  │
├─────────────────────────────────────────────────────────────────┤
│                      APPLICATION LAYER                           │
│   ┌──────────────┐ ┌──────────────┐ ┌──────────────────────┐   │
│   │ PlanActFlow  │ │   CQRS       │ │  Services            │   │
│   │  (planner)   │ │  (commands)  │ │  (memory, tokens)    │   │
│   └──────────────┘ └──────────────┘ └──────────────────────┘   │
├─────────────────────────────────────────────────────────────────┤
│                        DOMAIN LAYER                              │
│   ┌──────────────┐ ┌──────────────┐ ┌──────────────────────┐   │
│   │   Session    │ │    Plan      │ │   AgentEvent         │   │
│   │  (events)    │ │  (steps)     │ │   (messages)         │   │
│   └──────────────┘ └──────────────┘ └──────────────────────┘   │
├─────────────────────────────────────────────────────────────────┤
│                     INFRASTRUCTURE LAYER                         │
│   ┌──────────────┐ ┌──────────────┐ ┌──────────────────────┐   │
│   │  Browser     │ │   LLM        │ │   Event Store        │   │
│   │  (Playwright)│ │  (Adapters)  │ │   (SQLite)           │   │
│   └──────────────┘ └──────────────┘ └──────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Target Architecture with CatchMe Integration

```
┌─────────────────────────────────────────────────────────────────┐
│                        INTERFACES LAYER                          │
│   (CLI, Web UI, API endpoints)                                  │
├─────────────────────────────────────────────────────────────────┤
│                      APPLICATION LAYER                           │
│   ┌──────────────┐ ┌──────────────┐ ┌──────────────────────┐   │
│   │ PlanActFlow  │ │   CQRS       │ │  Services            │   │
│   │  (planner)   │ │  (commands)  │ │  (memory, tokens)    │   │
│   └──────┬───────┘ └──────────────┘ └──────────────────────┘   │
│          │                                                       │
│   ┌──────┴──────────────────────────────────────────────────┐   │
│   │              CatchMe Integration Layer (NEW)             │   │
│   │  ┌────────────┐ ┌────────────┐ ┌────────────────────┐   │   │
│   │  │  Context   │ │ Retrieval  │ │ Browser Content    │   │   │
│   │  │   Bridge   │ │  Adapter   │ │    Enhancement     │   │   │
│   │  └────────────┘ └────────────┘ └────────────────────┘   │   │
│   │  ┌────────────┐ ┌────────────┐ ┌────────────────────┐   │   │
│   │  │   Cost     │ │   Vision   │ │  Hierarchical      │   │   │
│   │  │  Tracker   │ │  Pipeline  │ │   Planner          │   │   │
│   │  └────────────┘ └────────────┘ └────────────────────┘   │   │
│   └──────────────────────────┬───────────────────────────────┘   │
├──────────────────────────────┼───────────────────────────────────┤
│                        DOMAIN LAYER                              │
│   ┌──────────────┐ ┌─────────┴──┐ ┌──────────────────────┐   │
│   │   Session    │ │    Plan    │ │   AgentEvent         │   │
│   │  (+context)  │ │  (+hier)   │ │   (+catchme_ctx)     │   │
│   └──────────────┘ └────────────┘ └──────────────────────┘   │
├──────────────────────────────┼───────────────────────────────────┤
│                     INFRASTRUCTURE LAYER                         │
│   ┌──────────────┐ ┌─────────┴──┐ ┌──────────────────────┐   │
│   │  Browser     │ │   LLM      │ │   Event Store        │   │
│   │  (Playwright)│ │  (Cascade) │ │   (SQLite)           │   │
│   └──────────────┘ └────────────┘ └──────────────────────┘   │
├──────────────────────────────┼───────────────────────────────────┤
│                     INTEGRATIONS LAYER (NEW)                     │
│   ┌──────────────────────────┴──────────────────────────┐      │
│   │              CatchMe (external process)              │      │
│   │  ┌────────────┐ ┌────────────┐ ┌──────────────────┐ │      │
│   │  │  Recorders │ │  Activity  │ │   Retrieval      │ │      │
│   │  │  (6 types) │ │    Tree    │ │   (LLM-nav)      │ │      │
│   │  └────────────┘ └────────────┘ └──────────────────┘ │      │
│   └─────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

### 2.3 Integration Boundaries

| Boundary | Rule |
|----------|------|
| **Weebot → CatchMe** | Read-only. Weebot queries CatchMe via its public API (`catchme.pipelines.retrieve`, `catchme.pipelines.tree`). Never writes to CatchMe's store. |
| **CatchMe → Weebot** | None. CatchMe is independent; weebot pulls context when needed. |
| **Privacy Boundary** | Weebot never accesses raw keystrokes or screenshots directly. Only reads LLM-generated summaries and structured metadata. |
| **Security Boundary** | All CatchMe data is local-only. Weebot's BashGuard and validation pipeline still apply to any CatchMe-derived content used in prompts. |

---

## 3. Phase 1: Foundation & Context Enrichment Layer

**Duration:** Week 1-2  
**Goal:** Enable weebot to understand what the user was doing before starting a session  
**Impact:** Immediate UX improvement — contextual greetings, continuity suggestions  

### 3.1 Tasks

#### Task 1.1: Create Integration Package Structure

**Files to Create:**
```
weebot/integrations/__init__.py
weebot/integrations/catchme/__init__.py
weebot/integrations/catchme/config.py
weebot/integrations/catchme/exceptions.py
weebot/integrations/catchme/adapter_base.py
```

**Details:**
- `config.py`: Configuration dataclass for CatchMe integration settings
  - `enabled: bool = False` — master switch
  - `catchme_data_dir: Path` — path to CatchMe's data directory
  - `context_window_minutes: int = 30` — how far back to look for context
  - `max_context_items: int = 5` — max context items to inject
  - `privacy_level: str = "summary"` — "summary" | "detailed" | "minimal"
- `exceptions.py`: Custom exceptions (`CatchMeNotAvailable`, `CatchMeError`)
- `adapter_base.py`: Abstract base class for all CatchMe adapters

**Acceptance Criteria:**
- [ ] Package imports without errors
- [ ] Config has sensible defaults
- [ ] 100% test coverage for config and exceptions

---

#### Task 1.2: Build CatchMe Availability Detector

**Files to Create:**
```
weebot/integrations/catchme/detector.py
weebot/integrations/catchme/tests/test_detector.py
```

**Details:**
```python
class CatchMeDetector:
    """Detects whether CatchMe is installed and running."""
    
    def is_installed(self) -> bool:
        """Check if catchme package is importable."""
        
    def is_running(self) -> bool:
        """Check if CatchMe recorder process is active."""
        
    def get_data_dir(self) -> Path | None:
        """Resolve CatchMe's data directory."""
        
    def get_version(self) -> str | None:
        """Get installed CatchMe version."""
```

**Acceptance Criteria:**
- [ ] Correctly detects installed CatchMe
- [ ] Correctly reports when CatchMe is absent (no errors)
- [ ] Returns None for data dir when not installed
- [ ] All tests pass on Windows, macOS, Linux

---

#### Task 1.3: Implement Context Bridge

**Files to Create:**
```
weebot/integrations/catchme/context_bridge.py
weebot/integrations/catchme/models.py
weebot/integrations/catchme/tests/test_context_bridge.py
```

**Details:**

The Context Bridge translates CatchMe's activity tree into weebot-compatible context.

```python
# models.py
class UserContextItem(BaseModel):
    """A single piece of user context from CatchMe."""
    timestamp: datetime
    category: str  # "coding", "browsing", "reading", "communication"
    app: str
    location: str  # file path, URL, or window title
    summary: str  # LLM-generated summary from CatchMe
    confidence: float  # 0.0-1.0

class UserActivityContext(BaseModel):
    """Aggregated user context for a time window."""
    window_start: datetime
    window_end: datetime
    items: list[UserContextItem]
    primary_activity: str  # Most significant activity
    recent_files: list[str]
    recent_urls: list[str]
    clipboard_preview: str | None
```

```python
# context_bridge.py
class CatchMeContextBridge:
    """Bridge between CatchMe's activity tree and weebot's memory system."""
    
    def __init__(self, config: CatchMeConfig, detector: CatchMeDetector):
        self._config = config
        self._detector = detector
        self._available = detector.is_installed()
    
    @property
    def available(self) -> bool:
        return self._available and self._config.enabled
    
    def get_recent_context(self, minutes: int | None = None) -> UserActivityContext | None:
        """Fetch user's recent activity as structured context.
        
        Returns None if CatchMe is unavailable or has no data.
        """
        if not self.available:
            return None
        
        # Use CatchMe's tree API to get recent sessions
        # Filter by time window
        # Extract summaries and metadata
        # Return structured context
    
    def get_current_focus(self) -> UserContextItem | None:
        """Get what the user is currently focused on."""
        
    def get_recent_files(self, hours: int = 24) -> list[str]:
        """Get list of recently accessed files."""
        
    def get_recent_urls(self, hours: int = 24) -> list[str]:
        """Get list of recently visited URLs."""
```

**Privacy Controls:**
- `privacy_level="minimal"`: Only app names and window titles, no summaries
- `privacy_level="summary"`: App names + LLM summaries (recommended default)
- `privacy_level="detailed"`: Includes file paths, URLs, clipboard previews

**Acceptance Criteria:**
- [ ] Returns None gracefully when CatchMe unavailable
- [ ] Correctly parses CatchMe's tree format
- [ ] Respects privacy_level setting
- [ ] Filters by time window correctly
- [ ] Limits context items to max_context_items
- [ ] ≥90% test coverage

---

#### Task 1.4: Integrate with Session Initialization

**Files to Modify:**
```
weebot/domain/models/session.py          # Add context field
weebot/application/flows/plan_act_flow.py # Inject context at session start
weebot/application/agents/planner.py      # Use context in planning
```

**Details:**

1. **Session model enhancement:**
```python
class Session(BaseModel):
    # ... existing fields ...
    user_context: UserActivityContext | None = Field(default=None)
    
    def with_context(self, context: UserActivityContext | None) -> "Session":
        return self.model_copy(update={"user_context": context})
```

2. **PlanActFlow integration:**
```python
class PlanActFlow(BaseFlow):
    def __init__(self, ..., catchme_bridge: CatchMeContextBridge | None = None):
        # ... existing init ...
        self._catchme_bridge = catchme_bridge
    
    async def run(self, prompt: str) -> AsyncGenerator[AgentEvent, None]:
        # Enrich session with user context at start
        if self._catchme_bridge and self._catchme_bridge.available:
            context = self._catchme_bridge.get_recent_context()
            if context:
                self._session = self._session.with_context(context)
                logger.info("Enriched session with CatchMe context: %d items", len(context.items))
        
        # ... rest of existing run logic ...
```

3. **PlannerAgent integration:**
```python
class PlannerAgent:
    def _build_system_prompt(self, ...) -> str:
        prompt = "...existing prompt..."
        
        # Add user context section if available
        if session.user_context:
            prompt += self._format_user_context(session.user_context)
        
        return prompt
    
    def _format_user_context(self, context: UserActivityContext) -> str:
        parts = ["\n## User's Recent Activity"]
        for item in context.items[:3]:
            parts.append(f"- [{item.app}] {item.summary}")
        if context.recent_files:
            parts.append(f"\nRecent files: {', '.join(context.recent_files[:3])}")
        return "\n".join(parts)
```

**Acceptance Criteria:**
- [ ] Session accepts user_context without breaking existing code
- [ ] Context is injected at session start when available
- [ ] Planner includes context in system prompt
- [ ] Context is truncated to fit token budget
- [ ] No errors when CatchMe is unavailable
- [ ] Existing tests still pass

---

#### Task 1.5: Add Contextual Greeting Suggestions

**Files to Create:**
```
weebot/integrations/catchme/suggestion_engine.py
weebot/integrations/catchme/tests/test_suggestion_engine.py
```

**Details:**
```python
class ContextualSuggestionEngine:
    """Generate contextual conversation starters based on user activity."""
    
    def suggest_opening(self, context: UserActivityContext) -> list[str]:
        """Generate 1-3 contextual opening suggestions.
        
        Examples:
        - "You were working on payment_gateway.py in VS Code. Continue?"
        - "I see you copied a Stripe API key. Setting up payments?"
        - "You were reading Stripe docs in Chrome. Need help integrating?"
        """
        
    def _detect_continuity(self, context: UserActivityContext) -> bool:
        """Detect if user was in the middle of a task."""
        
    def _generate_continuation_prompt(self, item: UserContextItem) -> str:
        """Generate a prompt suggesting task continuation."""
```

**Acceptance Criteria:**
- [ ] Generates relevant suggestions based on activity
- [ ] Limits to 1-3 suggestions
- [ ] Suggestions are concise (<100 chars)
- [ ] No suggestions when no meaningful context
- [ ] ≥90% test coverage

---

### 3.2 Phase 1 Deliverables

| Deliverable | File(s) | Tests |
|------------|---------|-------|
| Integration package | `weebot/integrations/catchme/` | `tests/` |
| Context Bridge | `context_bridge.py`, `models.py` | `test_context_bridge.py` |
| Session Enhancement | `session.py` (modified) | Existing tests pass |
| Planner Integration | `planner.py` (modified) | Existing tests pass |
| Suggestion Engine | `suggestion_engine.py` | `test_suggestion_engine.py` |

### 3.3 Phase 1 Success Criteria

- [ ] Weebot can detect and connect to CatchMe
- [ ] User activity context is available in session
- [ ] Planner uses context for better planning
- [ ] Contextual suggestions appear in UI
- [ ] All existing tests pass
- [ ] New code has ≥90% coverage
- [ ] No performance degradation when CatchMe unavailable

---

## 4. Phase 2: Retrieval Adapter & Browser Enhancement

**Duration:** Week 2-3  
**Goal:** Enable natural language queries over user's activity history + enhanced browser content extraction  
**Impact:** Users can ask "What was I working on yesterday?" and get accurate answers  

### 4.1 Tasks

#### Task 2.1: Implement Retrieval Adapter

**Files to Create:**
```
weebot/integrations/catchme/retrieval_adapter.py
weebot/integrations/catchme/tests/test_retrieval_adapter.py
```

**Details:**
```python
class CatchMeRetrievalAdapter:
    """Adapter for querying user's activity history via natural language."""
    
    def __init__(self, config: CatchMeConfig, detector: CatchMeDetector):
        self._config = config
        self._detector = detector
    
    def query(self, query: str) -> Iterator[RetrievalResult]:
        """Execute a natural language query against activity history.
        
        Yields RetrievalResult objects containing:
        - answer: str — synthesized answer
        - sources: list[str] — node IDs that contributed
        - confidence: float — answer confidence
        """
        if not self._detector.is_installed():
            yield RetrievalResult(
                answer="Activity history is not available.",
                sources=[],
                confidence=0.0
            )
            return
        
        # Delegate to CatchMe's retrieve() function
        from catchme.pipelines.retrieve import retrieve
        
        collected = []
        for step in retrieve(query):
            if step["type"] == "answer":
                yield RetrievalResult(
                    answer=step.get("content", ""),
                    sources=step.get("sources", []),
                    confidence=self._estimate_confidence(step, collected)
                )
            elif step["type"] == "error":
                yield RetrievalResult(
                    answer=f"Error retrieving history: {step.get('message', 'unknown')}",
                    sources=[],
                    confidence=0.0
                )
            else:
                collected.append(step)
    
    def find_recent_files(self, hours: int = 24, pattern: str | None = None) -> list[str]:
        """Find recently accessed files matching optional pattern."""
        
    def find_recent_urls(self, hours: int = 24, domain: str | None = None) -> list[str]:
        """Find recently visited URLs matching optional domain filter."""
        
    def get_activity_summary(self, date: str | None = None) -> str:
        """Get a summary of activity for a specific date (YYYY-MM-DD)."""
```

**Acceptance Criteria:**
- [ ] Queries return structured results
- [ ] Streaming results work correctly
- [ ] Error handling for missing CatchMe
- [ ] Time-based filtering works
- [ ] ≥90% test coverage

---

#### Task 2.2: Create Retrieval Tool for Agent

**Files to Create:**
```
weebot/integrations/catchme/tools/activity_query_tool.py
weebot/integrations/catchme/tools/__init__.py
```

**Details:**
```python
class ActivityQueryTool(Tool):
    """Tool that allows the agent to query user's activity history."""
    
    name = "query_activity_history"
    description = """Query the user's personal activity history.
    
    Use this when the user asks about:
    - What they were doing at a specific time
    - Files they recently worked on
    - Websites they visited
    - Their recent workflow or tasks
    
    Examples:
    - "What was I working on yesterday?"
    - "Find that API key I copied"
    - "Show me the error I got this morning"
    """
    
    parameters = {
        "query": "Natural language query about user's activity",
        "time_range": "Optional: today, yesterday, last_week, or specific date"
    }
    
    async def execute(self, query: str, time_range: str | None = None) -> str:
        # Enhance query with time range if provided
        full_query = query
        if time_range:
            full_query = f"{query} ({time_range})"
        
        results = list(self._retrieval_adapter.query(full_query))
        if results:
            return results[0].answer
        return "No activity history found for that query."
```

**Acceptance Criteria:**
- [ ] Tool is registered in weebot's tool registry
- [ ] Tool description is clear for the LLM
- [ ] Results are formatted for agent consumption
- [ ] Tool respects privacy settings

---

#### Task 2.3: Enhance Browser Content Extraction

**Files to Create:**
```
weebot/integrations/catchme/browser_enhancement.py
weebot/infrastructure/browser/enhanced_content_extractor.py
```

**Files to Modify:**
```
weebot/infrastructure/browser/playwright_adapter.py  # Add get_semantic_content()
```

**Details:**

CatchMe's Chrome extension uses Readability.js + DOM walk for content extraction. We can port this logic to enhance weebot's browser automation.

```python
class EnhancedContentExtractor:
    """Enhanced content extraction combining Playwright with Readability-like logic."""
    
    def __init__(self, page: Page):
        self._page = page
    
    async def extract_article(self) -> dict:
        """Extract article content using Readability-like algorithm.
        
        Returns:
            {
                "title": str,
                "content": str,  # Clean text content
                "excerpt": str,
                "byline": str,
                "site_name": str,
                "url": str,
                "word_count": int
            }
        """
        
    async def extract_semantic_structure(self) -> dict:
        """Extract semantic structure: headings, lists, code blocks, tables."""
        
    async def extract_with_readability_js(self) -> dict:
        """Inject Readability.js into page and extract."""
        # Load Readability.js from catchme/extension/lib/
        # Execute in page context
        # Return parsed article
```

**PlaywrightAdapter enhancement:**
```python
class PlaywrightAdapter(BrowserPort):
    # ... existing methods ...
    
    async def get_semantic_content(self) -> dict:
        """Get semantically extracted page content.
        
        Uses Readability.js when available, falls back to
        DOM-based extraction for SPAs and dashboards.
        """
        extractor = EnhancedContentExtractor(self._page)
        return await extractor.extract_article()
```

**Acceptance Criteria:**
- [ ] Article extraction works on news/blog pages
- [ ] DOM fallback works on SPAs (React, Vue, etc.)
- [ ] Semantic structure extraction preserves headings, lists, code
- [ ] Performance: extraction completes in <2s
- [ ] ≥90% test coverage

---

#### Task 2.4: Add Browser History Context

**Files to Create:**
```
weebot/integrations/catchme/browser_context.py
```

**Details:**
```python
class BrowserContextProvider:
    """Provides browser-related context from CatchMe for weebot sessions."""
    
    def get_page_content_summary(self, url: str) -> str | None:
        """Get cached content summary for a URL if user recently visited it."""
        
    def get_recent_research_context(self, topic: str) -> list[str]:
        """Find recent browsing related to a topic.
        
        Uses CatchMe's retrieval to find relevant pages the user
        has recently visited that relate to the current task.
        """
        
    def was_recently_viewed(self, url: str, hours: int = 24) -> bool:
        """Check if a URL was recently visited by the user."""
```

**Acceptance Criteria:**
- [ ] Returns cached content for recently visited URLs
- [ ] Topic-based research context works
- [ ] Respects time window
- [ ] Graceful when no data available

---

### 4.2 Phase 2 Deliverables

| Deliverable | File(s) | Tests |
|------------|---------|-------|
| Retrieval Adapter | `retrieval_adapter.py` | `test_retrieval_adapter.py` |
| Activity Query Tool | `tools/activity_query_tool.py` | Integration tests |
| Enhanced Content Extractor | `enhanced_content_extractor.py` | `test_enhanced_extractor.py` |
| Browser Context Provider | `browser_context.py` | `test_browser_context.py` |

### 4.3 Phase 2 Success Criteria

- [ ] Agent can query user's activity history
- [ ] Browser content extraction is enhanced
- [ ] Cached page content is available for recently visited URLs
- [ ] All existing tests pass
- [ ] New code has ≥90% coverage

---

## 5. Phase 3: Cost Optimization & Vision Pipeline

**Duration:** Week 3-4  
**Goal:** Harden production use with cost tracking and visual debugging  
**Impact:** Production-ready with cost visibility and better debugging  

### 5.1 Tasks

#### Task 3.1: Enhance Token Budget Monitor with CatchMe Patterns

**Files to Modify:**
```
weebot/application/services/token_budget_monitor.py
weebot/core/model_cascade_config.py
```

**Files to Create:**
```
weebot/integrations/catchme/cost_tracker.py
weebot/integrations/catchme/tests/test_cost_tracker.py
```

**Details:**

Adapt CatchMe's `_CallBudget` and `_TokenTracker` patterns for weebot's model cascade:

```python
class EnhancedTokenTracker:
    """Cross-process token usage tracker with persistence.
    
    Inspired by CatchMe's _TokenTracker but integrated with
    weebot's ModelCascadeConfig.
    """
    
    def __init__(self, storage_path: Path | None = None):
        self._storage_path = storage_path or Path.home() / ".weebot" / "token_usage.json"
        self._lock = threading.Lock()
        self._records: list[TokenRecord] = []
        self._load_from_disk()
    
    def record(self, model_id: str, prompt_tokens: int, completion_tokens: int, 
               cost_usd: float, task_type: str) -> None:
        """Record a token usage event."""
        
    def get_session_cost(self, session_id: str) -> CostBreakdown:
        """Get total cost for a session."""
        
    def get_daily_cost(self, date: date | None = None) -> CostBreakdown:
        """Get total cost for a day."""
        
    def get_cost_projection(self, window_days: int = 7) -> float:
        """Project monthly cost based on recent usage."""
        
    def persist(self) -> None:
        """Atomically save to disk."""
```

**ModelCascadeConfig enhancement:**
```python
@dataclass
class ModelConfig:
    # ... existing fields ...
    daily_budget_limit: float | None = None  # USD per day
    call_budget_limit: int = 0  # 0 = unlimited
```

**Acceptance Criteria:**
- [ ] Token usage is persisted across process restarts
- [ ] Daily cost tracking works
- [ ] Budget limits are enforced
- [ ] Cost projections are reasonable
- [ ] ≥90% test coverage

---

#### Task 3.2: Implement Vision Pipeline for Tool Debugging

**Files to Create:**
```
weebot/integrations/catchme/vision_pipeline.py
weebot/integrations/catchme/tests/test_vision_pipeline.py
```

**Files to Modify:**
```
weebot/core/tool_agent.py  # Add screenshot capture on tool execution
```

**Details:**

Port CatchMe's screenshot annotation for weebot's tool execution:

```python
class ToolExecutionVisualizer:
    """Capture and annotate screenshots for tool execution debugging."""
    
    def __init__(self, output_dir: Path | None = None):
        self._output_dir = output_dir or Path.home() / ".weebot" / "screenshots"
        self._output_dir.mkdir(parents=True, exist_ok=True)
    
    async def capture_before_after(self, tool_call: dict, 
                                    execute_fn: Callable) -> ToolExecutionResult:
        """Capture screenshots before and after tool execution.
        
        Returns enhanced result with screenshot paths.
        """
        
    def annotate_screenshot(self, image_path: Path, 
                           annotation: str,
                           coordinates: tuple[int, int] | None = None) -> Path:
        """Add annotation overlay to screenshot.
        
        Uses CatchMe's annotation logic:
        - Crosshair at click coordinates
        - Label with action description
        - Detail crop around interaction point
        """
        
    def create_execution_timeline(self, session_id: str) -> list[dict]:
        """Create a visual timeline of tool executions with screenshots."""
```

**ToolAgent integration:**
```python
class ToolAgent:
    async def execute_tool(self, tool_call: dict) -> dict:
        # ... existing logic ...
        
        # Capture screenshot if visualizer is enabled
        if self._visualizer and tool_call.get("tool") in ["browser_click", "browser_navigate"]:
            result = await self._visualizer.capture_before_after(
                tool_call, 
                lambda: self._execute(tool_call)
            )
            return result
        
        return await self._execute(tool_call)
```

**Acceptance Criteria:**
- [ ] Screenshots captured for browser tools
- [ ] Annotations show click locations
- [ ] Detail crops generated for small elements
- [ ] Screenshots stored securely in weebot's data dir
- [ ] Old screenshots cleaned up automatically (>30 days)
- [ ] ≥90% test coverage

---

#### Task 3.3: Add Cost Visibility to UI

**Files to Create:**
```
weebot-ui/src/components/CostMonitor.tsx
weebot-ui/src/hooks/useCostTracking.ts
```

**Details:**
- Real-time cost display in UI
- Daily budget progress bar
- Model usage breakdown pie chart
- Cost per session table
- Alert when approaching budget limit

**Acceptance Criteria:**
- [ ] Cost display updates in real-time
- [ ] Budget alerts trigger at 75%, 90%, 100%
- [ ] Historical cost data viewable
- [ ] Export cost data as CSV

---

### 5.2 Phase 3 Deliverables

| Deliverable | File(s) | Tests |
|------------|---------|-------|
| Enhanced Cost Tracker | `cost_tracker.py` | `test_cost_tracker.py` |
| Vision Pipeline | `vision_pipeline.py` | `test_vision_pipeline.py` |
| Cost UI Components | `CostMonitor.tsx`, `useCostTracking.ts` | E2E tests |

### 5.3 Phase 3 Success Criteria

- [ ] Token usage persisted across restarts
- [ ] Budget limits enforced
- [ ] Screenshots captured for browser actions
- [ ] Cost visible in UI with alerts
- [ ] All existing tests pass
- [ ] New code has ≥90% coverage

---

## 6. Phase 4: Hierarchical Planning & Polish

**Duration:** Week 4-6  
**Goal:** Evolve PlanActFlow to support hierarchical planning inspired by CatchMe's tree  
**Impact:** Better handling of complex, multi-step tasks  

### 6.1 Tasks

#### Task 4.1: Design Hierarchical Plan Model

**Files to Create:**
```
weebot/domain/models/hierarchical_plan.py
weebot/domain/models/tests/test_hierarchical_plan.py
```

**Details:**

Inspired by CatchMe's ActivityNode tree:

```python
class HierarchicalStep(BaseModel):
    """A step that can contain substeps."""
    id: str
    description: str
    status: StepStatus
    level: int  # 0 = leaf, 1 = group, 2 = phase, 3 = milestone
    substeps: list["HierarchicalStep"] = Field(default_factory=list)
    parent_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    
    def is_leaf(self) -> bool:
        return len(self.substeps) == 0
    
    def is_complete(self) -> bool:
        if self.is_leaf():
            return self.status in (StepStatus.COMPLETED, StepStatus.FAILED)
        return all(s.is_complete() for s in self.substeps)
    
    def get_active_path(self) -> list["HierarchicalStep"]:
        """Get the path from root to currently active leaf."""
        
    def flatten(self) -> list["HierarchicalStep"]:
        """Flatten tree to list in execution order."""


class HierarchicalPlan(BaseModel):
    """A plan with hierarchical decomposition."""
    title: str
    message: str
    root_steps: list[HierarchicalStep]
    status: PlanStatus
    
    def get_next_leaf(self) -> HierarchicalStep | None:
        """Get the next leaf step to execute."""
        
    def get_progress(self) -> tuple[int, int]:
        """Get (completed, total) leaf count."""
        
    def to_flat_plan(self) -> Plan:
        """Convert to flat Plan for backwards compatibility."""
```

**Acceptance Criteria:**
- [ ] Tree structure supports arbitrary depth
- [ ] Flattening preserves execution order
- [ ] Progress tracking works correctly
- [ ] Backwards compatible with flat Plan
- [ ] ≥90% test coverage

---

#### Task 4.2: Implement Hierarchical Planner

**Files to Create:**
```
weebot/application/agents/hierarchical_planner.py
weebot/application/agents/tests/test_hierarchical_planner.py
```

**Details:**
```python
class HierarchicalPlannerAgent:
    """Planner that creates hierarchical plans with multi-level decomposition."""
    
    async def plan(self, prompt: str, context: UserActivityContext | None = None) -> HierarchicalPlan:
        """Create a hierarchical plan from a user prompt.
        
        Planning strategy:
        1. LLM generates high-level phases (level 3)
        2. For each phase, LLM generates groups (level 2)
        3. For each group, LLM generates concrete steps (level 1/0)
        
        Each level is generated in a separate LLM call to manage context.
        """
        
    async def _generate_phases(self, prompt: str) -> list[dict]:
        """Generate top-level phases."""
        
    async def _generate_groups(self, phase: dict) -> list[dict]:
        """Generate groups within a phase."""
        
    async def _generate_steps(self, group: dict) -> list[dict]:
        """Generate concrete steps within a group."""
        
    def _convert_to_hierarchical(self, phases: list[dict]) -> HierarchicalPlan:
        """Convert LLM output to HierarchicalPlan model."""
```

**Acceptance Criteria:**
- [ ] Plans have meaningful hierarchy
- [ ] Each level is independently executable
- [ ] Context from CatchMe influences planning
- [ ] Plans are validated against schema
- [ ] ≥90% test coverage

---

#### Task 4.3: Integrate Hierarchical Plan into PlanActFlow

**Files to Modify:**
```
weebot/application/flows/plan_act_flow.py
weebot/application/flows/states/planning.py
weebot/application/flows/states/executing.py
```

**Details:**

Add hierarchical planning mode to PlanActFlow:

```python
class PlanActFlow(BaseFlow):
    def __init__(self, ..., 
                 use_hierarchical_planning: bool = False,
                 hierarchical_planner: HierarchicalPlannerAgent | None = None):
        # ... existing init ...
        self._use_hierarchical = use_hierarchical_planning
        self._hierarchical_planner = hierarchical_planner
    
    async def run(self, prompt: str) -> AsyncGenerator[AgentEvent, None]:
        # ... existing logic ...
        
        if self._use_hierarchical and self._hierarchical_planner:
            # Use hierarchical planning
            plan = await self._hierarchical_planner.plan(
                prompt, 
                context=self._session.user_context
            )
        else:
            # Use existing flat planning
            plan = await self._planner.plan(prompt)
```

**Acceptance Criteria:**
- [ ] Hierarchical mode toggleable via config
- [ ] Flat planning still works (backwards compatible)
- [ ] Hierarchical plans execute correctly
- [ ] State transitions handle hierarchy
- [ ] All existing tests pass

---

#### Task 4.4: Documentation & Examples

**Files to Create:**
```
docs/integrations/catchme/README.md
docs/integrations/catchme/SETUP.md
docs/integrations/catchme/API.md
docs/integrations/catchme/PRIVACY.md
examples/catchme_integration/basic_usage.py
examples/catchme_integration/contextual_greeting.py
examples/catchme_integration/activity_query.py
```

**Details:**
- Setup instructions for installing CatchMe alongside weebot
- API reference for all public classes
- Privacy guide explaining what data is accessed
- Example scripts demonstrating each feature

**Acceptance Criteria:**
- [ ] All docs are complete and accurate
- [ ] Examples run without errors
- [ ] Privacy guide addresses all concerns

---

#### Task 4.5: Final Integration Testing

**Files to Create:**
```
tests/integration/test_catchme_full_pipeline.py
tests/integration/test_catchme_privacy.py
tests/integration/test_catchme_performance.py
```

**Details:**
- End-to-end tests covering all integration points
- Privacy tests verifying no raw keystroke access
- Performance tests ensuring no degradation
- Load tests for retrieval adapter

**Acceptance Criteria:**
- [ ] All integration tests pass
- [ ] Privacy tests confirm data boundaries
- [ ] Performance within 10% of baseline
- [ ] Load tests handle 100 concurrent queries

---

### 6.2 Phase 4 Deliverables

| Deliverable | File(s) | Tests |
|------------|---------|-------|
| Hierarchical Plan Model | `hierarchical_plan.py` | `test_hierarchical_plan.py` |
| Hierarchical Planner | `hierarchical_planner.py` | `test_hierarchical_planner.py` |
| PlanActFlow Integration | `plan_act_flow.py` (modified) | Integration tests |
| Documentation | `docs/integrations/catchme/` | N/A |
| Examples | `examples/catchme_integration/` | N/A |
| Integration Tests | `tests/integration/test_catchme_*.py` | All pass |

### 6.3 Phase 4 Success Criteria

- [ ] Hierarchical planning works end-to-end
- [ ] All features documented
- [ ] Examples are runnable
- [ ] Integration tests pass
- [ ] Performance meets targets
- [ ] Ready for v2.8.0 release

---

## 7. Security & Privacy Considerations

### 7.1 Data Access Matrix

| Data Type | CatchMe Access | Weebot Access | Justification |
|-----------|---------------|---------------|---------------|
| Raw keystrokes | Full | **None** | Privacy boundary — weebot never sees raw input |
| Screenshots | Full | **None** | Privacy boundary — only LLM summaries cross |
| Window titles | Full | Summary only | Needed for context awareness |
| App names | Full | Summary only | Needed for context awareness |
| File paths | Full | Optional | Only with user consent (privacy_level) |
| URLs visited | Full | Optional | Only with user consent (privacy_level) |
| LLM summaries | Full | Full | These are safe — already processed by LLM |
| Clipboard | Full | **None** | Never accessed — too sensitive |

### 7.2 Security Measures

1. **BashGuard Integration:** Any CatchMe-derived content used in bash commands must pass through weebot's existing `BashGuard` validation pipeline.

2. **Prompt Injection Protection:** CatchMe summaries are user-controlled content. They must be treated as untrusted input and sanitized before inclusion in LLM prompts.

3. **Local-Only Operation:** CatchMe data never leaves the local machine. Weebot integration does not add any network endpoints for CatchMe data.

4. **Audit Logging:** All access to CatchMe data is logged with:
   - Timestamp
   - Query type
   - Data categories accessed
   - Session ID

5. **User Consent:** Integration is opt-in. User must explicitly enable CatchMe integration.

### 7.3 Privacy Levels

```python
class PrivacyLevel(str, Enum):
    MINIMAL = "minimal"      # App names only, no summaries
    SUMMARY = "summary"      # App names + LLM summaries (default)
    DETAILED = "detailed"    # Includes file paths, URLs
```

---

## 8. Testing Strategy

### 8.1 Test Pyramid

```
                    ┌─────────┐
                    │  E2E    │  5%  (full pipeline tests)
                    │  Tests  │
                   ┌┴─────────┴┐
                   │ Integration│  15% (adapter + service tests)
                   │   Tests    │
                  ┌┴────────────┴┐
                  │   Unit Tests   │  80% (individual classes/functions)
                  │   (≥90% cov)   │
                  └────────────────┘
```

### 8.2 Test Requirements by Phase

| Phase | Unit Tests | Integration Tests | E2E Tests | Coverage Target |
|-------|-----------|------------------|-----------|-----------------|
| 1 | 20+ | 5+ | 2+ | ≥90% |
| 2 | 15+ | 5+ | 2+ | ≥90% |
| 3 | 10+ | 3+ | 1+ | ≥90% |
| 4 | 15+ | 5+ | 2+ | ≥90% |

### 8.3 Mock Strategy

CatchMe is an external dependency. Tests must work without it installed:

```python
# Example: Mock CatchMe for tests
@pytest.fixture
def mock_catchme_tree():
    return {
        "tree": {
            "node_id": "d20240115",
            "kind": "day",
            "title": "2024-01-15",
            "children": [
                {
                    "node_id": "d20240115_s1000",
                    "kind": "session",
                    "title": "09:00 – 12:00",
                    "summary": "Working on payment integration",
                    "children": [
                        {
                            "node_id": "d20240115_s1000_vscode",
                            "kind": "app",
                            "title": "VS Code",
                            "summary": "Editing Python files",
                            "children": []
                        }
                    ]
                }
            ]
        },
        "mode": "time"
    }
```

---

## 9. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| CatchMe API changes | Medium | High | Adapter pattern isolates changes; version checking |
| Performance degradation | Low | Medium | Lazy loading; caching; benchmark tests |
| Privacy concerns | Medium | High | Clear privacy levels; audit logging; opt-in only |
| Test flakiness (CatchMe dependency) | Medium | Medium | Comprehensive mocking; CI without CatchMe |
| Scope creep | High | Medium | Strict phase gates; MVP first |
| Breaking existing tests | Low | High | Run full test suite after each phase |
| Platform-specific issues | Medium | Low | Cross-platform CI; platform abstraction |

---

## 10. Appendix: File Inventory

### New Files (by Phase)

#### Phase 1
```
weebot/integrations/__init__.py
weebot/integrations/catchme/__init__.py
weebot/integrations/catchme/config.py
weebot/integrations/catchme/exceptions.py
weebot/integrations/catchme/adapter_base.py
weebot/integrations/catchme/detector.py
weebot/integrations/catchme/context_bridge.py
weebot/integrations/catchme/models.py
weebot/integrations/catchme/suggestion_engine.py
weebot/integrations/catchme/tests/__init__.py
weebot/integrations/catchme/tests/test_detector.py
weebot/integrations/catchme/tests/test_context_bridge.py
weebot/integrations/catchme/tests/test_suggestion_engine.py
weebot/integrations/catchme/tests/test_config.py
```

#### Phase 2
```
weebot/integrations/catchme/retrieval_adapter.py
weebot/integrations/catchme/browser_enhancement.py
weebot/integrations/catchme/browser_context.py
weebot/integrations/catchme/tools/__init__.py
weebot/integrations/catchme/tools/activity_query_tool.py
weebot/integrations/catchme/tests/test_retrieval_adapter.py
weebot/integrations/catchme/tests/test_browser_context.py
weebot/infrastructure/browser/enhanced_content_extractor.py
weebot/infrastructure/browser/tests/test_enhanced_extractor.py
```

#### Phase 3
```
weebot/integrations/catchme/cost_tracker.py
weebot/integrations/catchme/vision_pipeline.py
weebot/integrations/catchme/tests/test_cost_tracker.py
weebot/integrations/catchme/tests/test_vision_pipeline.py
weebot-ui/src/components/CostMonitor.tsx
weebot-ui/src/hooks/useCostTracking.ts
```

#### Phase 4
```
weebot/domain/models/hierarchical_plan.py
weebot/domain/models/tests/test_hierarchical_plan.py
weebot/application/agents/hierarchical_planner.py
weebot/application/agents/tests/test_hierarchical_planner.py
docs/integrations/catchme/README.md
docs/integrations/catchme/SETUP.md
docs/integrations/catchme/API.md
docs/integrations/catchme/PRIVACY.md
examples/catchme_integration/basic_usage.py
examples/catchme_integration/contextual_greeting.py
examples/catchme_integration/activity_query.py
tests/integration/test_catchme_full_pipeline.py
tests/integration/test_catchme_privacy.py
tests/integration/test_catchme_performance.py
```

### Modified Files (by Phase)

#### Phase 1
```
weebot/domain/models/session.py
weebot/application/flows/plan_act_flow.py
weebot/application/agents/planner.py
```

#### Phase 2
```
weebot/infrastructure/browser/playwright_adapter.py
weebot/tools/base.py  # Register activity query tool
```

#### Phase 3
```
weebot/application/services/token_budget_monitor.py
weebot/core/model_cascade_config.py
weebot/core/tool_agent.py
```

#### Phase 4
```
weebot/application/flows/plan_act_flow.py
weebot/application/flows/states/planning.py
weebot/application/flows/states/executing.py
```

---

## Quick Reference: Task Checklist

### Phase 1
- [ ] Task 1.1: Create integration package structure
- [ ] Task 1.2: Build CatchMe availability detector
- [ ] Task 1.3: Implement Context Bridge
- [ ] Task 1.4: Integrate with Session initialization
- [ ] Task 1.5: Add contextual greeting suggestions
- [ ] Phase 1 review & sign-off

### Phase 2
- [ ] Task 2.1: Implement Retrieval Adapter
- [ ] Task 2.2: Create Activity Query Tool
- [ ] Task 2.3: Enhance Browser Content Extraction
- [ ] Task 2.4: Add Browser History Context
- [ ] Phase 2 review & sign-off

### Phase 3
- [ ] Task 3.1: Enhance Token Budget Monitor
- [ ] Task 3.2: Implement Vision Pipeline
- [ ] Task 3.3: Add Cost Visibility to UI
- [ ] Phase 3 review & sign-off

### Phase 4
- [ ] Task 4.1: Design Hierarchical Plan Model
- [ ] Task 4.2: Implement Hierarchical Planner
- [ ] Task 4.3: Integrate into PlanActFlow
- [ ] Task 4.4: Documentation & Examples
- [ ] Task 4.5: Final Integration Testing
- [ ] Phase 4 review & sign-off
- [ ] Release v2.8.0

---

*This plan was generated based on comprehensive analysis of both the Weebot (v2.7.0) and CatchMe (v0.1.0) codebases. All implementation details follow existing patterns in the respective projects.*
