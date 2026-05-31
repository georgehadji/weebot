"""Planner agent — creates and updates structured JSON plans."""
from __future__ import annotations

import json
import logging
import re
from typing import Any, AsyncGenerator, Dict, List, Optional

from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.ports.llm_port import LLMPort
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

PLANNER_SYSTEM_PROMPT = """You are a planning agent. Given a user task, create a COMPLETE plan with ALL necessary steps.

CRITICAL: Respond ONLY with valid JSON. Do not wrap in markdown code blocks. Do not add any text before or after the JSON.

Required JSON structure:
{
  "title": "Short title",
  "message": "Brief plan summary",
  "steps": [
    {"id": "step-1", "description": "First action", "status": "pending"},
    {"id": "step-2", "description": "Second action", "status": "pending"}
  ]
}

Rules:
- Create ALL steps needed to fully complete the task - do not stop at just one or two steps
- For file operations: include steps to find files, verify destination, move/copy files, and verify completion
- Include a follow-up step ONLY when user clarification is genuinely needed to continue
- ONLY create steps that this agent can execute with available tools (searching, reading, writing, code edits, shell commands, browser/web tools)
- Do NOT create human-only or physical-world steps (e.g., phone calls, visiting properties, signing legal documents)
- If a human-only action is required, end with one concise informational step telling the user what they must do next
- Each step must have: unique "id", "description", and "status" set to "pending"
- Output RAW JSON only, no ```json markers
- Keep descriptions actionable and specific
"""

UPDATE_PLAN_SYSTEM_PROMPT = """You are a planning agent. Given the current plan and the most recently completed step,
update the plan if needed.

CRITICAL: Respond ONLY with valid JSON. Do not wrap in markdown code blocks. Do not add any text before or after the JSON.

Keep completed steps as-is. Adjust or add pending steps based on new information.
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
    ):
        self._llm = llm
        self._event_bus = event_bus
        self._model = model
        self._episodic_memory = episodic_memory
        system_prompt = PLANNER_SYSTEM_PROMPT
        if skill_prompt:
            system_prompt = f"{PLANNER_SYSTEM_PROMPT}\n\n{skill_prompt}"
        if facts:
            facts_block = "### Known Facts\n" + "\n".join(f"- {k}: {v}" for k, v in facts.items())
            system_prompt = f"{system_prompt}\n\n{facts_block}"
        self._memory: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt}
        ]

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

    @staticmethod
    def _extract_json_object(content: str) -> str:
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and end > start:
            return content[start:end + 1]
        return content

    @classmethod
    def _parse_json_content(cls, content: str) -> Dict[str, Any]:
        cleaned = cls._strip_code_fences(content)
        try:
            return json.loads(cleaned)
        except Exception:
            extracted = cls._extract_json_object(cleaned)
            return json.loads(extracted)

    async def _request_json_retry(self, memory: List[Dict[str, Any]]) -> Dict[str, Any]:
        retry_memory = list(memory)
        retry_memory.append({
            "role": "user",
            "content": "Your previous response was invalid JSON. Return ONLY a valid JSON object matching the required schema.",
        })
        retry_response = await self._llm.chat(
            messages=retry_memory,
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=4096,
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

    async def create_plan(self, prompt: str, attachments: Optional[List[str]] = None) -> AsyncGenerator[AgentEvent, None]:
        # Reset _memory to just the system prompt so stale conversation
        # from a previous create_plan() call doesn't pollute this one.
        system_prompt = self._memory[0]["content"] if self._memory else PLANNER_SYSTEM_PROMPT
        self._memory = [{"role": "system", "content": system_prompt}]

        user_msg = prompt
        if attachments:
            user_msg += "\n\nAttachments:\n" + "\n".join(attachments)

        if self._episodic_memory is not None:
            examples = await self._episodic_memory.get_few_shot_examples(prompt, k=3)
            if examples:
                user_msg = f"{examples}\n\n{user_msg}"

        self._memory.append({"role": "user", "content": user_msg})

        yield MessageEvent(role="assistant", message="Creating plan...")

        response = await self._llm.chat(
            messages=self._memory,
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=4096,
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

    async def update_plan(self, plan: Plan, completed_step: Step) -> AsyncGenerator[AgentEvent, None]:
        update_memory = [
            {"role": "system", "content": UPDATE_PLAN_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Current plan:\n{plan.model_dump_json()}\n\nCompleted step:\n{completed_step.model_dump_json()}",
            },
        ]

        yield MessageEvent(role="assistant", message="Updating plan...")

        response = await self._llm.chat(
            messages=update_memory,
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=4096,
        )

        try:
            parsed = self._parse_json_content(response.content)
            updated_plan = self._parse_plan(parsed)
            merged = plan.merge(updated_plan)
            yield PlanEvent(status=PlanStatus.UPDATED, plan=merged.model_dump())
        except Exception as exc:
            logger.exception("Failed to update plan")
            yield ErrorEvent(error=f"Plan update failed: {exc}")

    @staticmethod
    def _parse_plan(data: Dict[str, Any]) -> Plan:
        steps_data = data.get("steps", [])
        steps = []
        for idx, s in enumerate(steps_data):
            step_id = s.get("id") or f"step-{idx + 1}"
            steps.append(Step(
                id=step_id,
                description=s.get("description", ""),
                status="pending",
            ))
        return Plan(
            title=data.get("title", "Untitled Plan"),
            message=data.get("message", ""),
            steps=steps,
        )
