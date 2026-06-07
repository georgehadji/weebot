"""Centralized constants for weebot.

Single source of truth for magic numbers, limits, and defaults.
Values inherited from :mod:`weebot.config.settings` where they exist.
"""
from __future__ import annotations

from weebot.config.settings import (
    BROWSER_TIMEOUT,
    HEADLESS,
    LOGS_DIR,
    LOG_FILE,
    MAX_RETRIES,
    REQUIRED_PATH_PREFIX,
    SESSIONS_DB,
    TEMPERATURE,
    WORKSPACE_ROOT,
)

# ========================================================================
# Token estimation
# ========================================================================
CHARS_PER_TOKEN: int = 4
"""Characters per token (rough estimate, used by tokenizer + monitor)."""

CODE_CHARS_PER_TOKEN: float = 3.5
"""Code characters per token (code is more token-efficient)."""

# ========================================================================
# Execution defaults
# ========================================================================
MAX_EXECUTOR_STEPS: int = 50
"""Max tool-call iterations per step in ExecutorAgent."""

MAX_PLANNER_STEPS: int = 15
"""Max tool-call iterations per step in StructuredExecutorAgent."""

MAX_TOKENS_DEFAULT: int = 16384
"""Default max_tokens for LLM calls (stays within OpenRouter credit limits)."""

# ========================================================================
# Persistence / DB
# ========================================================================
MAX_EVENTS_JSON_BYTES: int = 10 * 1024 * 1024  # 10 MB
"""Max serialized events JSON before oldest events are dropped."""

DB_SESSIONS_PATH: str = SESSIONS_DB
"""Default SQLite path for session storage (from WEEBOT_SESSIONS_DB)."""

DB_PROJECTS_PATH: str = "./projects.db"
"""Default SQLite path for project storage."""

# ========================================================================
# Agent context history
# ========================================================================
MAX_HISTORY_SIZE: int = 1000
"""Max pub/sub event history entries in EventBroker variants."""

MAX_HISTORY_PER_SESSION: int = 200
"""Max token history entries per session in TokenBudgetMonitor."""

# ========================================================================
# Session caps (memory leak prevention)
# ========================================================================
MAX_WORKING_MEMORY_SESSIONS: int = 1000
"""Max session keys in WorkingMemory before oldest is evicted."""

MAX_APPROVAL_SESSIONS: int = 50
"""Max session approval decisions cached before oldest is evicted."""

MAX_TOKEN_BUDGET_SESSIONS: int = 500
"""Max session entries in TokenBudgetMonitor before oldest is evicted."""

# ========================================================================
# Retries / timeouts
# ========================================================================
LLM_RETRY_DELAYS: list[float] = [1, 2, 4, 8, 15, 30]
"""Exponential backoff delays in seconds for LLM retries."""

TOOL_EXECUTION_TIMEOUT: float = 60.0
"""Default timeout in seconds for tool execution."""

BROWSER_PAGE_TIMEOUT: int = 30000
"""Page navigation timeout in ms (matches settings.BROWSER_TIMEOUT)."""

# ========================================================================
# Tool output limits
# ========================================================================
MAX_TOOL_OUTPUT_CHARS: int = 20_000
"""Max characters in a single tool result before truncation."""

SUBAGENT_MAX_STEPS: int = 15
"""Max tool-call iterations for sub-agents spawned by DispatchAgentsTool."""

# ========================================================================
# Flow execution limits
# ========================================================================
DEFAULT_MAX_STEP_REPETITIONS: int = 3
"""Default max times the same step can be re-attempted before forcing completion."""
DEFAULT_MAX_FLOW_ITERATIONS: int = 50
"""Default safety cap on state-machine iterations to prevent infinite loops."""
DEFAULT_MAX_CHAT_CONTEXT_MESSAGES: int = 50
"""Default max conversation turns before summarization."""

# ========================================================================
# SkillOpt defaults
# ========================================================================
DEFAULT_SKILLOPT_EPOCHS: int = 4
DEFAULT_SKILLOPT_STEPS_PER_EPOCH: int = 5
DEFAULT_SKILLOPT_BATCH_SIZE: int = 40
DEFAULT_SKILLOPT_MINIBATCH_SIZE: int = 8

# ========================================================================
# External service defaults
# ========================================================================
MCP_MAX_RETRIES: int = 3
MCP_RETRY_BASE_DELAY: float = 1.0
MCP_RETRY_MAX_DELAY: float = 10.0
EXTERNAL_SERVICE_TIMEOUT: int = 30
EXTERNAL_SERVICE_RETRIES: int = 3

# ========================================================================
# Verification (CoVe) — two-layer validation
# ========================================================================
VERIFICATION_SCORE_MIN: int = 3
"""Minimum score (1-5) on each verification axis before gate sweep."""

VERIFICATION_AXES: list[str] = ["correctness", "completeness", "specificity", "restraint"]
"""Axes scored during self-critique. Each axis must score ≥ VERIFICATION_SCORE_MIN."""

VERIFICATION_MAX_REVISION_PASSES: int = 2
"""Maximum revision passes during self-critique before accepting the output as-is."""

# ========================================================================
# Plan diversification
# ========================================================================
PLAN_DIVERSIFICATION_WINDOW: int = 3
"""Number of recent plans to check for structural similarity."""

PLAN_SIMILARITY_THRESHOLD: float = 0.7
"""Maximum allowed tool-sequence similarity (0-1) before diversification hint is triggered."""

# ========================================================================
# Temperature presets — semantic names for agent-specific tuning
# ========================================================================
TEMPERATURE_DETERMINISTIC: float = 0.0
"""Zero randomness — planning, compression, verification, skill curation."""

TEMPERATURE_PRECISE: float = 0.1
"""Very low randomness — code review, critique, trajectory building, CoVe."""

# TEMPERATURE (imported from settings) = 0.2 — general-purpose default
TEMPERATURE_BALANCED: float = 0.3
"""Moderate creativity — summarization, synthesis, debate, memory operations."""

TEMPERATURE_CREATIVE: float = 0.7
"""High diversity — chat agent, mixture-of-agents reference calls."""

TEMPERATURE_KIMI: float = 1.0
"""Kimi K2.6 requirement — forced by MoonshotAdapter. Not for general use."""

# ========================================================================
# max_tokens presets — semantic names for agent-specific output limits
# ========================================================================
MAX_TOKENS_TINY: int = 128
"""Short diagnostic output — layer diagnostics, skill curation."""

MAX_TOKENS_COMPACT: int = 256
"""Brief responses — meta self-improver."""

MAX_TOKENS_CONCISE: int = 300
"""Compact analysis — verifier scorer, evolution tracker."""

MAX_TOKENS_SHORT: int = 500
"""Compact output — optimizer reflection, CoVe, plan critic, trajectory builder."""

MAX_TOKENS_MODERATE: int = 1000
"""Moderate output — OpenRouter cascade, layer editor, meta critic."""

MAX_TOKENS_STANDARD: int = 2000
"""Standard agent response — optimizer proposals, CoVe synthesis."""

MAX_TOKENS_EXTENDED: int = 2048
"""Extended output — goal agent, debate, mixture-of-agents aggregator."""

MAX_TOKENS_DETAILED: int = 3000
"""Detailed output — optimizer ranking phase."""

MAX_TOKENS_CHAT: int = 4000
"""Conversational output — chat agent."""

MAX_TOKENS_PLANNING: int = 4096
"""Structured plan generation — planner agent."""

# MAX_TOKENS_DEFAULT (defined above) = 16384 — API default cap
