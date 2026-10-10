"""The model/tool agent loop."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from .models import Model
from .tools import PermissionPolicy, ToolContext, ToolRegistry, WorkspaceGuard
from .types import AssistantReply, Message, ToolCall


DEFAULT_SYSTEM_PROMPT = """You are a workspace agent. Use the supplied tools when needed.
All paths must be relative to the workspace. Read-only tools may run immediately.
Write tools can be denied by the user; if so, adjust your plan or explain the denial.
Treat tool errors as recoverable observations and never invent a successful result."""


@dataclass(frozen=True)
class AgentResult:
    status: Literal["completed", "model_error", "max_steps_exceeded"]
    output: str
    steps: int
    messages: tuple[Message, ...]
    error: str | None = None


class Agent:
    """Run a model until it answers without requesting another tool."""

    def __init__(
        self,
        model: Model,
        tools: ToolRegistry,
        workspace: WorkspaceGuard,
        *,
        permissions: PermissionPolicy | None = None,
        max_steps: int = 10,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        self.model = model
        self.tools = tools
        self.context = ToolContext(workspace, permissions or PermissionPolicy())
        self.max_steps = max_steps
        self.system_prompt = system_prompt

    def _request_model(
        self, messages: list[Message], specifications: list[dict]
    ) -> AssistantReply:
        """Call either the native or starter-compatible model method."""

        complete = getattr(self.model, "complete", None)
        if callable(complete):
            return complete(messages, specifications)
        generate = getattr(self.model, "generate", None)
        if callable(generate):
            return generate(messages, specifications)
        raise TypeError("Model must provide complete() or generate()")

    def run(self, request: str) -> AgentResult:
        if not isinstance(request, str) or not request.strip():
            raise ValueError("request must be a non-empty string")
        messages: list[Message] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": request},
        ]
        specifications = self.tools.specifications()

        for step in range(1, self.max_steps + 1):
            try:
                reply = self._request_model(messages, specifications)
                if not isinstance(reply, AssistantReply):
                    raise TypeError("Model.complete() must return AssistantReply")
                if not isinstance(reply.content, str):
                    raise TypeError("AssistantReply.content must be a string")
                if not isinstance(reply.tool_calls, (list, tuple)):
                    raise TypeError("AssistantReply.tool_calls must be a list or tuple")
                for call in reply.tool_calls:
                    if not isinstance(call, ToolCall):
                        raise TypeError("Every tool call must be a ToolCall")
                    if not isinstance(call.id, str) or not call.id:
                        raise TypeError("Every tool call must have a non-empty string id")
                    if not isinstance(call.name, str) or not call.name:
                        raise TypeError("Every tool call must have a non-empty string name")
            except Exception as exc:
                error = f"Model request failed: {exc}"
                return AgentResult(
                    "model_error", error, step, tuple(messages), error=error
                )

            assistant_message: Message = {
                "role": "assistant",
                "content": reply.content,
            }
            if reply.tool_calls:
                assistant_message["tool_calls"] = [
                    {"id": call.id, "name": call.name, "arguments": call.arguments}
                    for call in reply.tool_calls
                ]
            messages.append(assistant_message)

            if not reply.tool_calls:
                return AgentResult("completed", reply.content, step, tuple(messages))

            for call in reply.tool_calls:
                result = self.tools.execute(call.name, call.arguments, self.context)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": call.name,
                        "content": json.dumps(result.as_dict(), ensure_ascii=False),
                    }
                )

        error = f"Maximum execution steps exceeded ({self.max_steps})"
        messages.append({"role": "system", "content": error})
        return AgentResult(
            "max_steps_exceeded",
            error,
            self.max_steps,
            tuple(messages),
            error=error,
        )
