"""Counterfactual Simulation and Safety mechanisms."""
from typing import Dict, Any, Optional
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from weebot.core.approval_policy import ExecApprovalPolicy


class SafetyChecker:
    """Implements Counterfactual Simulation for critical operations."""

    CRITICAL_KEYWORDS = ["delete", "remove", "format", "kill", "stop-process", "rm", "del"]

    def __init__(self):
        self.llm = ChatOpenAI(temperature=0)
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
        prompt = PromptTemplate(
            template="""
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
            """,
            input_variables=["action", "context"]
        )
        
        chain = prompt | self.llm
        result = await chain.ainvoke({
            "action": original_action,
            "context": context
        })
        
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
