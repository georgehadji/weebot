"""Wire StateGraph into FlowRouter.resolve_initial_state().

Replaces the hard-coded if/elif state priority chain with a
declarative StateGraph call.
"""
from __future__ import annotations

from pathlib import Path

BASE = Path("weebot/application/flows/flow_router.py")


def main():
    content = Path(BASE).read_text(encoding="utf-8")

    # 1. Add StateGraph import
    content = content.replace(
        "from weebot.domain.models.session import Session, SessionStatus",
        "from weebot.application.flows.state_graph import build_default_state_graph\nfrom weebot.domain.models.session import Session, SessionStatus",
    )

    # 2. Add _state_class_map and _graph class attributes
    content = content.replace(
        "class FlowRouter:\n    \"\"\"Resolves the initial flow state based on session context and plan status.\"\"\"",
        """class FlowRouter:
    \"\"\"Resolves the initial flow state based on session context and plan status.\"\"\"

    # State name -> FlowState class mapping for StateGraph compatibility
    _state_class_map = {}
    _graph = None

    @classmethod
    def _get_graph(cls):
        \"\"\"Lazily build the state graph (singleton per class).\"\"\"
        if cls._graph is None:
            from weebot.application.flows.states.executing import ExecutingState
            from weebot.application.flows.states.planning import PlanningState
            from weebot.application.flows.states.product_gate import ProductGateState
            cls._state_class_map = {
                "ExecutingState": ExecutingState,
                "PlanningState": PlanningState,
                "ProductGateState": ProductGateState,
            }
            cls._graph = build_default_state_graph()
        return cls._graph""",
    )

    # 3. Replace resolve_initial_state body with graph call
    old_body = """        # Priority 0: Product gate clarification pending
        product_gate_pending = session.context.get("_product_gate_pending")
        if product_gate_pending:
            from weebot.application.flows.states.product_gate import ProductGateState

            # Clear the pending flag
            extra_out = {**(extra or {}), "_product_gate_pending": False}
            updated = session.model_copy(
                update={"context": session.context.model_copy(update={"extra": extra_out})}
            )
            logger.info("Resuming product gate with user clarification")
            return ProductGateState(resume_with=prompt), updated

        plan_pending_approval = session.context.get("plan_pending_approval")

        if plan_pending_approval:
            from weebot.application.flows.states.plan_review import _APPROVE_TOKENS

            response = prompt.strip().lower()

            # Clear the approval flag regardless of outcome
            extra_out = {**(extra or {}), "plan_pending_approval": False}
            updated = session.model_copy(
                update={"context": session.context.model_copy(update={"extra": extra_out})}
            )

            if response in _APPROVE_TOKENS or not response:
                logger.info("Plan approved by user — proceeding to execution")
                # Transition from WAITING -> RUNNING so the main loop
                # doesn't break prematurely (it breaks on WAITING).
                updated = updated.set_status(SessionStatus.RUNNING)
                return ExecutingState(), updated

            logger.info("User requested plan modification: %r", prompt[:80])
            # Set modification context so PlanningState re-runs
            extra_out["_intent_reviewed"] = False
            extra_out["_plan_modification_request"] = prompt
            updated = session.model_copy(
                update={"context": session.context.model_copy(update={"extra": extra_out})}
            )
            return PlanningState(), updated

        last_plan = session.get_last_plan()

        if last_plan is not None and not last_plan.is_complete():
            logger.info("Resuming session %s with existing plan", session.id)
            if session.status == SessionStatus.WAITING:
                session = session.set_status(SessionStatus.RUNNING)
            return ExecutingState(), session

        if session.status == SessionStatus.WAITING and last_plan is not None:
            logger.info("Session %s was waiting, resuming execution", session.id)
            session = session.set_status(SessionStatus.RUNNING)
            return ExecutingState(), session

        return PlanningState(), session"""

    new_body = """        graph = cls._get_graph()
        try:
            state_name, updated = graph.resolve(session, prompt, extra)

            # Map string state name back to FlowState class
            state_cls = cls._state_class_map.get(state_name)
            if state_cls is not None:
                if state_name == "ProductGateState":
                    state_instance = state_cls(resume_with=prompt)
                else:
                    state_instance = state_cls()
            else:
                logger.warning("Unknown state %r, falling back to PlanningState", state_name)
                from weebot.application.flows.states.planning import PlanningState
                state_instance = PlanningState()

            logger.info("Resolved state: %s for session %s", state_name, session.id)
            return state_instance, updated
        except ValueError as exc:
            logger.warning("StateGraph resolve failed: %s — falling back to PlanningState", exc)
            from weebot.application.flows.states.planning import PlanningState
            return PlanningState(), session"""

    content = content.replace(old_body, new_body)

    Path(BASE).write_text(content, encoding="utf-8", newline="")
    print("StateGraph wired into FlowRouter.resolve_initial_state()")


if __name__ == "__main__":
    main()
