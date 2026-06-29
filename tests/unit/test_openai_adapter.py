"""Tests for OpenAIAdapter and thinking mode normalization."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from weebot.infrastructure.adapters.llm.openai_adapter import OpenAIAdapter


@pytest.mark.asyncio
async def test_openai_adapter_strips_thinking_suffix():
    # Arrange
    adapter = OpenAIAdapter(api_key="sk-or-v1-testkey", default_model="z-ai/glm-5.2:thinking")
    
    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "Answer content"
    mock_choice.message.tool_calls = None
    mock_response.choices = [mock_choice]
    mock_response.model = "z-ai/glm-5.2"
    mock_response.usage = None
    
    # Mock AsyncOpenAI create call
    with patch.object(adapter._client.chat.completions, "create", new_callable=AsyncMock) as mock_create:
        mock_create.return_value = mock_response
        
        # Act
        response = await adapter.chat(
            messages=[{"role": "user", "content": "Explain quantum computing."}]
        )
        
        # Assert
        assert response.content == "Answer content"
        mock_create.assert_called_once()
        called_kwargs = mock_create.call_args[1]
        
        # Suffix must be stripped
        assert called_kwargs["model"] == "z-ai/glm-5.2"
        # Deep thinking must be enabled
        assert called_kwargs["extra_body"]["thinking"] == {"type": "enabled"}
        # Default reasoning_effort must be 'max'
        assert called_kwargs["reasoning_effort"] == "max"


@pytest.mark.asyncio
async def test_openai_adapter_disables_thinking_for_short_tokens():
    # Arrange
    adapter = OpenAIAdapter(api_key="sk-or-v1-testkey", default_model="z-ai/glm-5.2")
    
    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "Short answer"
    mock_choice.message.tool_calls = None
    mock_response.choices = [mock_choice]
    mock_response.model = "z-ai/glm-5.2"
    mock_response.usage = None
    
    with patch.object(adapter._client.chat.completions, "create", new_callable=AsyncMock) as mock_create:
        mock_create.return_value = mock_response
        
        # Act (max_tokens=100 is short, under 500 threshold)
        response = await adapter.chat(
            messages=[{"role": "user", "content": "Short question"}],
            max_tokens=100
        )
        
        # Assert
        assert response.content == "Short answer"
        mock_create.assert_called_once()
        called_kwargs = mock_create.call_args[1]
        
        # Chat template kwargs should ask to disable thinking to avoid truncation
        assert called_kwargs["extra_body"]["chat_template_kwargs"] == {"enable_thinking": False}


@pytest.mark.asyncio
async def test_openai_adapter_grok_parameter_cleaning():
    # Arrange
    adapter = OpenAIAdapter(api_key="sk-or-v1-testkey", default_model="x-ai/grok-4.3")
    
    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "Grok response"
    mock_choice.message.tool_calls = None
    mock_response.choices = [mock_choice]
    mock_response.model = "x-ai/grok-4.3"
    mock_response.usage = None
    
    with patch.object(adapter._client.chat.completions, "create", new_callable=AsyncMock) as mock_create:
        mock_create.return_value = mock_response
        
        # Act
        # Pass incompatible parameters (presence_penalty, frequency_penalty, stop)
        response = await adapter.chat(
            messages=[{"role": "user", "content": "Tell me about Grok 4.3"}],
            reasoning_effort="high"
        )
        
        # Assert
        called_kwargs = mock_create.call_args[1]
        
        # Verify incompatible params are stripped
        assert "presence_penalty" not in called_kwargs
        assert "frequency_penalty" not in called_kwargs
        assert "stop" not in called_kwargs
        
        # Verify reasoning effort is translated to x.AI's 'reasoning' body structure
        assert called_kwargs["extra_body"]["reasoning"] == {"effort": "high"}


@pytest.mark.asyncio
async def test_openai_adapter_grok_multi_agent_cleaning():
    # Arrange
    adapter = OpenAIAdapter(api_key="sk-or-v1-testkey", default_model="x-ai/grok-4.20-multi-agent")
    
    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "Multi-agent coordinated result"
    mock_choice.message.tool_calls = None
    mock_response.choices = [mock_choice]
    mock_response.model = "x-ai/grok-4.20-multi-agent"
    mock_response.usage = None
    
    with patch.object(adapter._client.chat.completions, "create", new_callable=AsyncMock) as mock_create:
        mock_create.return_value = mock_response
        
        # Act
        response = await adapter.chat(
            messages=[{"role": "user", "content": "Coordinate multi-agent task"}],
            reasoning_effort="max",
            max_tokens=2048
        )
        
        # Assert
        called_kwargs = mock_create.call_args[1]
        
        # Verify max_tokens is popped
        assert "max_tokens" not in called_kwargs
        
        # Verify max maps to xhigh for multi-agent
        assert called_kwargs["extra_body"]["reasoning"] == {"effort": "xhigh"}

