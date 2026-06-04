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

DB_SESSIONS_PATH: str = "./weebot_sessions.db"
"""Default SQLite path for session storage."""

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
