"""Data exchanged by models, the agent loop, and tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence


Message = dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    """A single tool invocation requested by a model."""

    id: str
    name: str
    arguments: Any = field(default_factory=dict)


@dataclass(frozen=True)
class AssistantReply:
    """One model response, which may contain zero or more tool calls."""

    content: str = ""
    tool_calls: Sequence[ToolCall] = ()
