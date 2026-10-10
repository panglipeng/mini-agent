"""OpenAI-compatible Chat Completions adapter.

The adapter translates the project's vendor-neutral messages and tool schemas
to the Chat Completions function-calling format.  It works with OpenAI and
other providers that expose a compatible ``/chat/completions`` endpoint.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .types import AssistantReply, Message, ToolCall


class OpenAICompatibleModel:
    """Use an OpenAI-compatible API as the reasoning model."""

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 60.0,
        client: Any = None,
    ) -> None:
        if not isinstance(model, str) or not model.strip():
            raise ValueError("A non-empty model name is required")
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")

        self.model = model.strip()
        if client is not None:
            self.client = client
            return

        if not api_key:
            raise ValueError(
                "API key is required; set MINI_API_KEY or OPENAI_API_KEY"
            )
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "The 'openai' package is required; run: python -m pip install -e ."
            ) from exc

        options: dict[str, Any] = {"api_key": api_key, "timeout": timeout}
        if base_url:
            options["base_url"] = base_url.rstrip("/")
        self.client = OpenAI(**options)

    def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]],
    ) -> AssistantReply:
        api_messages = [_message_for_api(message) for message in messages]
        api_tools = [_tool_for_api(tool) for tool in tools]

        request: dict[str, Any] = {
            "model": self.model,
            "messages": api_messages,
        }
        if api_tools:
            request["tools"] = api_tools
            request["tool_choice"] = "auto"

        response = self.client.chat.completions.create(**request)
        try:
            message = response.choices[0].message
        except (AttributeError, IndexError, TypeError) as exc:
            raise ValueError("API returned an invalid Chat Completions response") from exc

        calls: list[ToolCall] = []
        for call in message.tool_calls or []:
            function = getattr(call, "function", None)
            if function is None:
                raise ValueError("API returned a non-function tool call")
            arguments = function.arguments or "{}"
            calls.append(ToolCall(call.id, function.name, arguments))

        content = message.content or ""
        if not isinstance(content, str):
            raise ValueError("API returned non-text message content")
        return AssistantReply(content, tuple(calls))


def create_model() -> OpenAICompatibleModel:
    """Factory used by ``mini --model-factory`` and ``MINI_MODEL_FACTORY``."""

    config = _load_config()
    api_key = (
        os.getenv("MINI_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or config.get("api_key")
    )
    base_url = (
        os.getenv("MINI_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
        or config.get("base_url")
    )
    model = (
        os.getenv("MINI_MODEL")
        or os.getenv("OPENAI_MODEL")
        or config.get("model")
    )
    if not model:
        raise ValueError("请在 config.json 中填写 model（模型名称）")
    if not api_key:
        raise ValueError("请在 config.json 中填写 api_key")
    if _looks_like_placeholder(str(api_key)) or _looks_like_placeholder(str(model)):
        raise ValueError("请先打开项目根目录的 config.json，填写 api_key 和 model")

    raw_timeout = os.getenv("MINI_API_TIMEOUT") or config.get("timeout", 60)
    try:
        timeout = float(raw_timeout)
    except (TypeError, ValueError) as exc:
        raise ValueError("config.json 中的 timeout 必须是数字") from exc
    return OpenAICompatibleModel(
        str(model),
        api_key=str(api_key),
        base_url=str(base_url) if base_url else None,
        timeout=timeout,
    )


def _load_config() -> dict[str, Any]:
    """Load the first available local configuration file.

    ``MINI_CONFIG`` can point to another file. Otherwise a config in the
    current directory is preferred, followed by the project-root config.
    Environment variables are applied later and therefore override the file.
    """

    configured_path = os.getenv("MINI_CONFIG")
    if configured_path:
        candidates = [Path(configured_path).expanduser()]
    else:
        candidates = [
            Path.cwd() / "config.json",
            Path(__file__).resolve().parent.parent / "config.json",
        ]

    for path in candidates:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"配置文件格式错误：{path}（{exc.msg}）") from exc
        except OSError as exc:
            raise ValueError(f"无法读取配置文件：{path}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"配置文件必须是 JSON 对象：{path}")
        return data
    return {}


def _looks_like_placeholder(value: str) -> bool:
    normalized = value.strip().lower()
    return not normalized or "在这里" in normalized or normalized.startswith("your_")


def _tool_for_api(tool: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool.get("parameters", {"type": "object"}),
        },
    }


def _message_for_api(message: Mapping[str, Any]) -> dict[str, Any]:
    role = message.get("role")
    content = message.get("content", "")

    if role == "assistant":
        result: dict[str, Any] = {"role": "assistant", "content": content}
        calls = message.get("tool_calls")
        if calls:
            result["tool_calls"] = [
                {
                    "id": call["id"],
                    "type": "function",
                    "function": {
                        "name": call["name"],
                        "arguments": _arguments_json(call.get("arguments", {})),
                    },
                }
                for call in calls
            ]
        return result

    if role == "tool":
        return {
            "role": "tool",
            "tool_call_id": message["tool_call_id"],
            "content": str(content),
        }

    if role not in {"system", "developer", "user"}:
        raise ValueError(f"Unsupported message role: {role!r}")
    return {"role": role, "content": content}


def _arguments_json(arguments: Any) -> str:
    if isinstance(arguments, str):
        return arguments
    return json.dumps(arguments, ensure_ascii=False)
