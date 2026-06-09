"""TypedDict schemas for HookRegistry context dicts.

Each stage has its own TypedDict so callsites are statically checkable
and hook authors know exactly what keys are guaranteed.

Architecture: Application layer (pure Python typing, no I/O, no framework).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class PreExecuteContext(TypedDict):
    session_id: str
    prompt: str
    plan: Optional[Any]  # None on first call


class PostExecuteContext(TypedDict):
    session_id: str
    plan: Optional[Any]
    status: str
    elapsed_ms: float
    total_tokens: int


class PreTaskContext(TypedDict):
    session_id: str
    step_id: str
    step_description: str
    step_index: int
    total_steps: int
    plan: Any


class PostTaskContext(TypedDict):
    session_id: str
    step_id: str
    step_description: str
    elapsed_ms: float
    plan: Any


class OnErrorContext(TypedDict):
    session_id: str
    step_id: str
    error: str
    error_type: str
    plan: Optional[Any]


class PreToolCallContext(TypedDict):
    session_id: str
    step_id: str
    tool_name: str
    tool_args: Dict[str, Any]


class PostToolCallContext(TypedDict):
    session_id: str
    step_id: str
    tool_name: str
    tool_args: Dict[str, Any]
    result: Any
    elapsed_ms: float
    success: bool


class PostPlanCreatedContext(TypedDict):
    session_id: str
    plan: Any
    step_count: int
    elapsed_ms: float


class PostPlanUpdatedContext(TypedDict):
    session_id: str
    plan: Any
    step_count: int
    elapsed_ms: float
    reason: str


class PostBashGuardContext(TypedDict):
    session_id: str
    command: str
    risk_level: str
    allowed: bool


class PostVerificationContext(TypedDict):
    session_id: str
    scores: Dict[str, int]
    gate_failures: List[str]
    inconsistency_count: int


class PostCompleteContext(TypedDict):
    session_id: str
    plan: Optional[Any]
    tool_count: int
    error_count: int
    total_elapsed_ms: float
    plan_fingerprint: str
