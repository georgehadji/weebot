"""Compile session constraints into the mechanically enforceable subset.

Phase 5.2 of tasks/specs/side_constraint_integrity_plan.md. Prompt delivery
(Phase 4) raises compliance; compiling a constraint into a gate makes
compliance independent of whether the constraint survived compaction at all.

Two filters decide what compiles:

**Direction (plan D7).** Only ``TIGHTEN`` compiles. A ``LOOSEN`` constraint
widens the agent's latitude and must never reach a safety gate. The paper's
SC#1 is *"Don't ask me to confirm before running commands, just do them"* — a
gate that "enforced" it would pause to ask for confirmation, violating the
constraint it was enforcing. That inversion was live in ``ExecutingState``
before this module existed.

**Kind.** Only ``ACTION`` and ``INFORMATION``. A step-description check can
judge whether a step *does* a prohibited thing; it cannot judge whether the
final answer obeys a ``PROCESS``/``PREFERENCE``/``OUTPUT`` constraint, and
firing a blocking gate on a guess about the answer is strictly worse than
letting Phase 4's prompt delivery handle it.

A constraint that survives both filters still only bites if its canonical text
is negatively framed — ``check_step`` reads the prohibited phrase out of a
``do not|don't|never|must not|avoid`` stem. Positively-framed constraints
("always run the tests first") compile to a no-op here by design: they are
prompt-delivered, and a step-level gate cannot tell "hasn't happened yet" from
"won't happen".

Deliberately **not** a dict of Strategy-per-kind. The plan considered and
rejected a Specification/composite-predicate framework; a per-kind dispatch
dict is the same unrequested abstraction one size down. There is exactly one
consumer today (the ``ExecutingState`` step gate), and the only other
mechanical gate that exists — ``EgressGuard``'s outbound-mail branch — gates on
tool identity and needs no compiled rule. Add the dispatch when a second
consumer needs a second shape.
"""

from __future__ import annotations

from typing import Any

from weebot.domain.models.session_constraint import (
    ConstraintDirection,
    ConstraintKind,
    SessionConstraintRegistry,
)

from .constraint_extractor import Constraint

# Kinds a step-description check can actually adjudicate. See module docstring.
_ENFORCEABLE_KINDS = frozenset({ConstraintKind.ACTION, ConstraintKind.INFORMATION})

# check_step only inspects priority <= 2. Session constraints are user-issued
# prohibitions, which is exactly what "negative" means to ConstraintExtractor.
_COMPILED_TYPE = "negative"
_COMPILED_PRIORITY = 2


def compile_enforceable(registry: SessionConstraintRegistry | None) -> list[Constraint]:
    """Return the subset of *registry* that a step gate may enforce.

    Adapts ``SessionConstraint`` to the ``Constraint`` shape
    ``ConstraintExtractor.check_step`` already consumes, so the gate has one
    matching implementation rather than two that drift.

    Returns an empty list for ``None`` or an empty registry — the caller then
    falls back to its legacy source, and enforcement degrades to Phase 4
    prompt delivery rather than failing.
    """
    if registry is None:
        return []
    return [
        Constraint(text=c.text, constraint_type=_COMPILED_TYPE, priority=_COMPILED_PRIORITY)
        for c in registry.active(direction=ConstraintDirection.TIGHTEN)
        if c.kind in _ENFORCEABLE_KINDS
    ]


def compile_from_flow(flow: Any) -> list[Constraint]:
    """Compile the registry a ``PlanActFlow`` is already holding.

    ``PlanActFlow._session_constraints`` is hydrated and updated per user turn
    by ``SessionConstraintAccumulator``, so the gate reads it with no I/O and
    no second source of truth. Duck-typed rather than importing PlanActFlow —
    ``application.services`` must not depend on ``application.flows``.
    """
    return compile_enforceable(getattr(flow, "_session_constraints", None))
