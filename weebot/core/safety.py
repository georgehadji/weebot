"""Counterfactual Simulation and Safety mechanisms.

Decoupled from LangChain per ADR-009 (core = no I/O, no framework deps).
Uses LLMPort for all LLM interactions.
"""
from __future__ import annotations

from typing import Any, Dict

from weebot.application.ports.llm_port import LLMPort
from weebot.core.approval_policy import ExecApprovalPolicy


COUNTERFACTUAL_SIMULATION_PROMPT = """
You are a safety module performing Counterfactual Simulation.

Original Action: {action}
Context: {context}

Before executing this potentially destructive action, simulate:
1. What could go wrong?
2. What is the safest alternative approach (Plan B)?
3. Can we achieve the goal non-destructively?

Provide:
- risk_assessment: Brief risk analysis
- plan_b: Alternative safer approach
- confirmation_required: yes/no
- backup_suggestion: How to backup before proceeding
"""


class SafetyChecker:
    """Implements Counterfactual Simulation for critical operations.

    Requires an ``LLMPort`` instance (injected via DI container).
    """

    CRITICAL_KEYWORDS = ["delete", "remove", "format", "kill", "stop-process", "rm", "del"]

    def __init__(self, llm: LLMPort):
        self.llm = llm
        self.approval_policy = ExecApprovalPolicy()
    
    def is_critical_operation(self, action: str, tool: str) -> bool:
        """Determine if action requires Counterfactual Simulation."""
        if tool != "powershell_executor":
            return False
        
        action_lower = action.lower()
        return any(keyword in action_lower for keyword in self.CRITICAL_KEYWORDS)
    
    async def generate_plan_b(self, original_action: str, context: str) -> Dict[str, Any]:
        """
        Generate alternative plan before executing critical action.
        Counterfactual Simulation: "What if this goes wrong?"
        """
        prompt_text = COUNTERFACTUAL_SIMULATION_PROMPT.format(
            action=original_action,
            context=context,
        )
        messages = [{"role": "user", "content": prompt_text}]
        result = await self.llm.chat(messages=messages)

        approval = self.approval_policy.evaluate(original_action)
        return {
            "simulation_result": self._parse_safety_response(result.content),
            "original_action": original_action,
            "proceed": not approval.requires_confirmation,
            "undo_hint": approval.undo_hint,
        }
    
    def _parse_safety_response(self, content: str) -> Dict[str, str]:
        """Parse LLM response into structured format."""
        lines = content.strip().split('\n')
        result = {}
        
        for line in lines:
            if ':' in line:
                key, value = line.split(':', 1)
                result[key.strip().lower()] = value.strip()
        
        return result
