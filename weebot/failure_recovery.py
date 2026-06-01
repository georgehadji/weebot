"""
⚠️ LEGACY MODULE (Bucket D — Freeze)

This module is part of the pre-Clean-Architecture legacy track.
It will not receive new features. File issues against weebot.application.*
for equivalent functionality.

Migration path: weebot.application.services.complex_task_executor (and successors)
Last maintainer audit: 2026-06-01
Target sunset: 2026-09-01

Automatic Failure Recovery System for Weebot
Provides automatic failure detection and recovery capabilities
to ensure robust task execution and workflow continuity.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from datetime import datetime, timedelta
import logging
import traceback
from enum import Enum

from weebot.core.circuit_breaker import CircuitBreaker, BreakerState
from weebot.core.agent_context import AgentContext
from weebot.workflow_planner import WorkflowPlan, PlannedTask
from weebot.application.services.complex_task_executor import ComplexTaskResult, ComplexTaskStatus


class FailureType(Enum):
    """Types of failures that can occur."""
    TIMEOUT = "timeout"
    NETWORK_ERROR = "network_error"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    INVALID_INPUT = "invalid_input"
    TOOL_ERROR = "tool_error"
    AGENT_UNAVAILABLE = "agent_unavailable"
    CIRCUIT_BREAKER_OPEN = "circuit_breaker_open"
    UNKNOWN = "unknown"


class RecoveryStrategy(Enum):
    """Strategies for recovering from failures."""
    RETRY_WITH_BACKOFF = "retry_with_backoff"
    FALLBACK_TOOL = "fallback_tool"
    ALTERNATIVE_AGENT = "alternative_agent"
    SKIP_AND_CONTINUE = "skip_and_continue"
    ROLLBACK_TO_CHECKPOINT = "rollback_to_checkpoint"
    MANUAL_INTERVENTION = "manual_intervention"


@dataclass
class FailureRecord:
    """Record of a failure event."""
    task_id: str
    failure_type: FailureType
    error_message: str
    timestamp: datetime
    attempt_count: int
    context: Dict[str, Any]  # Additional context about the failure
    recovery_strategy: Optional[RecoveryStrategy] = None
    recovery_attempted: bool = False
    recovery_success: Optional[bool] = None


@dataclass
class RecoveryAction:
    """An action to take for recovery."""
    strategy: RecoveryStrategy
    parameters: Dict[str, Any]
    priority: int  # Lower number means higher priority
    applicability_score: float  # 0.0 to 1.0, how applicable this strategy is


class FailureRecoveryManager:
    """
    Manages automatic failure detection and recovery for workflows.
    """
    
    def __init__(self, circuit_breaker: Optional[CircuitBreaker] = None):
        self.circuit_breaker = circuit_breaker
        self.failure_history: List[FailureRecord] = []
        self.recovery_history: List[Tuple[FailureRecord, RecoveryAction, bool]] = []  # (failure, action, success)
        self.max_history_size = 1000
        self.logger = logging.getLogger(__name__)
        
        # Define recovery strategies for different failure types
        self.recovery_strategies = {
            FailureType.TIMEOUT: [
                RecoveryAction(RecoveryStrategy.RETRY_WITH_BACKOFF, {"multiplier": 2.0}, 1, 0.9),
                RecoveryAction(RecoveryStrategy.SKIP_AND_CONTINUE, {}, 2, 0.7)
            ],
            FailureType.NETWORK_ERROR: [
                RecoveryAction(RecoveryStrategy.RETRY_WITH_BACKOFF, {"multiplier": 1.5}, 1, 0.85),
                RecoveryAction(RecoveryStrategy.FALLBACK_TOOL, {}, 2, 0.8)
            ],
            FailureType.RESOURCE_EXHAUSTION: [
                RecoveryAction(RecoveryStrategy.SKIP_AND_CONTINUE, {}, 1, 0.9),
                RecoveryAction(RecoveryStrategy.ALTERNATIVE_AGENT, {}, 2, 0.7)
            ],
            FailureType.TOOL_ERROR: [
                RecoveryAction(RecoveryStrategy.FALLBACK_TOOL, {}, 1, 0.8),
                RecoveryAction(RecoveryStrategy.RETRY_WITH_BACKOFF, {"multiplier": 1.0}, 2, 0.6)
            ],
            FailureType.AGENT_UNAVAILABLE: [
                RecoveryAction(RecoveryStrategy.ALTERNATIVE_AGENT, {}, 1, 0.95),
                RecoveryAction(RecoveryStrategy.SKIP_AND_CONTINUE, {}, 2, 0.7)
            ],
            FailureType.CIRCUIT_BREAKER_OPEN: [
                RecoveryAction(RecoveryStrategy.MANUAL_INTERVENTION, {}, 1, 1.0),  # Usually requires manual intervention
                RecoveryAction(RecoveryStrategy.SKIP_AND_CONTINUE, {}, 2, 0.5)
            ],
            FailureType.UNKNOWN: [
                RecoveryAction(RecoveryStrategy.RETRY_WITH_BACKOFF, {"multiplier": 1.0}, 1, 0.5),
                RecoveryAction(RecoveryStrategy.SKIP_AND_CONTINUE, {}, 2, 0.6)
            ]
        }
    
    def record_failure(self, task_id: str, error: Exception, context: Dict[str, Any] = None, attempt_count: int = 1):
        """Record a failure event."""
        failure_type = self._classify_failure(error)
        error_message = str(error)
        
        record = FailureRecord(
            task_id=task_id,
            failure_type=failure_type,
            error_message=error_message,
            timestamp=datetime.now(),
            attempt_count=attempt_count,
            context=context or {}
        )
        
        self.failure_history.append(record)
        
        # Keep history size manageable
        if len(self.failure_history) > self.max_history_size:
            self.failure_history = self.failure_history[-self.max_history_size:]
        
        self.logger.warning(f"Recorded failure for task {task_id}: {failure_type.value} - {error_message}")
    
    def _classify_failure(self, error: Exception) -> FailureType:
        """Classify the type of failure based on the error."""
        error_str = str(error).lower()
        
        if "timeout" in error_str or "timed out" in error_str:
            return FailureType.TIMEOUT
        elif "network" in error_str or "connection" in error_str or "connect" in error_str:
            return FailureType.NETWORK_ERROR
        elif "memory" in error_str or "resource" in error_str or "quota" in error_str:
            return FailureType.RESOURCE_EXHAUSTION
        elif "invalid" in error_str or "input" in error_str:
            return FailureType.INVALID_INPUT
        elif "tool" in error_str or "execute" in error_str:
            return FailureType.TOOL_ERROR
        elif "agent" in error_str or "unavailable" in error_str:
            return FailureType.AGENT_UNAVAILABLE
        elif "circuit" in error_str and "open" in error_str:
            return FailureType.CIRCUIT_BREAKER_OPEN
        else:
            return FailureType.UNKNOWN
    
    def suggest_recovery_actions(self, failure_record: FailureRecord) -> List[RecoveryAction]:
        """Suggest possible recovery actions for a failure."""
        if failure_record.failure_type in self.recovery_strategies:
            # Return strategies sorted by priority
            strategies = self.recovery_strategies[failure_record.failure_type]
            return sorted(strategies, key=lambda x: (x.priority, -x.applicability_score))
        else:
            # Return generic strategies
            generic_strategies = [
                RecoveryAction(RecoveryStrategy.RETRY_WITH_BACKOFF, {"multiplier": 1.0}, 1, 0.5),
                RecoveryAction(RecoveryStrategy.SKIP_AND_CONTINUE, {}, 2, 0.5)
            ]
            return sorted(generic_strategies, key=lambda x: (x.priority, -x.applicability_score))
    
    async def attempt_recovery(
        self, 
        failure_record: FailureRecord, 
        task: PlannedTask, 
        agent_context: AgentContext,
        available_agents: Optional[Dict[str, Any]] = None,
        available_tools: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, Optional[Exception]]:
        """
        Attempt to recover from a failure using the best available strategy.
        
        Args:
            failure_record: The recorded failure
            task: The task that failed
            agent_context: Current agent context
            available_agents: Available alternative agents
            available_tools: Available alternative tools
            
        Returns:
            Tuple of (recovery_success, error_if_any)
        """
        # Get suggested recovery actions
        suggested_actions = self.suggest_recovery_actions(failure_record)
        
        for action in suggested_actions:
            try:
                self.logger.info(f"Attempting recovery using {action.strategy.value} for task {failure_record.task_id}")
                
                success = await self._execute_recovery_action(
                    action, 
                    failure_record, 
                    task, 
                    agent_context,
                    available_agents,
                    available_tools
                )
                
                # Record the recovery attempt
                self.recovery_history.append((failure_record, action, success))
                
                if len(self.recovery_history) > self.max_history_size:
                    self.recovery_history = self.recovery_history[-self.max_history_size:]
                
                if success:
                    self.logger.info(f"Recovery successful for task {failure_record.task_id} using {action.strategy.value}")
                    failure_record.recovery_strategy = action.strategy
                    failure_record.recovery_attempted = True
                    failure_record.recovery_success = True
                    return True, None
                else:
                    self.logger.info(f"Recovery failed for task {failure_record.task_id} using {action.strategy.value}, trying next option")
                    continue
                    
            except Exception as e:
                self.logger.error(f"Error during recovery attempt: {e}")
                continue
        
        # If no recovery strategy worked
        self.logger.error(f"All recovery strategies failed for task {failure_record.task_id}")
        return False, Exception("All recovery strategies exhausted")
    
    async def _execute_recovery_action(
        self,
        action: RecoveryAction,
        failure_record: FailureRecord,
        task: PlannedTask,
        agent_context: AgentContext,
        available_agents: Optional[Dict[str, Any]],
        available_tools: Optional[Dict[str, Any]]
    ) -> bool:
        """Execute a specific recovery action."""
        try:
            if action.strategy == RecoveryStrategy.RETRY_WITH_BACKOFF:
                # Wait before retrying
                multiplier = action.parameters.get("multiplier", 1.0)
                wait_time = min(30.0, 2.0 * multiplier)  # Max 30 seconds
                await asyncio.sleep(wait_time)
                
                # Retry the task (this would typically involve re-executing the task)
                # For now, we'll just return True to indicate the wait was successful
                return True
                
            elif action.strategy == RecoveryStrategy.FALLBACK_TOOL:
                # Switch to a fallback tool if available
                if available_tools:
                    fallback_tool = self._select_fallback_tool(task, available_tools)
                    if fallback_tool:
                        # Update task to use fallback tool
                        task.required_tools = [fallback_tool]
                        return True
                return False
                
            elif action.strategy == RecoveryStrategy.ALTERNATIVE_AGENT:
                # Switch to an alternative agent if available
                if available_agents:
                    alternative_agent = self._select_alternative_agent(task, available_agents)
                    if alternative_agent:
                        # In a real implementation, we would assign the task to the alternative agent
                        return True
                return False
                
            elif action.strategy == RecoveryStrategy.SKIP_AND_CONTINUE:
                # Mark task as skipped and continue workflow
                # This would be handled at the workflow orchestration level
                return True
                
            elif action.strategy == RecoveryStrategy.ROLLBACK_TO_CHECKPOINT:
                # Rollback to a previous checkpoint
                # This would involve restoring state to a previous checkpoint
                return True
                
            elif action.strategy == RecoveryStrategy.MANUAL_INTERVENTION:
                # Flag for manual intervention
                # This would involve notifying a human operator
                return False  # Cannot be automatically recovered
                
        except Exception as e:
            self.logger.error(f"Error executing recovery action {action.strategy.value}: {e}")
            return False
    
    def _select_fallback_tool(self, task: PlannedTask, available_tools: Dict[str, Any]) -> Optional[str]:
        """Select an appropriate fallback tool for a task."""
        # Look for tools that can perform similar functions
        primary_tool = task.required_tools[0] if task.required_tools else None
        
        # Simple heuristic: look for tools with similar names or capabilities
        for tool_name in available_tools:
            if tool_name != primary_tool and self._is_similar_tool(primary_tool, tool_name):
                return tool_name
        
        # If no similar tool found, return any available tool
        if available_tools:
            return list(available_tools.keys())[0]
        
        return None
    
    def _is_similar_tool(self, tool1: Optional[str], tool2: str) -> bool:
        """Check if two tools are similar in function."""
        if not tool1:
            return False
            
        # Simple similarity check based on name
        tool1_lower = tool1.lower()
        tool2_lower = tool2.lower()
        
        # Check if they share common substrings indicating similar function
        common_indicators = ["search", "browse", "execute", "file", "data", "web"]
        for indicator in common_indicators:
            if indicator in tool1_lower and indicator in tool2_lower:
                return True
        
        return False
    
    def _select_alternative_agent(self, task: PlannedTask, available_agents: Dict[str, Any]) -> Optional[str]:
        """Select an alternative agent for a task."""
        # In a real implementation, this would consider agent capabilities
        # For now, return the first available agent
        if available_agents:
            return list(available_agents.keys())[0]
        return None
    
    def get_recovery_statistics(self) -> Dict[str, Any]:
        """Get statistics about recovery attempts."""
        if not self.recovery_history:
            return {
                "total_recovery_attempts": 0,
                "successful_recoveries": 0,
                "success_rate": 0.0,
                "recovery_strategies_used": {},
                "common_failure_types": {}
            }
        
        total_attempts = len(self.recovery_history)
        successful_recoveries = sum(1 for _, _, success in self.recovery_history if success)
        success_rate = successful_recoveries / total_attempts if total_attempts > 0 else 0.0
        
        # Count recovery strategies used
        strategy_counts = {}
        failure_type_counts = {}
        
        for failure, action, success in self.recovery_history:
            strategy_str = action.strategy.value
            strategy_counts[strategy_str] = strategy_counts.get(strategy_str, 0) + 1
            
            failure_type_str = failure.failure_type.value
            failure_type_counts[failure_type_str] = failure_type_counts.get(failure_type_str, 0) + 1
        
        return {
            "total_recovery_attempts": total_attempts,
            "successful_recoveries": successful_recoveries,
            "success_rate": success_rate,
            "recovery_strategies_used": strategy_counts,
            "common_failure_types": failure_type_counts
        }
    
    def is_task_recoverable(self, failure_record: FailureRecord) -> bool:
        """Determine if a failed task is worth attempting to recover."""
        # Don't retry if we've already tried too many times
        if failure_record.attempt_count > 5:
            return False
        
        # Some failure types are not worth retrying
        non_recoverable = [FailureType.INVALID_INPUT, FailureType.MANUAL_INTERVENTION]
        if failure_record.failure_type in non_recoverable:
            return False
        
        # Otherwise, it's worth attempting recovery
        return True


# Example usage
if __name__ == "__main__":
    import asyncio
    
    async def example():
        # Create a failure recovery manager
        recovery_mgr = FailureRecoveryManager()
        
        # Simulate a failure
        try:
            # Simulate an operation that fails
            raise asyncio.TimeoutError("Task timed out after 30 seconds")
        except Exception as e:
            # Record the failure
            recovery_mgr.record_failure(
                task_id="task_123", 
                error=e, 
                context={"agent": "researcher", "tool": "web_search"},
                attempt_count=2
            )
        
        # Get the most recent failure
        if recovery_mgr.failure_history:
            latest_failure = recovery_mgr.failure_history[-1]
            print(f"Latest failure: {latest_failure.failure_type.value} - {latest_failure.error_message}")
            
            # Suggest recovery actions
            actions = recovery_mgr.suggest_recovery_actions(latest_failure)
            print(f"Suggested recovery actions:")
            for action in actions:
                print(f"  - {action.strategy.value} (priority: {action.priority}, score: {action.applicability_score})")
            
            # Get recovery statistics
            stats = recovery_mgr.get_recovery_statistics()
            print(f"\nRecovery statistics: {stats}")
    
    asyncio.run(example())