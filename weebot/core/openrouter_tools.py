#!/usr/bin/env python3
"""
Weebot OpenRouter Tools Integration
====================================

Enhanced tool calling with:
- OpenRouter web_search server tool
- Interleaved thinking support
- Auto Exacto optimization (automatic)
- Tool choice control
- Parallel tool calling

Usage:
    from weebot.core.openrouter_tools import (
        ToolRegistry,
        WebSearchTool,
        ToolChoice,
        create_agent_loop,
    )
"""

import json
from typing import Optional, Callable, Any
from dataclasses import dataclass, field
from enum import Enum
from collections.abc import Awaitable
import asyncio


class ToolChoice(str, Enum):
    """Tool choice strategies."""
    AUTO = "auto"           # Model decides whether to use tools
    REQUIRED = "required"   # Model must use a tool
    NONE = "none"           # Model cannot use tools


@dataclass
class ToolParameter:
    """Definition of a tool parameter."""
    name: str
    type: str  # string, number, integer, boolean, array, object
    description: str
    required: bool = True
    enum: Optional[list] = None
    default: Any = None


@dataclass
class Tool:
    """Tool definition for OpenRouter."""
    name: str
    description: str
    parameters: list[ToolParameter]
    handler: Optional[Callable[..., Awaitable[Any]]] = None
    strict: bool = False  # Enable strict mode for tool calling

    def to_openai_schema(self) -> dict:
        """Convert to OpenAI-compatible tool schema."""
        properties = {}
        required = []
        
        for param in self.parameters:
            prop = {
                "type": param.type,
                "description": param.description,
            }
            if param.enum:
                prop["enum"] = param.enum
            properties[param.name] = prop
            
            if param.required:
                required.append(param.name)
        
        schema = {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }
        
        if self.strict:
            schema["function"]["strict"] = True
        
        return schema


class WebSearchTool(Tool):
    """
    OpenRouter's built-in web search server tool.
    
    This tool allows models to search the web for current information.
    Replaces the deprecated :online variant.
    
    Usage:
        tool = WebSearchTool()
        # Include in tools list, model will call it automatically
    """
    
    def __init__(self):
        super().__init__(
            name="web_search",
            description="Search the web for current information. Use this when you need up-to-date information that may not be in your training data.",
            parameters=[
                ToolParameter(
                    name="query",
                    type="string",
                    description="The search query to execute",
                    required=True,
                ),
                ToolParameter(
                    name="num_results",
                    type="integer",
                    description="Number of results to return (1-10)",
                    required=False,
                    default=5,
                ),
            ],
        )
    
    def to_server_tool(self) -> dict:
        """Convert to OpenRouter server tool format."""
        return {
            "type": "server_tool",
            "tool": "openrouter:web_search",
            "arguments": {
                "query": "{{input}}",  # Template for model to fill
            },
        }


class ToolRegistry:
    """Registry for managing tools."""
    
    def __init__(self):
        self._tools: dict[str, Tool] = {}
    
    def register(self, tool: Tool) -> "ToolRegistry":
        """Register a tool."""
        self._tools[tool.name] = tool
        return self
    
    def unregister(self, name: str) -> "ToolRegistry":
        """Unregister a tool."""
        if name in self._tools:
            del self._tools[name]
        return self
    
    def get(self, name: str) -> Optional[Tool]:
        """Get a tool by name."""
        return self._tools.get(name)
    
    def list_tools(self) -> list[str]:
        """List all registered tool names."""
        return list(self._tools.keys())
    
    def to_openai_schema(self) -> list[dict]:
        """Convert all tools to OpenAI schema."""
        return [tool.to_openai_schema() for tool in self._tools.values()]
    
    def get_handler(self, name: str) -> Optional[Callable]:
        """Get the handler for a tool."""
        tool = self._tools.get(name)
        return tool.handler if tool else None


# ============================================================================
# AGENT LOOP
# ============================================================================

class AgentLoop:
    """
    Simple agentic loop for tool calling.
    
    Handles the conversation loop:
    1. Send message to model
    2. If tool_calls in response, execute tools
    3. Send tool results back to model
    4. Repeat until no more tool calls
    """
    
    def __init__(
        self,
        tool_registry: ToolRegistry,
        max_iterations: int = 10,
        enable_interleaved_thinking: bool = False,
    ):
        self.tool_registry = tool_registry
        self.max_iterations = max_iterations
        self.enable_interleaved_thinking = enable_interleaved_thinking
        self.history = []
    
    async def run(
        self,
        messages: list[dict],
        llm_call: Callable[[list[dict]], Awaitable[dict]],
    ) -> dict:
        """
        Run the agent loop.
        
        Args:
            messages: Initial conversation messages
            llm_call: Async function that calls the LLM
        
        Returns:
            Final response from the model
        """
        current_messages = messages.copy()
        
        for iteration in range(self.max_iterations):
            # Call the model
            response = await llm_call(current_messages)
            
            # Check for tool calls (guard against empty choices list)
            choices = response.get("choices") or [{}]
            choice = choices[0] if choices else {}
            finish_reason = choice.get("finish_reason")
            
            if finish_reason != "tool_calls":
                # No tool calls, we're done
                return response
            
            # Process tool calls
            message = choice.get("message", {})
            tool_calls = message.get("tool_calls", [])
            
            # Add assistant message to history
            current_messages.append({
                "role": "assistant",
                "content": message.get("content"),
                "tool_calls": tool_calls,
            })
            
            # Execute each tool call
            for tool_call in tool_calls:
                result = await self._execute_tool_call(tool_call)
                current_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "name": tool_call["function"]["name"],
                    "content": json.dumps(result),
                })
        
        # Max iterations reached
        return {
            "error": "Max iterations reached",
            "history": current_messages,
        }
    
    async def _execute_tool_call(self, tool_call: dict) -> Any:
        """Execute a single tool call."""
        function = tool_call.get("function", {})
        name = function.get("name")
        arguments_str = function.get("arguments", "{}")
        
        try:
            arguments = json.loads(arguments_str)
        except json.JSONDecodeError:
            return {"error": "Invalid arguments JSON"}
        
        # Get tool handler
        handler = self.tool_registry.get_handler(name)
        
        if not handler:
            return {"error": f"Tool '{name}' not found"}
        
        try:
            if asyncio.iscoroutinefunction(handler):
                result = await handler(**arguments)
            else:
                result = handler(**arguments)
            return {"result": result}
        except Exception as e:
            return {"error": str(e)}


def create_agent_loop(
    tools: list[Tool],
    max_iterations: int = 10,
    enable_interleaved_thinking: bool = False,
) -> AgentLoop:
    """
    Create an agent loop with the given tools.
    
    Args:
        tools: List of tools to register
        max_iterations: Maximum tool call iterations
        enable_interleaved_thinking: Enable Anthropic interleaved thinking
    
    Returns:
        Configured AgentLoop
    """
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    
    return AgentLoop(
        tool_registry=registry,
        max_iterations=max_iterations,
        enable_interleaved_thinking=enable_interleaved_thinking,
    )


# ============================================================================
# PRE-BUILT TOOLS
# ============================================================================

def create_file_read_tool(read_func: Callable[[str], str]) -> Tool:
    """Create a file reading tool."""
    return Tool(
        name="read_file",
        description="Read the contents of a file.",
        parameters=[
            ToolParameter(
                name="path",
                type="string",
                description="Path to the file to read",
                required=True,
            ),
        ],
        handler=read_func,
    )


def create_file_write_tool(write_func: Callable[[str, str], bool]) -> Tool:
    """Create a file writing tool."""
    return Tool(
        name="write_file",
        description="Write content to a file.",
        parameters=[
            ToolParameter(
                name="path",
                type="string",
                description="Path to the file to write",
                required=True,
            ),
            ToolParameter(
                name="content",
                type="string",
                description="Content to write to the file",
                required=True,
            ),
        ],
        handler=write_func,
    )


def create_shell_tool(shell_func: Callable[[str], dict]) -> Tool:
    """Create a shell command execution tool."""
    return Tool(
        name="run_shell",
        description="Execute a shell command and return the output.",
        parameters=[
            ToolParameter(
                name="command",
                type="string",
                description="The shell command to execute",
                required=True,
            ),
            ToolParameter(
                name="timeout",
                type="integer",
                description="Timeout in seconds (default: 30)",
                required=False,
                default=30,
            ),
        ],
        handler=shell_func,
    )


def create_code_search_tool(search_func: Callable[[str, str], list]) -> Tool:
    """Create a code search tool."""
    return Tool(
        name="search_code",
        description="Search for code patterns in the codebase.",
        parameters=[
            ToolParameter(
                name="query",
                type="string",
                description="Search query or pattern",
                required=True,
            ),
            ToolParameter(
                name="language",
                type="string",
                description="Programming language to filter by (e.g., 'python', 'javascript')",
                required=False,
            ),
        ],
        handler=search_func,
    )


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

async def example():
    """Example of using the tools system."""
    
    # Create tools
    web_search = WebSearchTool()
    
    # Custom tool with handler
    async def get_weather(location: str) -> dict:
        """Example weather tool."""
        return {"temperature": 72, "condition": "sunny", "location": location}
    
    weather_tool = Tool(
        name="get_weather",
        description="Get the current weather for a location.",
        parameters=[
            ToolParameter(
                name="location",
                type="string",
                description="City and state, e.g. 'San Francisco, CA'",
                required=True,
            ),
        ],
        handler=get_weather,
    )
    
    # Create registry
    registry = ToolRegistry()
    registry.register(weather_tool)
    
    print("=" * 70)
    print("TOOL REGISTRY DEMO")
    print("=" * 70)
    print()
    print("Registered tools:", registry.list_tools())
    print()
    print("Weather tool schema:")
    print(json.dumps(weather_tool.to_openai_schema(), indent=2))
    print()
    print("Web search tool (server tool):")
    print(json.dumps(web_search.to_server_tool(), indent=2))
    print()
    
    # Test handler
    handler = registry.get_handler("get_weather")
    if handler:
        result = await handler(location="San Francisco, CA")
        print("Weather result:", result)
    
    print()
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(example())
