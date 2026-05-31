"""Executor agent with structured output support.

This extends the base ExecutorAgent with structured output capabilities
for improved reliability and programmatic handling of responses.
"""
from __future__ import annotations

import logging
from typing import Any, AsyncGenerator, Dict, Optional

from weebot.application.agents.executor import ExecutorAgent
from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.ports.llm_port import LLMPort
from weebot.domain.models.event import (
    AgentEvent,
    ErrorEvent,
    MessageEvent,
    StepEvent,
    StepStatus,
)
from weebot.domain.models.plan import Plan, Step
from weebot.models.structured_output import (
    STRUCTURED_OUTPUT_PROMPT,
    WeebotOutput,
    parse_agent_output,
    TaskStatus,
)
from weebot.tools.base import ToolCollection

logger = logging.getLogger(__name__)


class StructuredExecutorAgent(ExecutorAgent):
    """Executor agent that produces structured output.

    This agent extends the base ExecutorAgent to mandate structured JSON output
    from the LLM, enabling better error handling, validation, and user interaction.

    Usage:
        agent = StructuredExecutorAgent(llm=llm_port, tools=tools)
        async for event in agent.execute_step_structured(plan, step):
            handle_event(event)
    """

    def __init__(
        self,
        llm: LLMPort,
        tools: ToolCollection,
        event_bus: Optional[EventBusPort] = None,
        model: Optional[str] = None,
        max_steps: int = 15,
        skill_prompt: Optional[str] = None,
        max_context_turns: int = 15,
        require_structured_output: bool = True,
    ):
        super().__init__(
            llm=llm,
            tools=tools,
            event_bus=event_bus,
            model=model,
            max_steps=max_steps,
            skill_prompt=skill_prompt,
            max_context_turns=max_context_turns,
        )
        self._require_structured = require_structured_output
        self._last_structured_output: Optional[WeebotOutput] = None

    async def execute_step_structured(
        self, plan: Plan, step: Step
    ) -> AsyncGenerator[AgentEvent, None]:
        """Execute a step with structured output.

        This method extends the base execute_step to:
        1. Include structured output requirements in the system prompt
        2. Parse responses as structured output
        3. Handle validation, user clarification, and errors programmatically

        Yields:
            AgentEvent events including:
            - StepEvent: Step start/completion
            - MessageEvent: Assistant messages
            - ErrorEvent: Execution errors
            - WaitForUserEvent: When user input needed (from parent class)
        """
        import time

        start_time = time.time()
        self._last_structured_output = None

        # Build system prompt with structured output requirements
        base_prompt = self._system_prompt or ""
        if self._require_structured:
            system_prompt = f"""{base_prompt}

{STRUCTURED_OUTPUT_PROMPT}

When responding after using tools, wrap your final response in the structured JSON format shown above.
Include code_changes if you modified files, bash_commands if you ran commands, and validation_results
if you performed any checks.
"""
        else:
            system_prompt = base_prompt

        yield StepEvent(
            step_id=step.id, description=step.description, status=StepStatus.STARTED
        )

        try:
            # Use the LLM to get a response
            messages = [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": f"Plan: {plan.title}\nStep: {step.description}\nExecute this step using available tools. Respond with structured JSON when complete.",
                },
            ]

            # Get response from LLM
            response = await self._llm.chat(
                messages=messages,
                tools=self._tools.to_params(),
                tool_choice="auto",
                model=self._model,
                temperature=0.2,
            )

            # Process tool calls if any
            if response.tool_calls:
                # Execute tools (delegating to parent class logic)
                for tc in response.tool_calls:
                    from weebot.domain.models.event import ToolEvent, ToolStatus

                    yield ToolEvent(
                        tool_call_id=tc["id"],
                        tool_name=tc["function"]["name"],
                        function_name=tc["function"]["name"],
                        function_args=__import__("json").loads(
                            tc["function"]["arguments"]
                        ),
                        status=ToolStatus.CALLING,
                    )

                    result = await self._execute_tool_call(tc)

                    yield ToolEvent(
                        tool_call_id=tc["id"],
                        tool_name=tc["function"]["name"],
                        function_name=tc["function"]["name"],
                        function_args=__import__("json").loads(
                            tc["function"]["arguments"]
                        ),
                        status=ToolStatus.CALLED,
                        result=str(result),
                    )

                    # Handle human-in-the-loop
                    if result.data and result.data.get("awaiting_human"):
                        from weebot.domain.models.event import WaitForUserEvent

                        question = result.data.get("question", "")
                        yield WaitForUserEvent(question=question)
                        return

            # Parse the content as structured output
            content = response.content or ""
            structured = parse_agent_output(content)

            # Add processing time
            structured.processing_time_ms = int((time.time() - start_time) * 1000)
            self._last_structured_output = structured

            # Handle based on status
            if structured.status == TaskStatus.SUCCESS:
                yield MessageEvent(
                    role="assistant",
                    message=f"{structured.message}\n\nReasoning: {structured.reasoning}",
                )

            elif structured.status == TaskStatus.PARTIAL:
                yield MessageEvent(
                    role="assistant",
                    message=f"Partial result: {structured.message}\n\nReasoning: {structured.reasoning}",
                )
                if structured.requires_user_input:
                    questions = "\n".join(
                        f"- {q}" for q in structured.suggested_questions
                    )
                    yield MessageEvent(
                        role="assistant",
                        message=f"I need more information:\n{questions}",
                    )

            elif structured.status == TaskStatus.NEEDS_CLARIFICATION:
                yield MessageEvent(
                    role="assistant",
                    message=f"I need clarification: {structured.message}",
                )
                if structured.suggested_questions:
                    questions = "\n".join(
                        f"- {q}" for q in structured.suggested_questions
                    )
                    yield MessageEvent(role="assistant", message=f"Consider:\n{questions}")

            elif structured.status == TaskStatus.FAILED:
                yield ErrorEvent(error=f"Step failed: {structured.message}")
                yield MessageEvent(
                    role="assistant",
                    message=f"Failed: {structured.reasoning}",
                )

            # Log code changes if any
            if structured.code_changes:
                changes_desc = "\n".join(
                    f"- {c.change_type}: {c.file_path} - {c.description}"
                    for c in structured.code_changes
                )
                yield MessageEvent(
                    role="assistant",
                    message=f"Code changes proposed:\n{changes_desc}",
                )

            # Log bash commands if any
            if structured.bash_commands:
                commands_desc = "\n".join(
                    f"- {bc.command} ({bc.purpose})"
                    for bc in structured.bash_commands
                )
                yield MessageEvent(
                    role="assistant",
                    message=f"Commands proposed:\n{commands_desc}",
                )

            yield StepEvent(
                step_id=step.id, description=step.description, status=StepStatus.COMPLETED
            )

        except Exception as e:
            logger.exception("Error in structured step execution")
            yield ErrorEvent(error=f"Execution error: {e}")
            yield StepEvent(
                step_id=step.id, description=step.description, status=StepStatus.FAILED
            )

    def get_last_output(self) -> Optional[WeebotOutput]:
        """Get the last structured output produced.

        Returns:
            WeebotOutput from the most recent step execution, or None
        """
        return self._last_structured_output

    def get_code_changes(self) -> list[Dict[str, Any]]:
        """Get code changes from the last output.

        Returns:
            List of code change dictionaries
        """
        if not self._last_structured_output:
            return []
        return [
            change.model_dump() for change in self._last_structured_output.code_changes
        ]

    def get_bash_commands(self) -> list[Dict[str, Any]]:
        """Get bash commands from the last output.

        Returns:
            List of bash command dictionaries
        """
        if not self._last_structured_output:
            return []
        return [
            cmd.model_dump() for cmd in self._last_structured_output.bash_commands
        ]
