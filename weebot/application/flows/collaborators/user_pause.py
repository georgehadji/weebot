"""UserPause — the one place that knows what a durable pause requires.

A pause is only real if it survives the process. The CLI breaks its
``async for`` on the ``WaitForUserEvent`` and calls ``resume_session()``,
which loads from the repository — so the WAITING status, the gate's flags and
the question itself must all be in the database *before* the caller yields.

When they were not, three things followed, all measured:

  * ``resume_session`` raised ``ValueError: Session ... is not waiting``, so
    the CLI crashed on the user's answer;
  * the gate's own flags never persisted, so the gate re-fired on every
    resume without bound — each turn builds a fresh flow, so
    ``max_iterations`` cannot stop it;
  * ``_user_gate_pending`` never reached ``FlowRouter``, leaving the branch
    that reads the user's answer unreachable and ADR 006's "untrusted mail is
    not acted on without review" untrue in production.

Both halves of the contract live here so a future gate cannot implement one
and forget the other, which is exactly how the defect arose: two gates copied
a pause that set WAITING and yielded, from a state that also persisted.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def pause_flow_for_user(flow: Any, question: str) -> Any:
    """Set WAITING, record the question, and persist. Returns the event.

    Callers must mutate ``flow._session`` with whatever has to survive
    *before* calling this, then ``yield`` the event returned.

    The event is added exactly once. ``EventPublisher.emit`` calls
    ``add_event`` itself, so adding it here *and* emitting it — as
    ``PlanReviewState`` does — writes the same pause into the transcript
    twice.
    """
    from weebot.domain.models.event import WaitForUserEvent
    from weebot.domain.models.session import SessionStatus

    flow._session = flow._session.set_status(SessionStatus.WAITING)
    event = WaitForUserEvent(question=question)

    # Emit first: adds the event, publishes it to the bus for SSE and
    # WebSocket subscribers, and persists on a best-effort basis.
    try:
        await flow._emit(event)
    except Exception:
        logger.debug(
            "Emitting the pause through the pipeline failed; recording it directly.",
            exc_info=True,
        )
        flow._session = flow._session.add_event(event)

    # ...then persist authoritatively. `_persist_session` downgrades a failed
    # write to a warning, which is precisely the failure this exists to
    # prevent: the caller would yield, the CLI would resume, and the session
    # would not be WAITING. Let that surface here rather than as
    # "is not waiting" one turn later.
    repo = getattr(flow, "_state_repo", None)
    if repo is not None:
        await repo.save_session(flow._session)
    else:
        logger.warning(
            "Session %s is pausing with no state repository configured — the "
            "pause is in memory only and will not survive a resume.",
            flow._session.id,
        )
    return event


async def pause_for_user(context: Any, question: str) -> Any:
    """Pause durably via the flow, or in memory if the context cannot.

    A context without ``_pause_for_user`` (a test double, or a flow type that
    does not implement the contract) still has to pause, so this falls back to
    the in-memory half and says plainly that the durable half did not happen.
    Silence here is what let two gates ship a pause that never reached the
    database.
    """
    from weebot.domain.models.event import WaitForUserEvent
    from weebot.domain.models.session import SessionStatus

    pause = getattr(context, "_pause_for_user", None)
    if pause is not None:
        return await pause(question)

    logger.warning(
        "Flow %s has no _pause_for_user; pausing in memory only. The session "
        "will not be WAITING in the repository, so a resume that reloads from "
        "there will not see this pause.",
        type(context).__name__,
    )
    context._session = context._session.set_status(SessionStatus.WAITING)
    return WaitForUserEvent(question=question)
