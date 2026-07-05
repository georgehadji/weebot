"""Composite tool specifications for the Weebot MCP server.

Composite tools expose common multi-step workflows as single MCP tools,
reducing the reasoning burden on external LLM clients.  The underlying atomic
tools remain available for internal use and can be re-exposed by setting
``mcp_composite_tools_enabled=false``.
"""
from __future__ import annotations

from weebot.domain.models.composite_tool import CompositeToolSpec, SubToolCall


DEFAULT_COMPOSITE_TOOLS: list[CompositeToolSpec] = [
    CompositeToolSpec(
        name="analyze_and_edit",
        description=(
            "Analyze a file, run a syntax check, and apply a targeted edit. "
            "Use this when the user asks to fix a bug or refactor a specific file. "
            "Arguments: path (str), old_str (str), new_str (str)."
        ),
        sub_tools=[
            SubToolCall(
                tool_name="file_view",
                arguments={"path": "${path}"},
                capture_output_as="file_content",
                description="Read the target file",
            ),
            SubToolCall(
                tool_name="python_execute",
                arguments={
                    "code": "import py_compile; py_compile.compile('${path}', doraise=True)"
                },
                description="Validate syntax with py_compile",
            ),
            SubToolCall(
                tool_name="file_str_replace",
                arguments={
                    "path": "${path}",
                    "old_str": "${old_str}",
                    "new_str": "${new_str}",
                },
                description="Apply the requested edit",
            ),
        ],
        hidden_atomic_tools=["file_editor"],
        transaction_policy="best_effort",
    ),
    CompositeToolSpec(
        name="research_and_summarize",
        description=(
            "Search the web and return a concise summary. "
            "Use this when the user asks to research a topic. "
            "Arguments: query (str)."
        ),
        sub_tools=[
            SubToolCall(
                tool_name="web_search",
                arguments={"query": "${query}"},
                capture_output_as="search_results",
                description="Search the web",
            ),
            SubToolCall(
                tool_name="python_execute",
                arguments={
                    "code": (
                        "import sys; "
                        "results = '''${search_results}'''; "
                        "print('Summary of', len(results.splitlines()), 'lines')"
                    ),
                },
                capture_output_as="summary",
                description="Process search results",
            ),
        ],
        hidden_atomic_tools=["web_search"],
        transaction_policy="best_effort",
    ),
]
