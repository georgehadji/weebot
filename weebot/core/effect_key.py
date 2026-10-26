"""The identity of one outbound action: what makes a re-run the SAME send.

Pure: the same arguments give the same key in every process, so a ledger written
before a crash is still readable after it (ORCH-2 of
``tasks/specs/arch_audit_2026_10_remediation_plan.md``).

The key covers who (session), where in the work (step id and a digest of the
step's description) and what (tool and canonical arguments). The description
digest is there because the planner numbers steps ``step-1``, ``step-2`` ...
afresh on every plan, so a step id alone cannot tell a re-planned step from a
retried one; a step whose description changed is a new intent and gets a new key.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


def step_scope(step_description: str) -> str:
    """A short digest of a step's description (empty for no description)."""
    if not step_description:
        return ""
    return hashlib.sha256(step_description.strip().encode("utf-8")).hexdigest()[:16]


def effect_key(
    session_id: str,
    step_id: str,
    scope: str,
    tool_name: str,
    args: Mapping[str, Any],
) -> str:
    """SHA-256 over a stable serialisation of the action. 64 hex characters."""
    payload = json.dumps(
        [session_id, step_id, scope, tool_name, dict(args)],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
