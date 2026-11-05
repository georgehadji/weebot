"""What an MCP server may ask of the client while a tool call is running (H12).

The SDK runs these callbacks in the session's own task, not the caller's, so the session and
taint of the tool call that triggered them do not travel by ``ContextVar``. The manager
records each in-flight call (:class:`CallContext`, from the port); a callback uses the newest one for its
server. With none, the server is asking outside a tool call and the request is denied.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from mcp.shared.context import RequestContext
from mcp.types import (
    CreateMessageRequestParams,
    CreateMessageResult,
    ElicitRequestParams,
    ElicitResult,
    ErrorData,
    TextContent,
)

from weebot.application.ports.mcp_elicitation_port import McpElicitationPort
from weebot.application.ports.mcp_sampling_port import CallContext, McpSamplingPort, SamplingRequest
from weebot.domain.models.mcp import MCPSamplingPolicy

logger = logging.getLogger(__name__)

SamplingCallback = Callable[
    [RequestContext, CreateMessageRequestParams], Awaitable[CreateMessageResult | ErrorData]
]


def _plain_messages(params: CreateMessageRequestParams) -> list[dict[str, str]]:
    """Text of each message; image and audio parts are dropped (the call is text only)."""
    out = []
    for message in params.messages:
        parts = message.content_as_list
        text = "\n".join(p.text for p in parts if isinstance(p, TextContent))
        if text:
            out.append({"role": message.role, "content": text})
    return out


def make_sampling_callback(
    server_name: str,
    policy: MCPSamplingPolicy,
    handler: McpSamplingPort,
    current_call: Callable[[], CallContext | None],
) -> SamplingCallback:
    async def callback(
        context: RequestContext, params: CreateMessageRequestParams
    ) -> CreateMessageResult | ErrorData:
        call = current_call()
        request = SamplingRequest(
            messages=_plain_messages(params),
            max_tokens=params.maxTokens,
            stop_sequences=params.stopSequences,
            system_prompt=params.systemPrompt,
            temperature=params.temperature,
        )
        result = await handler.handle_sampling(
            server_name,
            request,
            policy,
            session_id=call.session_id if call else "",
            tainted=call.tainted if call else False,
        )
        if result is None:
            return ErrorData(code=-1, message="Sampling request declined by the client")
        text = "\n".join(c.get("text", "") for c in result.content)
        return CreateMessageResult(
            role="assistant",
            content=TextContent(type="text", text=text),
            model=result.model,
            stopReason=result.stop_reason,
        )

    return callback


ElicitationCallback = Callable[
    [RequestContext, ElicitRequestParams], Awaitable[ElicitResult | ErrorData]
]


def make_elicitation_callback(
    server_name: str,
    broker: McpElicitationPort,
    current_call: Callable[[], CallContext | None],
) -> ElicitationCallback:
    async def callback(
        context: RequestContext, params: ElicitRequestParams
    ) -> ElicitResult | ErrorData:
        # Only the in-band form is supported; a URL request would send the person to a page.
        if getattr(params, "mode", "form") != "form":
            logger.info("elicitation from %s declined: %s mode", server_name, params.mode)
            return ElicitResult(action="decline")
        call = current_call()
        reply = await broker.elicit(
            server_name,
            params.message,
            dict(params.requestedSchema),
            session_id=call.session_id if call else "",
        )
        return ElicitResult(action=reply.action, content=reply.content)

    return callback
