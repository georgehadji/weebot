"""Who a log line belongs to: session, step and correlation id, bound once.

OBS-1 of ``tasks/specs/arch_audit_2026_10_remediation_plan.md``. ``correlation_id``
existed in four files and was bound by almost nothing, so a log line from a tool, the
cascade or an adapter could not be tied to the session that caused it. The ids live
in ContextVars, set where a unit of work starts (``TaskRunner._run_flow``,
``PlanActFlow.run``, each executor step) and stamped onto every ``logging`` record by a
record factory, so no call site changes and every handler can print them.

Pure stdlib, no I/O. ``log_context()`` installs the record factory the first time it
is used, which keeps importing this module free of process-wide side effects.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar

correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)
session_id_var: ContextVar[str | None] = ContextVar("session_id", default=None)
step_id_var: ContextVar[str | None] = ContextVar("step_id", default=None)

_FIELDS = (
    ("session_id", session_id_var),
    ("step_id", step_id_var),
    ("correlation_id", correlation_id_var),
)


def current() -> dict[str, str]:
    """The ids bound in this context (only those that are set)."""
    return {name: value for name, var in _FIELDS if (value := var.get())}


def install_record_factory() -> None:
    """Stamp ``session_id`` / ``step_id`` / ``correlation_id`` on every LogRecord (idempotent)."""
    previous = logging.getLogRecordFactory()
    if getattr(previous, "_weebot_log_context", False):
        return

    def factory(*args, **kwargs):  # noqa: ANN002, ANN003
        record = previous(*args, **kwargs)
        for name, var in _FIELDS:
            if not hasattr(record, name):
                setattr(record, name, var.get() or "")
        return record

    factory._weebot_log_context = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(factory)


@contextmanager
def log_context(
    *,
    session_id: str | None = None,
    step_id: str | None = None,
    correlation_id: str | None = None,
    new_correlation: bool = False,
) -> Generator[None, None, None]:
    """Bind ids for the duration of a unit of work.

    A correlation id that is already bound is kept (a flow started by the runner shares
    the runner's id) unless ``new_correlation`` asks for a fresh one.
    """
    install_record_factory()
    tokens = []
    # ``bind_step`` sets without a token, so a step bound inside this context would
    # outlive it. Put back what was there when we leave.
    entry_step, entry_session = step_id_var.get(), session_id_var.get()
    if session_id is not None:
        tokens.append((session_id_var, session_id_var.set(session_id)))
    if step_id is not None:
        tokens.append((step_id_var, step_id_var.set(step_id)))
    wanted = correlation_id
    if wanted is None and (new_correlation or correlation_id_var.get() is None):
        wanted = uuid.uuid4().hex[:12]
    if wanted is not None:
        tokens.append((correlation_id_var, correlation_id_var.set(wanted)))
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            try:
                var.reset(token)
            except ValueError:
                # Reset from a different context (an async generator finalised
                # elsewhere): the value it set belongs to a context that is gone.
                logging.getLogger(__name__).debug("log context reset in another context")
        step_id_var.set(entry_step)
        session_id_var.set(entry_session)


def bind_step(step_id: str, session_id: str) -> None:
    """Re-bind the step (and session) for the rest of this task's work.

    Used where a context manager cannot wrap the work -- the executor's step is an
    async generator whose caller owns the surrounding task. Plain ``set``: no token
    is kept, so a finaliser running in another context cannot trip on a reset.
    """
    install_record_factory()
    if session_id:
        session_id_var.set(session_id)
    step_id_var.set(step_id)
