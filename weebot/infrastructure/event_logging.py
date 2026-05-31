"""Automatic event logging for agent actions.

This module provides decorators and helpers for automatically logging
agent actions to the event store.
"""
from __future__ import annotations

import functools
import logging
from typing import Any, Callable, Optional, TypeVar

from weebot.infrastructure.event_store import EventStore

logger = logging.getLogger(__name__)
T = TypeVar("T")


class EventLogger:
    """Logs agent actions to the event store.

    This class provides methods for logging various types of agent actions,
    including LLM calls, tool executions, bash commands, and plan operations.

    Example:
        >>> event_logger = EventLogger()
        >>> event_logger.log_llm_call("session-1", "gpt-4", "Hello", "Hi", 150, 0.02)
        >>> event_logger.log_tool_call("session-1", "bash", {"cmd": "ls"}, {"output": "file.txt"})
    """

    def __init__(self, event_store: Optional[EventStore] = None):
        """Initialize the event logger.

        Args:
            event_store: EventStore instance (creates default if None)
        """
        self.event_store = event_store or EventStore()

    def log_llm_call(
        self,
        session_id: str,
        model: str,
        prompt: str,
        response: str,
        tokens_used: int,
        cost: float,
        metadata: Optional[dict[str, Any]] = None,
    ) -> int:
        """Log an LLM call.

        Args:
            session_id: Session identifier
            model: Model name
            prompt: Input prompt
            response: Model response
            tokens_used: Total tokens consumed
            cost: Cost in USD
            metadata: Additional metadata

        Returns:
            Event ID
        """
        data = {
            "model": model,
            "prompt_length": len(prompt),
            "response_length": len(response),
            "prompt_preview": prompt[:500] if len(prompt) > 500 else prompt,
            "response_preview": response[:500] if len(response) > 500 else response,
        }
        if metadata:
            data.update(metadata)

        return self.event_store.log_event(
            session_id=session_id,
            event_type="llm_call",
            data=data,
            cost=cost,
            model=model,
            tokens_used=tokens_used,
        )

    def log_tool_call(
        self,
        session_id: str,
        tool_name: str,
        parameters: dict[str, Any],
        result: dict[str, Any],
        duration_ms: Optional[int] = None,
    ) -> int:
        """Log a tool execution.

        Args:
            session_id: Session identifier
            tool_name: Name of the tool
            parameters: Tool parameters
            result: Tool result
            duration_ms: Execution duration in milliseconds

        Returns:
            Event ID
        """
        output = str(result.get("output", ""))
        data = {
            "tool": tool_name,
            "parameters": parameters,
            "success": result.get("success", False),
            "output_preview": output[:500] if len(output) > 500 else output,
        }
        if duration_ms is not None:
            data["duration_ms"] = duration_ms

        return self.event_store.log_event(
            session_id=session_id,
            event_type="tool_call",
            data=data,
        )

    def log_bash_command(
        self,
        session_id: str,
        command: str,
        risk_level: str,
        approved: bool,
        output: str,
        exit_code: Optional[int] = None,
    ) -> int:
        """Log a bash command execution.

        Args:
            session_id: Session identifier
            command: The command executed
            risk_level: Risk assessment (safe/suspicious/dangerous/blocked)
            approved: Whether command was approved
            output: Command output
            exit_code: Command exit code

        Returns:
            Event ID
        """
        data = {
            "command": command,
            "risk_level": risk_level,
            "approved": approved,
            "output_preview": output[:500] if len(output) > 500 else output,
        }
        if exit_code is not None:
            data["exit_code"] = exit_code

        return self.event_store.log_event(
            session_id=session_id,
            event_type="bash_command",
            data=data,
        )

    def log_plan_created(
        self,
        session_id: str,
        plan: dict[str, Any],
    ) -> int:
        """Log plan creation.

        Args:
            session_id: Session identifier
            plan: Plan data

        Returns:
            Event ID
        """
        return self.event_store.log_event(
            session_id=session_id,
            event_type="plan_created",
            data={
                "plan_id": plan.get("id"),
                "plan_title": plan.get("title"),
                "step_count": len(plan.get("steps", [])),
                "plan": plan,
            },
        )

    def log_plan_updated(
        self,
        session_id: str,
        update: dict[str, Any],
    ) -> int:
        """Log plan update.

        Args:
            session_id: Session identifier
            update: Update data

        Returns:
            Event ID
        """
        return self.event_store.log_event(
            session_id=session_id,
            event_type="plan_updated",
            data={"update": update},
        )

    def log_step_started(
        self,
        session_id: str,
        step_id: str,
        step_description: str,
    ) -> int:
        """Log step start.

        Args:
            session_id: Session identifier
            step_id: Step identifier
            step_description: Step description

        Returns:
            Event ID
        """
        return self.event_store.log_event(
            session_id=session_id,
            event_type="step_started",
            data={
                "step_id": step_id,
                "description": step_description,
            },
        )

    def log_step_completed(
        self,
        session_id: str,
        step_id: str,
        success: bool = True,
        result: Optional[str] = None,
    ) -> int:
        """Log step completion.

        Args:
            session_id: Session identifier
            step_id: Step identifier
            success: Whether step succeeded
            result: Optional result summary

        Returns:
            Event ID
        """
        return self.event_store.log_event(
            session_id=session_id,
            event_type="step_completed",
            data={
                "step_id": step_id,
                "success": success,
                "result": result,
            },
        )

    def log_error(
        self,
        session_id: str,
        error_type: str,
        error_message: str,
        traceback: Optional[str] = None,
    ) -> int:
        """Log an error.

        Args:
            session_id: Session identifier
            error_type: Type of error
            error_message: Error message
            traceback: Optional traceback

        Returns:
            Event ID
        """
        data = {
            "error_type": error_type,
            "error_message": error_message,
        }
        if traceback:
            data["traceback_preview"] = traceback[:1000] if len(traceback) > 1000 else traceback

        return self.event_store.log_event(
            session_id=session_id,
            event_type="error",
            data=data,
        )

    def log_user_message(
        self,
        session_id: str,
        message: str,
    ) -> int:
        """Log a user message.

        Args:
            session_id: Session identifier
            message: User message

        Returns:
            Event ID
        """
        return self.event_store.log_event(
            session_id=session_id,
            event_type="user_message",
            data={
                "message_preview": message[:500] if len(message) > 500 else message,
            },
        )

    def log_assistant_message(
        self,
        session_id: str,
        message: str,
    ) -> int:
        """Log an assistant message.

        Args:
            session_id: Session identifier
            message: Assistant message

        Returns:
            Event ID
        """
        return self.event_store.log_event(
            session_id=session_id,
            event_type="assistant_message",
            data={
                "message_preview": message[:500] if len(message) > 500 else message,
            },
        )


# Global default instance
default_event_logger = EventLogger()


def log_execution(
    event_type: str,
    session_id_arg: str = "session_id",
    extract_data: Optional[Callable[..., dict[str, Any]]] = None,
) -> Callable[[T], T]:
    """Decorator to log function execution.

    Args:
        event_type: Type of event to log
        session_id_arg: Name of argument containing session_id
        extract_data: Optional function to extract data from arguments

    Returns:
        Decorator function
    """
    def decorator(func: T) -> T:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Get session_id from kwargs or args
            session_id = kwargs.get(session_id_arg)
            if session_id is None and args:
                # Try to get from first arg if it's a string
                if isinstance(args[0], str):
                    session_id = args[0]

            if session_id is None:
                session_id = "unknown"

            # Extract data
            data: dict[str, Any] = {"function": func.__name__}
            if extract_data:
                try:
                    data.update(extract_data(*args, **kwargs))
                except Exception as e:
                    logger.warning(f"Failed to extract data for logging: {e}")

            # Log before execution
            try:
                default_event_logger.event_store.log_event(
                    session_id=session_id,
                    event_type=f"{event_type}_started",
                    data=data,
                )
            except Exception as e:
                logger.warning(f"Failed to log event: {e}")

            # Execute function
            try:
                result = func(*args, **kwargs)

                # Log success
                try:
                    default_event_logger.event_store.log_event(
                        session_id=session_id,
                        event_type=f"{event_type}_completed",
                        data={**data, "success": True},
                    )
                except Exception as e:
                    logger.warning(f"Failed to log event: {e}")

                return result

            except Exception as e:
                # Log error
                try:
                    default_event_logger.event_store.log_event(
                        session_id=session_id,
                        event_type=f"{event_type}_error",
                        data={**data, "success": False, "error": str(e)},
                    )
                except Exception as log_e:
                    logger.warning(f"Failed to log event: {log_e}")

                raise

        return wrapper  # type: ignore
    return decorator
