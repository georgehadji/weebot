"""Recursive Agent implementing Observe-Evaluate-Act-Refine loop."""
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import SystemMessage, HumanMessage

from weebot.tools.powershell_tool import PowerShellTool
from weebot.tools.browser_tool import BrowserTool
from weebot.tools.heuristic_router import HeuristicRouter
from weebot.core.safety import SafetyChecker

MAX_RETRIES = 3


@dataclass
class ExecutionStep:
    step_number: int
    action: str
    tool_used: str
    result: str
    error: Optional[str] = None
    refinement_applied: bool = False
    timestamp: datetime = field(default_factory=datetime.now)


class RecursiveWeebotAgent:
    """
    Implements the OEAR (Observe-Evaluate-Act-Refine) loop.
    """
    
    def __init__(self):
        self.llm = ChatOpenAI(model="gpt-4", temperature=0.2)
        self.heuristic_router = HeuristicRouter()
        self.safety_checker = SafetyChecker()
        self.history: List[ExecutionStep] = []
        
        # Tools
        self.ps_tool = PowerShellTool()
        self.browser_tool = BrowserTool()
        self.tools = [self.ps_tool, self.browser_tool]
        
        # Create agent with tools
        self.agent = self._create_agent()
    
    def _create_agent(self):
        """Create prompt template for the OEAR agent."""
        system_prompt = (
            "You are weebot, an autonomous AI agent for Windows 11. "
            "Use powershell_executor for local operations and browser_navigator for web tasks. "
            "Follow OEAR: Observe, Evaluate, Act, Refine (retry with modifications on error)."
        )
        return ChatPromptTemplate.from_messages([
            SystemMessage(content=system_prompt),
            MessagesPlaceholder(variable_name="chat_history", optional=True),
            HumanMessage(content="{input}"),
        ])
    
    async def execute_task(self, task: str, max_retries: int = MAX_RETRIES) -> Dict[str, Any]:
        """
        Execute task with OEAR loop and recursive refinement.
        """
        step_number = len(self.history) + 1
        
        # OBSERVE & EVALUATE: Heuristic analysis
        routing = self.heuristic_router.analyze_task(task)
        
        for attempt in range(max_retries):
            try:
                # Determine which tool to use
                primary_tool = routing["primary_tool"]
                
                # SAFETY: Check for critical operations
                if self.safety_checker.is_critical_operation(task, primary_tool):
                    safety_result = await self.safety_checker.generate_plan_b(
                        task, f"Attempt {attempt + 1}"
                    )
                    if safety_result.get("confirmation_required") == "yes":
                        return {
                            "status": "requires_confirmation",
                            "safety_analysis": safety_result,
                            "action": task
                        }
                
                # ACT: Execute
                if primary_tool == "powershell":
                    result = self.ps_tool._run(task)
                    tool_used = "powershell"
                else:
                    result = self.browser_tool._run(task)
                    tool_used = "browser"
                
                # Check for errors
                if "Error:" in result:
                    raise Exception(result)
                
                # Record success
                step = ExecutionStep(
                    step_number=step_number,
                    action=task,
                    tool_used=tool_used,
                    result=result,
                    error=None,
                    refinement_applied=(attempt > 0)
                )
                self.history.append(step)
                
                return {
                    "status": "success",
                    "result": result,
                    "tool_used": tool_used,
                    "attempts": attempt + 1
                }
                
            except Exception as e:
                error_msg = str(e)
                
                # Record failure
                step = ExecutionStep(
                    step_number=step_number,
                    action=task,
                    tool_used=primary_tool if 'primary_tool' in locals() else "unknown",
                    result="",
                    error=error_msg,
                    refinement_applied=(attempt > 0)
                )
                self.history.append(step)
                
                # REFINE: Try alternative if available
                if attempt < max_retries - 1:
                    routing["primary_tool"] = routing["suggested_sequence"][1]
                    continue
                else:
                    return {
                        "status": "failed",
                        "error": error_msg,
                        "attempts": attempt + 1
                    }
        
        return {"status": "failed", "error": "Max retries exceeded"}
    
    def get_history(self) -> List[ExecutionStep]:
        """Return execution history."""
        return self.history
    
    def clear_history(self):
        """Clear execution history."""
        self.history = []
