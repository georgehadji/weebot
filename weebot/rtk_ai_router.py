"""
RTK-AI Router Interface Module

This module provides the interface between RTK token optimization and AI routing.
"""
import asyncio
import logging
from typing import Dict, Any, Optional
from pathlib import Path

from .rtk_provider import RTKProvider, get_rtk_provider
from .ai_router import TaskType

logger = logging.getLogger(__name__)


class RTKAIRouter:
    """
    Router that integrates RTK token optimization with AI routing decisions.
    
    Makes intelligent decisions about when to apply RTK optimization
    based on task type, command characteristics, and token economy.
    """
    
    def __init__(self):
        self.rtk_provider = get_rtk_provider()
    
    def select_model(self, task_type: TaskType, budget_constraint: Optional[float] = None) -> str:
        """
        Select the best model for the task considering RTK optimization opportunities.
        
        Args:
            task_type: Type of task being performed
            budget_constraint: Maximum cost per 1k tokens allowed
            
        Returns:
            Model name string
        """
        # For tasks that involve command execution, we might want to use models that work well
        # with RTK-optimized inputs
        if task_type in [TaskType.CODE_GENERATION, TaskType.CODE_REVIEW, TaskType.DEBUGGING]:
            # These tasks often involve examining command outputs, so use models with good reasoning
            if budget_constraint and budget_constraint < 0.005:
                return "gpt-4o-mini"  # Use cheaper model when budget is tight
            else:
                return "gpt-4o"  # Use premium model for complex tasks
        else:
            # For other tasks, use standard model selection
            if budget_constraint and budget_constraint < 0.005:
                return "gpt-4o-mini"
            else:
                return "gpt-3.5-turbo"


# Global RTK-AI router instance
_rtk_ai_router: Optional[RTKAIRouter] = None


def get_rtk_ai_router() -> RTKAIRouter:
    """
    Get the global RTK-AI router instance.
    
    Returns:
        RTKAIRouter instance
    """
    global _rtk_ai_router
    if _rtk_ai_router is None:
        _rtk_ai_router = RTKAIRouter()
    return _rtk_ai_router


async def execute_with_token_economy(
    command: str,
    task_type: TaskType,
    timeout: float = 30.0
) -> Dict[str, Any]:
    """
    Execute a command with token economy optimization via RTK.
    
    Args:
        command: Command to execute
        task_type: Type of task being performed
        timeout: Timeout in seconds
        
    Returns:
        Dictionary with execution results and optimization metadata
    """
    provider = get_rtk_provider()
    
    if not provider.is_available():
        # If RTK is not available, execute directly and return appropriate response
        return {
            "stdout": "",
            "stderr": "RTK not available, command not executed",
            "returncode": -1,
            "success": False,
            "token_savings_estimate": {
                "command_type": "unoptimized",
                "estimated_savings_percentage": 0,
                "typical_raw_tokens": 0,
                "typical_optimized_tokens": 0
            }
        }
    
    try:
        # Execute with RTK optimization
        stdout, stderr, returncode = await provider.execute_with_optimization(
            command, timeout
        )
        
        # Get token savings estimate
        token_savings_estimate = await provider.get_token_savings_estimate(command)
        
        return {
            "stdout": stdout,
            "stderr": stderr,
            "returncode": returncode,
            "success": returncode == 0 or (returncode == -1 and "timed out" not in stderr.lower()),
            "token_savings_estimate": token_savings_estimate,
            "rtk_command": provider.transform_command(command) if provider.should_optimize_command(command) else None
        }
        
    except Exception as e:
        logger.error(f"RTK execution failed: {e}")
        return {
            "stdout": "",
            "stderr": f"RTK execution error: {str(e)}",
            "returncode": -1,
            "success": False,
            "token_savings_estimate": {
                "command_type": "error",
                "estimated_savings_percentage": 0,
                "typical_raw_tokens": 0,
                "typical_optimized_tokens": 0
            }
        }


def is_command_execution_request(prompt: str) -> bool:
    """
    Determine if a prompt looks like a command execution request.
    
    Args:
        prompt: The prompt to analyze
        
    Returns:
        True if the prompt looks like a command execution request, False otherwise
    """
    # Common command patterns that benefit from RTK optimization
    command_indicators = [
        "execute", "run", "command", "bash", "shell", "terminal", 
        "ls", "git ", "grep ", "find ", "cat ", "docker ", "kubectl ",
        "npm ", "yarn ", "cargo ", "go ", "python ", "pip ", "conda ",
        "show me", "what is", "list ", "check ", "status", "analyze file",
        "read file", "find file", "search for"
    ]
    
    prompt_lower = prompt.lower()
    return any(indicator in prompt_lower for indicator in command_indicators)