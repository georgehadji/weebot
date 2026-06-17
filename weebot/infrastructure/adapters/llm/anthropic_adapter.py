"""Anthropic LLM adapter implementing LLMPort."""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from anthropic import AsyncAnthropic

from weebot.application.ports.llm_port import LLMPort, LLMResponse
from weebot.config.model_refs import MODEL_FACTORY_ANTHROPIC
from weebot.infrastructure.adapters.llm._multimodal import convert_messages


class AnthropicAdapter(LLMPort):
    """Adapter for Anthropic Claude API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        default_model: str = MODEL_FACTORY_ANTHROPIC,
    ):
        key = api_key or os.getenv("ANTHROPIC_API_KEY") or "no-key"
        self._client = AsyncAnthropic(api_key=key)
        self._default_model = default_model

    @staticmethod
    def _convert_tools(tools: Optional[List[Dict[str, Any]]]) -> Optional[List[Dict[str, Any]]]:
        """Convert OpenAI-format tools to Anthropic format."""
        if not tools:
            return None
        anthropic_tools = []
        for tool in tools:
            func = tool.get("function", {})
            anthropic_tools.append({
                "name": func.get("name", ""),
                "description": func.get("description", ""),
                "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
            })
        return anthropic_tools

    @staticmethod
    def _convert_tool_choice(tool_choice: Optional[str]) -> Optional[Dict[str, str]]:
        """Convert OpenAI tool_choice string to Anthropic format."""
        if tool_choice is None or tool_choice == "auto":
            return {"type": "auto"}
        if tool_choice == "none":
            return {"type": "none"}
        if tool_choice == "required":
            return {"type": "any"}
        # Assume specific tool name
        return {"type": "tool", "name": tool_choice}

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = "auto",
        response_format: Optional[Dict[str, Any]] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        kwargs: Dict[str, Any] = {
            "model": model or self._default_model,
            "max_tokens": max_tokens or 4096,
            "messages": convert_messages(messages, "anthropic"),
        }

        anthropic_tools = self._convert_tools(tools)
        if anthropic_tools:
            kwargs["tools"] = anthropic_tools
            kwargs["tool_choice"] = self._convert_tool_choice(tool_choice)

        if temperature is not None:
            kwargs["temperature"] = temperature

        response = await self._client.messages.create(**kwargs)

        content = ""
        tool_calls = None
        
        # Handle cases where response.content is None or empty
        if not response.content:
            raise RuntimeError("LLM returned empty response (no content)")
        
        for block in response.content:
            if block.type == "text":
                content += block.text
            elif block.type == "tool_use":
                if tool_calls is None:
                    tool_calls = []
                tool_calls.append({
                    "id": block.id,
                    "type": "function",
                    "function": {
                        "name": block.name,
                        "arguments": str(block.input),
                    },
                })

        usage = None
        if getattr(response, "usage", None):
            usage = {
                "prompt_tokens": response.usage.input_tokens,
                "completion_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
            }

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            model=response.model or (model or self._default_model),
            usage=usage,
        )
