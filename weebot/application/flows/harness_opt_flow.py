"""HarnessOptFlow — optimization epoch loop for HarnessConfig (Self-Harness).

Rollout → Mine → Propose → Apply → Validate → Accept/Reject.

Simplified version of SkillOptFlow that targets the behavioral instruction
surfaces of HarnessConfig rather than skill content.  Uses inline LLM
proposal generation (no OptimizerPort dependency) and delegates regression
validation to the RegressionGate (Phase 4).
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import TYPE_CHECKING, Any
from collections.abc import AsyncGenerator, Callable

from weebot.config.constants import MAX_TOKENS_SHORT, TEMPERATURE_BALANCED
from weebot.domain.models.session import Session

from weebot.application.flows.base_flow import BaseFlow
from weebot.application.services.harness_optimization_target import HarnessOptimizationTarget
from weebot.application.services.regression_gate import RegressionGate
from weebot.application.services.harness_safety_gate import HarnessSafetyGate
from weebot.domain.models.event import AgentEvent, DoneEvent, MessageEvent, WaitForUserEvent
from weebot.domain.models.failure_signature import EvidenceBundle
from weebot.domain.models.harness_edit import HarnessEdit

if TYPE_CHECKING:
    from weebot.application.ports.llm_port import LLMPort
    from weebot.application.ports.trajectory_repository_port import TrajectoryRepositoryPort

logger = logging.getLogger(__name__)

_HARNESS_PROPOSAL_PROMPT = """You are improving an agent harness.  The harness controls how an LLM-based
agent is instructed to execute tasks.  Below is the current harness state
and the most common failure patterns observed during evaluation.

Current harness:
{harness_content}

Failure patterns (ordered by frequency × actionability):
{failure_patterns}

Your job is to propose exactly ONE targeted edit to the harness that would
reduce one of the failure patterns.  Requirements:

1. **Minimality**: Change only ONE surface (one instruction, one setting).
2. **Specificity**: Tie the edit to a specific failure mechanism.
3. **Diversity**: If you've already proposed an edit for one mechanism,
   choose a DIFFERENT mechanism for the next proposal.

Editable surfaces (choose ONE per proposal):

**Instruction surfaces** (text changes only, auto-approvable):
- ``instructions.bootstrap`` — guidance for the very first action on a task
- ``instructions.execution`` — guidance for how to approach execution
- ``instructions.verification`` — guidance for verifying outcomes
- ``instructions.failure_recovery`` — guidance for recovering from failures
- ``instructions.system_prompt_extension`` — arbitrary text appended to system prompt

**Middleware rules** (structural additions, require human review):
- ``middleware.add:{{name}}`` — add a middleware rule with trigger + action
  Example: a tool-error handler that redirects after 3 consecutive errors,
          a loop-breaker that forces summarisation after N identical calls,
          an artifact-ensurer that verifies required files before concluding.
  ``value`` should be a JSON object: {{"name": "...", "trigger": "...", "action": "..."}}

**Subagent definitions** (structural additions, require human review):
- ``subagents.add:{{name}}`` — add a subagent definition
  Example: an artifact-ensurer subagent, a dependency-verifier subagent.
  ``value`` should be a JSON object: {{"name": "...", "role": "...", "prompt": "..."}}

**Tool policies** (setting changes, require human review):
- ``tool_policies.max_retries`` — max retries for failed tool calls
- ``tool_policies.retry_delay_seconds`` — backoff delay between retries

Respond with a JSON object:
{{
  "target": "instructions.bootstrap",
  "value": "new instruction text",
  "mechanism": "failure mechanism this addresses",
  "expected_effect": "what should improve",
  "risks": ["potential regression 1", "potential regression 2"]
}}
"""


class HarnessOptFlow(BaseFlow):
    """Optimization loop for agent harness configuration.

    Follows the same rollout→mine→propose→validate→accept pattern as
    SkillOptFlow but targets HarnessConfig behavioural surfaces.
    """

    def __init__(
        self,
        llm: LLMPort,
        target: HarnessOptimizationTarget,
        trajectory_repo: TrajectoryRepositoryPort,
        held_in_tasks: list[str] | None = None,
        held_out_tasks: list[str] | None = None,
        max_proposals: int = 3,
        gate: RegressionGate | None = None,
        tools: Any | None = None,
        code_quality_signal: Any | None = None,
    ):
        self._llm = llm
        self._tools = tools
        self._target = target
        self._trajectory_repo = trajectory_repo
        self._held_in_tasks = held_in_tasks or []
        self._held_out_tasks = held_out_tasks or []
        self._max_proposals = max_proposals
        self._code_quality_signal = code_quality_signal
        self._done = False
        # Edits the regression gate accepted and the safety gate held back.
        # Exposed so a caller can report or act on them deliberately.
        self._held_for_approval: list[HarnessEdit] = []

        # Injected gate; defaults to stub (always-accept) when no gate
        # or task_runner is provided.  The task_runner callable is what
        # lets the gate evaluate tasks under a specific HarnessConfig.
        # Phase 4+ wiring: pass a task_runner that creates PlanActFlows
        # with the candidate harness config injected.
        self._gate = gate or RegressionGate(
            task_runner=self._make_task_runner(), code_quality_signal=code_quality_signal
        )

    def is_done(self) -> bool:
        return self._done

    async def run(self, prompt: str = "") -> AsyncGenerator[AgentEvent, None]:
        """Execute one Self-Harness optimization iteration.

        Yields:
            AgentEvents including DoneEvent when complete.
        """
        yield MessageEvent(message="Starting Self-Harness optimization iteration")

        # 1. Load current harness
        try:
            harness = await self._target.load()
        except FileNotFoundError as exc:
            yield MessageEvent(message=f"ERROR: {exc}")
            self._done = True
            yield DoneEvent()
            return

        yield MessageEvent(message=f"Loaded harness {harness.version}: {harness.description}")

        # 2. Mine: query failure clusters from repository
        # NOTE: held-in evaluation (running tasks against the current harness)
        # is deferred to Phase 4 when RegressionGate consumes the results.
        # Mining uses already-stored failure signatures from past runs.
        yield MessageEvent(message="Mining failure patterns...")
        bundle = await self._mine_failure_patterns()

        if not bundle.clusters:
            logger.info("No failure clusters found — nothing to improve")
            yield MessageEvent(message="No failure clusters found — harness is stable")
            self._done = True
            yield DoneEvent()
            return

        yield MessageEvent(
            message=f"Found {len(bundle.clusters)} failure clusters "
            f"(total failures: {bundle.total_failures})"
        )

        # 4. Propose: generate candidate edits from failure evidence
        yield MessageEvent(message=f"Proposing up to {self._max_proposals} harness edits...")
        proposals = await self._propose_edits(harness_content=self._target.content, bundle=bundle)

        if not proposals:
            logger.info("No edits proposed")
            yield MessageEvent(message="No edits proposed — stopping")
            self._done = True
            yield DoneEvent()
            return

        yield MessageEvent(message=f"Generated {len(proposals)} candidate proposals")

        # 5. Apply each proposal and validate via regression gate
        for i, edit in enumerate(proposals):
            yield MessageEvent(message=f"Proposal {i+1}/{len(proposals)}: {edit.target_surface}")

            # Apply edit to produce a candidate harness
            candidate = await self._target.apply_edits([edit.to_edit_dict()])

            # Validate via regression gate
            decision = await self._gate.validate(
                baseline=harness,
                candidate=candidate,
                held_in_tasks=self._held_in_tasks,
                held_out_tasks=self._held_out_tasks,
            )

            if decision.accepted:
                # ── Safety gate: gated surfaces are NOT auto-promoted ──
                #
                # This used to be a notification. The flow yielded
                # WaitForUserEvent and then called `save(candidate)` on the
                # very next statement, unconditionally, with the comment
                # "Callers that want to block must stop iterating after
                # receiving WaitForUserEvent."
                #
                # Zero callers did. `cli/commands/harness.py` iterates with
                # `if hasattr(event, "message")`, and WaitForUserEvent carries
                # `question`, not `message` — so the approval prompt was not
                # even DISPLAYED, and the edit to a safety-critical surface
                # (runtime_control, subagents, or any unrecognised surface,
                # which `check` gates as fail-safe) was persisted regardless.
                #
                # A gate whose enforcement is delegated to every caller is not
                # a gate. This flow has no session or state repository, so
                # there is no durable pause to resume from; the honest
                # behaviour is to report the proposal and decline to apply it.
                safety_result = HarnessSafetyGate.check([edit])
                if safety_result.requires_approval:
                    yield WaitForUserEvent(question=safety_result.approval_prompt)
                    yield MessageEvent(
                        message=(
                            f"⏸ Held for approval: {edit.target_surface} — accepted by the "
                            f"regression gate but NOT applied, because it touches a "
                            f"safety-critical surface. Apply it deliberately if you want it."
                        )
                    )
                    self._held_for_approval.append(edit)
                    continue

                saved = await self._target.save(candidate)
                yield MessageEvent(
                    message=f"✓ Accepted: {edit.target_surface} → "
                    f"harness v{saved.version} "
                    f"(Δ_in={decision.delta_in:+.2f}, Δ_ho={decision.delta_ho:+.2f})"
                )
            else:
                yield MessageEvent(message=f"✗ Rejected: {edit.target_surface} — {decision.reason}")

        self._done = True
        yield DoneEvent()

    # ── Internal stages ───────────────────────────────────────────────

    def held_for_approval(self) -> list[HarnessEdit]:
        """Edits the regression gate accepted and the safety gate held back.

        Empty on a run where nothing touched a gated surface. A caller that
        wants these applied must do so deliberately — this flow will not.
        """
        return list(self._held_for_approval)

    def _make_task_runner(self) -> Callable:
        """Return a callable for the RegressionGate's task_runner protocol.

        The returned function has signature::

            (task_ids: list[str], config: HarnessConfig) -> list[dict]

        Each task_id is used as a prompt for a PlanActFlow run.
        The candidate ``config`` is injected into the flow via
        ``PlanActFlowConfig.harness_config`` so that the RegressionGate
        can compare different harness versions.

        Dependencies (llm, tools) are taken from ``self`` — injected at
        HarnessOptFlow construction time rather than introspected from a
        throwaway flow.
        """
        from weebot.application.flows.plan_act_flow import PlanActFlow
        from weebot.application.models.plan_act_flow_config import PlanActFlowConfig
        from weebot.application.services.harness_metric_scorer import HarnessMetricScorer
        from weebot.config.harness.schema import HarnessConfig

        async def _run(task_ids: list[str], config: HarnessConfig) -> list[dict]:
            results = []
            for task_id in task_ids:
                session = Session(
                    id=f"gate-eval-{uuid.uuid4().hex[:8]}",
                    user_id="regression-gate",
                    agent_id="gate-eval",
                    context={"harness_version": config.version},
                )
                flow_cfg = PlanActFlowConfig(
                    llm=self._llm, tools=self._tools, session=session, harness_config=config
                )
                flow = PlanActFlow(flow_cfg)
                try:
                    async for _ in flow.run(task_id):
                        pass
                    task_passed = True
                    task_error = None
                except Exception as exc:
                    logger.warning(
                        "Gate eval %s (harness %s) failed: %s", task_id, config.version, exc
                    )
                    task_passed = False
                    task_error = str(exc)

                # Score with HarnessMetricScorer
                metrics = HarnessMetricScorer.score(session=session, task_passed=task_passed)

                result: dict = {
                    "passed": task_passed,
                    "task_id": task_id,
                    "metrics": metrics.model_dump(),
                }
                if task_error:
                    result["error"] = task_error
                results.append(result)
            return results

        return _run

    async def _mine_failure_patterns(
        self, min_support: int = 3, lookback_days: int = 7, max_clusters: int = 5
    ) -> EvidenceBundle:
        """Query the trajectory repository for failure clusters."""
        clusters = await self._trajectory_repo.get_clusters(
            min_support=min_support, lookback_days=lookback_days, max_clusters=max_clusters
        )
        total_failures = sum(c.support for c in clusters)
        total_trajectories = await self._trajectory_repo.count_trajectories(
            lookback_days=lookback_days
        )
        return EvidenceBundle(
            harness_version=self._target.name,
            clusters=clusters,
            total_failures=total_failures,
            total_trajectories=total_trajectories,
        )

    async def _propose_edits(
        self, harness_content: str, bundle: EvidenceBundle
    ) -> list[HarnessEdit]:
        """Call the LLM to propose harness edits from failure evidence.

        Uses a simple budget-model call with structured JSON output.
        """
        # Format failure patterns for the prompt
        pattern_lines = []
        for i, cluster in enumerate(bundle.top_clusters(5)):
            sig = cluster.signature
            pattern_lines.append(
                f"{i+1}. [{cluster.support}x] "
                f"cause={sig.terminal_cause}, "
                f"behavior={sig.agent_behavior}, "
                f"mechanism={sig.mechanism} "
                f"(actionability={cluster.mean_actionability:.2f})"
            )

        if not pattern_lines:
            return []

        prompt = _HARNESS_PROPOSAL_PROMPT.format(
            harness_content=harness_content, failure_patterns="\n".join(pattern_lines)
        )

        edits = []
        for _ in range(self._max_proposals):
            try:
                response = await self._llm.chat(
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                    temperature=TEMPERATURE_BALANCED + (len(edits) * 0.1),  # ramp for diversity
                    max_tokens=MAX_TOKENS_SHORT,
                )

                if not response or not response.content:
                    continue

                raw = response.content
                # Strip markdown fences if present
                fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
                if fence_match:
                    raw = fence_match.group(1)

                parsed = json.loads(raw)

                edit = HarnessEdit(
                    target_surface=parsed.get("target", ""),
                    new_value=str(parsed.get("value", "")),
                    targeted_mechanism=parsed.get("mechanism", ""),
                    expected_effect=parsed.get("expected_effect", ""),
                    regression_risks=parsed.get("risks", []),
                )

                if edit.target_surface and edit.new_value:
                    # Avoid duplicate surface edits
                    if not any(e.target_surface == edit.target_surface for e in edits):
                        edits.append(edit)

            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                logger.warning("Proposal generation failed: %s", exc)
                continue

        return edits
