"""The executor's prompt, split by how long each part stays the same (H10).

A provider's prompt cache matches a request prefix byte for byte, in the order tools,
system, messages. The executor used to put per-step text (retrieved skills, behavioural
rules, the tool note) inside the system prompt and send the step's tools in dict order, so
the prefix changed at every step and nothing could be reused.

`PromptLayout` fixes the order: what is stable for a session goes first, what changes per
step goes into the step's first user message. `prefix_sha` is the hash of everything that
must not change for the cache to hold, so a test or a metric can compare two requests.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any


def canonical_tools(tools: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Tools sorted by name, with every dict's keys sorted: the same bytes for the same set."""
    ordered = sorted(tools, key=lambda t: t.get("function", {}).get("name", ""))
    return [json.loads(json.dumps(t, sort_keys=True)) for t in ordered]


def tools_sha(tools: Iterable[dict[str, Any]]) -> str:
    return _sha(_tools_json(tools))


def system_sha(system: str) -> str:
    return _sha(system)


def _tools_json(tools: Iterable[dict[str, Any]]) -> str:
    return json.dumps(canonical_tools(tools), sort_keys=True, separators=(",", ":"))


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class PromptLayout:
    system_static: str
    """Boot block, base prompt, harness, personality: the same for the whole session."""
    system_session: str
    """User profile and the frozen memory snapshot (H24a): fixed when the session starts."""
    step_context: str
    """Retrieved skills, behavioural rules, output root, tool note: sent as a user message."""
    prefix_sha: str
    """sha256 over the system text and the canonical tools: what the cache needs to hold."""

    @property
    def system(self) -> str:
        return self.system_static + self.system_session


class PromptLayoutBuilder:
    """Collects the three parts, then freezes them with the tools that go with them."""

    def __init__(self) -> None:
        self._static = ""
        self._session = ""
        self._step = ""

    def static(self, text: str) -> PromptLayoutBuilder:
        self._static = text
        return self

    def session(self, text: str) -> PromptLayoutBuilder:
        self._session = text
        return self

    def step(self, text: str) -> PromptLayoutBuilder:
        self._step = text
        return self

    def build(self, tools: Iterable[dict[str, Any]]) -> PromptLayout:
        sha = _sha(self._static + self._session + _tools_json(tools))
        return PromptLayout(self._static, self._session, self._step, sha)
