"""Unit tests for SessionConstraint / SessionConstraintRegistry.

Phase 1 of tasks/specs/side_constraint_integrity_plan.md — pure domain
logic, no I/O.
"""

from __future__ import annotations

from weebot.domain.models.session_constraint import (
    ConstraintDirection,
    ConstraintKind,
    SessionConstraint,
    SessionConstraintRegistry,
)


def _c(text: str, *, direction=ConstraintDirection.TIGHTEN, turn_index=0) -> SessionConstraint:
    return SessionConstraint(
        text=text,
        evidence_span=text,
        kind=ConstraintKind.ACTION,
        direction=direction,
        turn_index=turn_index,
    )


class TestRegistryAdd:
    def test_add_returns_new_registry_not_mutated(self):
        reg = SessionConstraintRegistry()
        c = _c("don't delete files")
        reg2 = reg.add(c)
        assert reg.constraints == []
        assert reg2.constraints == [c]

    def test_active_includes_freshly_added(self):
        reg = SessionConstraintRegistry().add(_c("a")).add(_c("b"))
        assert [c.text for c in reg.active()] == ["a", "b"]


class TestRevocation:
    def test_revoke_marks_matching_constraint_inactive(self):
        reg = SessionConstraintRegistry().add(_c("don't delete files"))
        reg2 = reg.revoke("don't delete files")
        assert reg2.active() == []
        assert reg2.constraints[0].revoked_at is not None

    def test_revoke_does_not_mutate_original_registry(self):
        reg = SessionConstraintRegistry().add(_c("x"))
        reg.revoke("x")
        assert reg.active() != []  # original untouched

    def test_revoke_only_affects_matching_text(self):
        reg = SessionConstraintRegistry().add(_c("a")).add(_c("b"))
        reg2 = reg.revoke("a")
        assert [c.text for c in reg2.active()] == ["b"]

    def test_revoking_already_revoked_is_a_noop(self):
        reg = SessionConstraintRegistry().add(_c("a"))
        reg2 = reg.revoke("a")
        first_revoked_at = reg2.constraints[0].revoked_at
        reg3 = reg2.revoke("a")
        assert reg3.constraints[0].revoked_at == first_revoked_at


class TestSupersede:
    def test_supersede_marks_old_and_appends_new(self):
        reg = SessionConstraintRegistry().add(_c("use imperial units"))
        new = _c("use metric units")
        reg2 = reg.supersede("use imperial units", new)
        assert [c.text for c in reg2.active()] == ["use metric units"]
        old = next(c for c in reg2.constraints if c.text == "use imperial units")
        assert old.superseded_by == "use metric units"


class TestDirectionFiltering:
    def test_active_filters_by_direction(self):
        reg = (
            SessionConstraintRegistry()
            .add(_c("tight", direction=ConstraintDirection.TIGHTEN))
            .add(_c("loose", direction=ConstraintDirection.LOOSEN))
        )
        assert [c.text for c in reg.active(direction=ConstraintDirection.TIGHTEN)] == ["tight"]
        assert [c.text for c in reg.active(direction=ConstraintDirection.LOOSEN)] == ["loose"]


class TestRender:
    def test_empty_registry_renders_empty_string(self):
        assert SessionConstraintRegistry().render() == ""

    def test_render_includes_tighten_and_loosen_sections(self):
        reg = (
            SessionConstraintRegistry()
            .add(_c("never delete files", direction=ConstraintDirection.TIGHTEN))
            .add(_c("skip confirmations", direction=ConstraintDirection.LOOSEN))
        )
        rendered = reg.render()
        assert "never delete files" in rendered
        assert "skip confirmations" in rendered
        assert "WIDEN your latitude" in rendered
        assert "never override a safety gate" in rendered

    def test_render_excludes_revoked(self):
        reg = SessionConstraintRegistry().add(_c("gone")).revoke("gone")
        assert "gone" not in reg.render()

    def test_render_excludes_superseded(self):
        reg = SessionConstraintRegistry().add(_c("old"))
        reg = reg.supersede("old", _c("new"))
        rendered = reg.render()
        assert "old" not in rendered
        assert "new" in rendered
