import json
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from mini_agent.openai_compatible import OpenAICompatibleModel, _load_config


class FakeCompletions:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return self.response


class FakeClient:
    def __init__(self, response):
        self.completions = FakeCompletions(response)
        self.chat = SimpleNamespace(completions=self.completions)


def api_response(content="", tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls or [])
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class OpenAICompatibleModelTests(unittest.TestCase):
    def test_direct_text_response(self):
        client = FakeClient(api_response("done"))
        model = OpenAICompatibleModel("test-model", client=client)

        reply = model.complete([{"role": "user", "content": "hello"}], [])

        self.assertEqual("done", reply.content)
        self.assertEqual((), reply.tool_calls)
        request = client.completions.requests[0]
        self.assertEqual("test-model", request["model"])
        self.assertNotIn("tools", request)

    def test_tool_schemas_and_calls_are_translated(self):
        call = SimpleNamespace(
            id="call-1",
            function=SimpleNamespace(
                name="read_file", arguments='{"path":"notes.txt"}'
            ),
        )
        client = FakeClient(api_response(tool_calls=[call]))
        model = OpenAICompatibleModel("test-model", client=client)
        messages = [
            {"role": "user", "content": "read notes"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "old-call",
                        "name": "list_files",
                        "arguments": {"path": "."},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "old-call",
                "name": "list_files",
                "content": '{"ok":true}',
            },
        ]
        tools = [
            {
                "name": "read_file",
                "description": "Read a file",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
                "read_only": True,
            }
        ]

        reply = model.complete(messages, tools)

        self.assertEqual("read_file", reply.tool_calls[0].name)
        self.assertEqual('{"path":"notes.txt"}', reply.tool_calls[0].arguments)
        request = client.completions.requests[0]
        self.assertEqual("auto", request["tool_choice"])
        self.assertEqual("function", request["tools"][0]["type"])
        self.assertNotIn("read_only", request["tools"][0]["function"])
        sent_call = request["messages"][1]["tool_calls"][0]
        self.assertEqual("list_files", sent_call["function"]["name"])
        self.assertEqual({"path": "."}, json.loads(sent_call["function"]["arguments"]))
        self.assertNotIn("name", request["messages"][2])

    def test_constructor_requires_model(self):
        with self.assertRaisesRegex(ValueError, "model name"):
            OpenAICompatibleModel("", client=FakeClient(api_response()))

    def test_loads_json_config_from_explicit_path(self):
        config_text = json.dumps(
            {
                "api_key": "test-key",
                "base_url": "https://example.test/v1",
                "model": "test-model",
                "timeout": 30,
            }
        )
        with patch.dict(os.environ, {"MINI_CONFIG": "my-config.json"}, clear=True):
            with patch.object(Path, "is_file", return_value=True):
                with patch.object(Path, "read_text", return_value=config_text):
                    config = _load_config()

        self.assertEqual("test-key", config["api_key"])
        self.assertEqual("test-model", config["model"])

    def test_rejects_invalid_json_config(self):
        with patch.dict(os.environ, {"MINI_CONFIG": "broken.json"}, clear=True):
            with patch.object(Path, "is_file", return_value=True):
                with patch.object(Path, "read_text", return_value="{broken"):
                    with self.assertRaisesRegex(ValueError, "配置文件格式错误"):
                        _load_config()


if __name__ == "__main__":
    unittest.main()
