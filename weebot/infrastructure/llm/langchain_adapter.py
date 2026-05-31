"""LangChain-compatible wrapper for LLMPort."""
from __future__ import annotations

from typing import Any, List, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_core.outputs import ChatGeneration, ChatResult


class LLMPortLangChainAdapter(BaseChatModel):
    """Wrap Weebot's LLMPort for use with LangChain tools like browser-use.

    This allows browser-use (which expects LangChain models) to work with
    Weebot's LLMPort abstraction, enabling model selection/routing.

    Example:
        from weebot.infrastructure.adapters.llm.openai_adapter import OpenAIAdapter
        llm_port = OpenAIAdapter()  # Or any LLMPort implementation
        langchain_llm = LLMPortLangChainAdapter(llm_port, model="gpt-4")

        agent = BrowserAgent(task="...", llm=langchain_llm)
    """

    llm_port: Any  # LLMPort - using Any to avoid pydantic validation issues
    model: Optional[str] = None
    temperature: float = 0.0
    max_tokens: Optional[int] = None

    @property
    def _llm_type(self) -> str:
        return "weebot-llm-port"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "temperature": self.temperature,
        }

    def _convert_messages(self, messages: List[BaseMessage]) -> list[dict[str, Any]]:
        """Convert LangChain messages to LLMPort format."""
        converted = []
        for msg in messages:
            if isinstance(msg, SystemMessage):
                converted.append({"role": "system", "content": msg.content})
            elif isinstance(msg, HumanMessage):
                converted.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                converted.append({"role": "assistant", "content": msg.content})
            else:
                converted.append({"role": "user", "content": str(msg.content)})
        return converted

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Synchronous generation (not recommended - use async)."""
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            response = loop.run_until_complete(self._agenerate(messages, stop, run_manager, **kwargs))
            return response
        except RuntimeError:
            raise RuntimeError("LLMPortLangChainAdapter._generate cannot be used without an event loop; use async methods instead.")

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Async generation using LLMPort."""
        converted_messages = self._convert_messages(messages)

        response = await self.llm_port.chat(
            messages=converted_messages,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )

        message = AIMessage(content=response.content)
        generation = ChatGeneration(message=message)
        return ChatResult(generations=[generation])
