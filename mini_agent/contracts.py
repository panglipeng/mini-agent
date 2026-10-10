"""Stable contracts exposed for starter and public-test compatibility.

The implementation is split across focused modules, but consumers can keep
using the conventional ``mini_agent.contracts`` import path supplied by the
assignment starter.
"""

from .models import Model
from .tools import Tool, ToolResult
from .types import AssistantReply, Message, ToolCall

# ``ModelResponse`` is the name commonly used by the starter.  Keep it as an
# alias so existing tests and adapters do not need to know the internal name.
ModelResponse = AssistantReply

__all__ = [
    "AssistantReply",
    "Message",
    "Model",
    "ModelResponse",
    "Tool",
    "ToolCall",
    "ToolResult",
]
