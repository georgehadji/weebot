"""Planner agent — creates and updates structured JSON plans."""
from __future__ import annotations

import json
import logging
import re
from typing import Any, AsyncGenerator, Dict, List, Optional

from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.ports.llm_port import LLMPort
from weebot.config.constants import TEMPERATURE_DETERMINISTIC, MAX_TOKENS_PLANNING
from weebot.domain.models.event import (
    AgentEvent,
    ErrorEvent,
    MessageEvent,
    PlanEvent,
    PlanStatus,
    TitleEvent,
)
from weebot.domain.models.plan import Plan, Step

logger = logging.getLogger(__name__)

# Prompts loaded from files in config/prompts/ with inline fallbacks.
from pathlib import Path
_PLANNER_PROMPT_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "prompts" / "planner_system.txt"
_PLANNER_UPDATE_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "prompts" / "planner_update.txt"

def _load_planner_prompt(path: Path, fallback: str) -> str:
    """Load a planner prompt with multiple fallback strategies.

    Priority: (1) importlib.resources (packaged), (2) filesystem path
    (source checkout), (3) inline fallback constant.
    """
    # 1. Try importlib.resources (works when weebot is installed as a package)
    try:
        from importlib.resources import files as _resource_files
        filename = path.name
        return _resource_files("weebot.config.prompts").joinpath(filename).read_text(encoding="utf-8")
    except Exception:
        pass

    # 2. Try filesystem path (works in development / source checkout)
    try:
        if path.exists():
            return path.read_text(encoding="utf-8")
    except Exception:
        pass

    # 3. Inline fallback
    return fallback

# Injected into PLANNER_SYSTEM_PROMPT when skill_prompt references web/UI work.
SPEC_FILE_RULE = """
SPEC FILE RULE:
When a task involves inspecting or building multiple distinct UI sections (more than 2 sections),
add an explicit spec-writing step for each section BEFORE its build step:
  {"id": "spec-N", "description": "Write section spec to tasks/specs/<section_name>.md using file_editor — include exact CSS values from browser_inspector, component list, asset paths, and interaction behaviors"}
Builder steps that follow MUST reference the spec file path so they read it rather than
relying on conversation context. This keeps executor context small and specs auditable.
"""


class PlannerAgent:
    """Agent responsible for creating and updating plans."""

    def __init__(
        self,
        llm: LLMPort,
        event_bus: Optional[EventBusPort] = None,
        model: Optional[str] = None,
        skill_prompt: Optional[str] = None,
        facts: Optional[Dict[str, Any]] = None,
        episodic_memory=None,
        prompt_variant_id: str | None = None,  # PromptRegistry variant (HyperAgents Enhancement 5)
    ):
        self._llm = llm
        self._event_bus = event_bus
        self._model = model
        self._episodic_memory = episodic_memory
        self._prompt_variant_id = prompt_variant_id
        system_prompt = self._get_system_prompt()
        # Only inject the spec-file rule for complex multi-section UI tasks
        # where explicit spec files genuinely reduce executor context pressure.
        # For simple tasks, this rule causes over-decomposition and executor loops.
        if skill_prompt and any(kw in skill_prompt.lower() for kw in ("multi-section", "multi-page", "5+ sections")):
            system_prompt += SPEC_FILE_RULE
        if skill_prompt:
            system_prompt = f"{system_prompt}\n\n{skill_prompt}"
        if facts:
            facts_block = "### Known Facts\n" + "\n".join(f"- {k}: {v}" for k, v in facts.items())
            system_prompt = f"{system_prompt}\n\n{facts_block}"
        self._memory: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt}
        ]

    def _get_system_prompt(self) -> str:
        variant = self._try_load_variant()
        if variant:
            return variant
        return _load_planner_prompt(_PLANNER_PROMPT_PATH, (
            'You are a planning agent. Given a user task, create a COMPLETE plan with ALL necessary steps.\n'
            'Do not add any text before or after the JSON. Output RAW JSON only.'
        ))

    def _get_update_prompt(self) -> str:
        variant = self._try_load_variant()
        if variant:
            return variant
        return _load_planner_prompt(_PLANNER_UPDATE_PATH, (
            'You are a planning agent. Update the plan keeping completed steps as-is.'
        ))

    def _try_load_variant(self) -> str | None:
        """Try loading a prompt variant from PromptRegistry, return None on failure."""
        if not self._prompt_variant_id:
            return None
        try:
            from weebot.application.services.prompt_registry import PromptRegistry
            registry = PromptRegistry()
            content = registry.get_variant(self._prompt_variant_id)
            if content and content.prompt_content:
                return content.prompt_content
        except Exception:
            pass
        return None

    async def _emit(self, event: AgentEvent) -> None:
        if self._event_bus:
            await self._event_bus.publish(event)

    @staticmethod
    def _strip_code_fences(content: str) -> str:
        stripped = content.strip()
        if stripped.startswith("```"):
            lines = stripped.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            return "\n".join(lines).strip()
        return stripped

    @classmethod
    def _parse_json_content(cls, content: str) -> Dict[str, Any]:
        cleaned = cls._strip_code_fences(content)

        # Fast path: strict parse
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # raw_decode: stops at first complete JSON object (handles trailing text)
        try:
            decoder = json.JSONDecoder()
            obj, _ = decoder.raw_decode(cleaned)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

        # Brace-depth matching: find first { and its matching }
        start = cleaned.find("{")
        if start != -1:
            depth = 0
            for i in range(start, len(cleaned)):
                if cleaned[i] == "{":
                    depth += 1
                elif cleaned[i] == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(cleaned[start:i + 1])
                        except json.JSONDecodeError:
                            break

        # Last resort: rfind approach (handles most cases)
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError:
                pass

        raise ValueError(f"Could not extract valid JSON from: {cleaned[:200]}")

    async def _request_json_retry(self, memory: List[Dict[str, Any]]) -> Dict[str, Any]:
        retry_memory = list(memory)
        retry_memory.append({
            "role": "user",
            "content": "Your previous response was invalid JSON. Return ONLY a valid JSON object matching the required schema.",
        })
        retry_response = await self._llm.chat(
            messages=retry_memory,
            response_format={"type": "json_object"},
            temperature=TEMPERATURE_DETERMINISTIC,
            max_tokens=MAX_TOKENS_PLANNING,
        )
        return self._parse_json_content(retry_response.content)

    @staticmethod
    def _minimal_fallback_plan(prompt: str) -> Dict[str, Any]:
        short = re.sub(r"\s+", " ", prompt).strip()
        return {
            "title": "Fallback Plan",
            "message": "Generated fallback plan after planner JSON failure.",
            "steps": [
                {"id": "step-1", "description": f"Work on user request: {short[:120]}", "status": "pending"},
                {"id": "step-2", "description": "Summarize findings and ask if user needs follow-up.", "status": "pending"},
            ],
        }

    async def create_plan(
        self,
        prompt: str,
        attachments: Optional[List[str]] = None,
        meta_notes: Optional[list[str]] = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        # Reset _memory to just the system prompt so stale conversation
        # from a previous create_plan() call doesn't pollute this one.
        system_prompt = self._memory[0]["content"] if self._memory else self._get_system_prompt()
        self._memory = [{"role": "system", "content": system_prompt}]

        user_msg = prompt
        if attachments:
            user_msg += "\n\nAttachments:\n" + "\n".join(attachments)

        if self._episodic_memory is not None:
            examples = await self._episodic_memory.get_few_shot_examples(prompt, k=3)
            if examples:
                user_msg = f"{examples}\n\n{user_msg}"

        # ── HyperAgents Enhancement 1: inject meta-notes from prior runs ──
        if meta_notes:
            notes_block = (
                "\n\n## Lessons from Prior Tasks (Meta-Analysis)\n"
                + "\n".join(f"- {note}" for note in meta_notes[-5:])
                + "\n\nApply these lessons when creating the plan."
            )
            user_msg = user_msg + notes_block

        self._memory.append({"role": "user", "content": user_msg})

        yield MessageEvent(role="assistant", message="Creating plan...")

        response = await self._llm.chat(
            messages=self._memory,
            response_format={"type": "json_object"},
            temperature=TEMPERATURE_DETERMINISTIC,
            max_tokens=MAX_TOKENS_PLANNING,
        )

        self._memory.append({"role": "assistant", "content": response.content})

        try:
            parsed = self._parse_json_content(response.content)
        except Exception:
            try:
                parsed = await self._request_json_retry(self._memory)
            except Exception as exc:
                logger.exception("Failed to parse plan after retry")
                parsed = self._minimal_fallback_plan(prompt)
                yield ErrorEvent(error=f"Plan parsing failed; using fallback plan: {exc}")

        plan = self._parse_plan(parsed)
        yield TitleEvent(title=plan.title)
        yield PlanEvent(status=PlanStatus.CREATED, plan=plan.model_dump())

    async def update_plan(self, plan: Plan, completed_step: Step, failure_context: str = "") -> AsyncGenerator[AgentEvent, None]:
        """Update the plan given the completed step. Optional *failure_context* from the
        previous execution attempt is injected into the prompt so the LLM can avoid
        repeating the same blocked/erroneous patterns."""
        user_content = f"Current plan:\n{plan.model_dump_json()}\n\nCompleted step:\n{completed_step.model_dump_json()}"
        if failure_context:
            user_content += (
                f"\n\nThe previous step failed with: {failure_context[:1000]}\n"
                "IMPORTANT: Do NOT attempt the same command or pattern. "
                "If the failure is a security policy block or timeout, redesign the step "
                "to use a fundamentally different approach (different tool, scoped query, or ask the user)."
            )

        update_memory = [
            {"role": "system", "content": self._get_update_prompt()},
            {"role": "user", "content": user_content},
        ]

        yield MessageEvent(role="assistant", message="Updating plan...")

        response = await self._llm.chat(
            messages=update_memory,
            response_format={"type": "json_object"},
            temperature=TEMPERATURE_DETERMINISTIC,
            max_tokens=MAX_TOKENS_PLANNING,
        )

        try:
            parsed = self._parse_json_content(response.content)
            updated_plan = self._parse_plan(parsed)
            merged = plan.merge(updated_plan)
            yield PlanEvent(status=PlanStatus.UPDATED, plan=merged.model_dump())
        except Exception as exc:
            logger.exception("Failed to update plan")
            yield ErrorEvent(error=f"Plan update failed: {exc}")

    # Maximum discrete items (files, images, operations) a single step
    # should generate.  Steps listing more items than this are automatically
    # split into sub-steps.
    _MAX_ITEMS_PER_STEP: int = 5

    # Patterns for steps that write spec files — these cause executor loops
    # when the conversation buffer fills up and the LLM can't complete the file.
    _SPEC_STEP_PATTERNS: list = [
        r'tasks/specs/',
        r'write.*spec.*to.*tasks/specs',
        r'file_editor.*tasks/specs',
        r'section spec.*tasks/specs',
    ]

    @staticmethod
    def _parse_plan(data: Dict[str, Any]) -> Plan:
        import re as _re
        steps_data = data.get("steps", [])
        steps = []
        spec_count = 0
        for idx, s in enumerate(steps_data):
            step_id = s.get("id") or f"step-{idx + 1}"
            desc = s.get("description", "")
            # Filter: drop spec-writing steps that cause executor loops.
            # Allow at most 1 spec step per plan (some tasks genuinely need one).
            is_spec_step = any(
                _re.search(pat, desc, _re.IGNORECASE)
                for pat in PlannerAgent._SPEC_STEP_PATTERNS
            )
            if is_spec_step:
                spec_count += 1
                if spec_count > 1:
                    continue  # drop excessive spec steps

            # Heuristic: count discrete items (files, images) in the step.
            # If there are more than MAX_ITEMS_PER_STEP, split into batches.
            _item_keywords = r'\b(?:hero|project\d|skill-|icon-|og-|profile|avatar|logo|favicon|banner|thumb)[\w.-]*'
            items = _re.findall(_item_keywords, desc, _re.IGNORECASE)
            unique_items = list(dict.fromkeys(items))  # dedup preserving order
            if len(unique_items) > PlannerAgent._MAX_ITEMS_PER_STEP:
                batch_size = PlannerAgent._MAX_ITEMS_PER_STEP
                for batch_num, i in enumerate(range(0, len(unique_items), batch_size)):
                    batch_items = unique_items[i:i + batch_size]
                    batch_desc = desc + f" (batch {batch_num + 1}: {', '.join(batch_items)})"
                    batch_id = f"{step_id}-b{batch_num + 1}" if batch_num > 0 else step_id
                    steps.append(Step(id=batch_id, description=batch_desc, status="pending"))
            else:
                steps.append(Step(
                    id=step_id,
                    description=desc,
                    status="pending",
                ))
        return Plan(
            title=data.get("title", "Untitled Plan"),
            message=data.get("message", ""),
            steps=steps,
        )
