"""Model abstraction and a deterministic model used by tests and demos."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Protocol, Sequence

from .types import AssistantReply, Message, ToolCall


class Model(Protocol):
    """Minimal interface required by :class:`mini_agent.agent.Agent`."""

    def complete(
        self, messages: Sequence[Message], tools: Sequence[dict[str, Any]]
    ) -> AssistantReply:
        """Return a response or one or more tool calls."""


class FakeModel:
    """Return a preset sequence of replies without requiring an API key.

    Copies of every request are stored in ``requests`` so tests can assert that
    tool results were sent back to the model.
    """

    def __init__(self, replies: Sequence[AssistantReply]) -> None:
        self._replies = list(replies)
        self._index = 0
        self.requests: list[tuple[list[Message], list[dict[str, Any]]]] = []

    def complete(
        self, messages: Sequence[Message], tools: Sequence[dict[str, Any]]
    ) -> AssistantReply:
        self.requests.append((copy.deepcopy(list(messages)), copy.deepcopy(list(tools))))
        if self._index >= len(self._replies):
            raise RuntimeError("FakeModel has no preset reply left")
        reply = self._replies[self._index]
        self._index += 1
        return reply

    def generate(
        self, messages: Sequence[Message], tools: Sequence[dict[str, Any]]
    ) -> AssistantReply:
        """Starter-compatible alias for :meth:`complete`."""

        return self.complete(messages, tools)

    @classmethod
    def from_json_file(cls, path: str | Path) -> "FakeModel":
        """Load replies from a JSON array.

        Each item supports ``content`` and ``tool_calls``. A tool call supports
        ``id``, ``name``, and ``arguments``. Arguments intentionally remain
        untyped here so the tool layer can exercise its own validation.
        """

        source = Path(path)
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Cannot load fake model script {source}: {exc}") from exc
        if not isinstance(payload, list):
            raise ValueError("Fake model script must be a JSON array")

        replies: list[AssistantReply] = []
        for reply_index, item in enumerate(payload):
            if not isinstance(item, dict):
                raise ValueError(f"Reply {reply_index} must be an object")
            content = item.get("content", "")
            calls_payload = item.get("tool_calls", [])
            if not isinstance(content, str) or not isinstance(calls_payload, list):
                raise ValueError(
                    f"Reply {reply_index} needs string content and array tool_calls"
                )
            calls: list[ToolCall] = []
            for call_index, call in enumerate(calls_payload):
                if not isinstance(call, dict):
                    raise ValueError(
                        f"Reply {reply_index} tool call {call_index} must be an object"
                    )
                name = call.get("name")
                if not isinstance(name, str) or not name:
                    raise ValueError(
                        f"Reply {reply_index} tool call {call_index} needs a name"
                    )
                call_id = call.get("id", f"call-{reply_index}-{call_index}")
                if not isinstance(call_id, str) or not call_id:
                    raise ValueError(
                        f"Reply {reply_index} tool call {call_index} has an invalid id"
                    )
                calls.append(ToolCall(call_id, name, call.get("arguments", {})))
            replies.append(AssistantReply(content, tuple(calls)))
        return cls(replies)
