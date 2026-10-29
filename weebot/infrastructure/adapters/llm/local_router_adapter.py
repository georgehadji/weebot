"""Sends ``ollama/<tag>`` ids to Ollama and ``free/<provider>/<model>`` ids to that free tier.

Everything else goes on as before.

The executor cascade calls one shared adapter with a different ``model=`` per attempt
(``_cascade.py``), and that adapter's base URL is fixed. Without this layer an ``ollama/...``
id would be sent to OpenRouter. The local adapter is built on first use, so a process that
never routes locally never builds it; the factory caches one free adapter per model id.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from weebot.application.ports.llm_port import LLMPort, LLMResponse
from weebot.config.free_models import FREE_PREFIX

OLLAMA_PREFIX = "ollama/"


class LocalModelRouter(LLMPort):
    # Read by unwrap_llm so isinstance checks on the concrete adapter still see through.
    _llm_wrapper = True

    def __init__(
        self,
        default: LLMPort,
        local_factory: Callable[[], LLMPort] | None = None,
        *,
        free_factory: Callable[[str], LLMPort] | None = None,
    ) -> None:
        self._default = default
        self._local_factory = local_factory
        self._free_factory = free_factory
        self._local: LLMPort | None = None

    @property
    def inner(self) -> LLMPort:
        return self._default

    def _local_adapter(self) -> LLMPort:
        if self._local is None:
            self._local = self._local_factory()  # type: ignore[misc]  # checked by chat()
        return self._local

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = "auto",
        response_format: dict[str, Any] | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        if model and model.startswith(OLLAMA_PREFIX) and self._local_factory is not None:
            target = self._local_adapter()
            model = model[len(OLLAMA_PREFIX) :]  # Ollama knows `qwen3:8b`, not `ollama/qwen3:8b`
        elif model and model.startswith(FREE_PREFIX) and self._free_factory is not None:
            target = self._free_factory(model)
            model = model[len(FREE_PREFIX) :].partition("/")[2]  # the provider's own model id
        else:
            target = self._default
        return await target.chat(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            response_format=response_format,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def build_multimodal_message(
        self, role: str, text: str, image_base64: str, media_type: str = "image/png"
    ) -> dict[str, Any]:
        return await self._default.build_multimodal_message(role, text, image_base64, media_type)

    def __getattr__(self, name: str) -> Any:
        # Adapter-specific surface (metrics, circuit state, stream) of the default adapter.
        if name.startswith("__") or name in (
            "_default", "_local_factory", "_free_factory", "_local"
        ):
            raise AttributeError(name)
        return getattr(self._default, name)
