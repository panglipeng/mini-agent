import json
import shutil
import unittest
import uuid
from pathlib import Path

from mini_agent.agent import Agent
from mini_agent.contracts import ModelResponse
from mini_agent.fake_model import FakeModel as StarterFakeModel
from mini_agent.models import FakeModel
from mini_agent.tools import PermissionPolicy, WorkspaceGuard, default_tools
from mini_agent.types import AssistantReply, ToolCall


class RaisingModel:
    def complete(self, messages, tools):
        raise ConnectionError("offline")


class MalformedModel:
    def complete(self, messages, tools):
        return {"content": "not an AssistantReply"}


class GenerateOnlyModel:
    def generate(self, messages, tools):
        return ModelResponse("generated through starter interface")


class AgentLoopTests(unittest.TestCase):
    def setUp(self):
        self.workspace = (
            Path.cwd() / "workspace" / ".test-workspaces" / uuid.uuid4().hex
        )
        self.workspace.mkdir(parents=True)
        (self.workspace / "notes.txt").write_text(
            "An Agent Loop calls tools.\nOther material.\n", encoding="utf-8"
        )

    def tearDown(self):
        shutil.rmtree(self.workspace)

    def agent(self, model, *, max_steps=10, allow_writes=False):
        return Agent(
            model,
            default_tools(),
            WorkspaceGuard(self.workspace),
            permissions=PermissionPolicy(allow_writes=allow_writes),
            max_steps=max_steps,
        )

    def test_direct_answer_finishes_without_tool(self):
        model = FakeModel([AssistantReply("done")])
        result = self.agent(model).run("answer directly")
        self.assertEqual("completed", result.status)
        self.assertEqual("done", result.output)
        self.assertEqual(1, result.steps)

    def test_starter_compatibility_imports_and_generate_alias(self):
        model = StarterFakeModel([ModelResponse("compatible", [])])
        reply = model.generate([], [])
        self.assertEqual("compatible", reply.content)
        self.assertEqual([], reply.tool_calls)

    def test_agent_accepts_list_tool_calls_from_public_adapters(self):
        model = FakeModel(
            [
                ModelResponse(
                    tool_calls=[ToolCall("list-1", "list_files", {"path": "."})]
                ),
                ModelResponse("done"),
            ]
        )
        result = self.agent(model).run("list files")
        self.assertEqual("completed", result.status)

    def test_agent_accepts_generate_only_starter_model(self):
        result = self.agent(GenerateOnlyModel()).run("use starter model")
        self.assertEqual("completed", result.status)
        self.assertEqual("generated through starter interface", result.output)

    def test_tool_result_is_added_before_next_model_call(self):
        model = FakeModel(
            [
                AssistantReply(
                    tool_calls=(
                        ToolCall("search-1", "search_text", {"query": "Agent Loop"}),
                    )
                ),
                AssistantReply("summary"),
            ]
        )
        result = self.agent(model).run("find Agent Loop")
        self.assertEqual("completed", result.status)
        second_messages = model.requests[1][0]
        tool_message = second_messages[-1]
        self.assertEqual("tool", tool_message["role"])
        payload = json.loads(tool_message["content"])
        self.assertTrue(payload["ok"])
        self.assertEqual("notes.txt", payload["data"]["matches"][0]["path"])

    def test_unknown_tool_is_recoverable(self):
        model = FakeModel(
            [
                AssistantReply(tool_calls=(ToolCall("bad-1", "missing", {}),)),
                AssistantReply("recovered"),
            ]
        )
        result = self.agent(model).run("try a tool")
        self.assertEqual("completed", result.status)
        error_payload = json.loads(model.requests[1][0][-1]["content"])
        self.assertEqual("unknown_tool", error_payload["code"])

    def test_model_exception_returns_error_result(self):
        result = self.agent(RaisingModel()).run("work")
        self.assertEqual("model_error", result.status)
        self.assertIn("offline", result.output)

    def test_malformed_model_response_returns_error_result(self):
        result = self.agent(MalformedModel()).run("work")
        self.assertEqual("model_error", result.status)
        self.assertIn("AssistantReply", result.output)

    def test_step_limit_stops_repeated_calls(self):
        calls = [
            AssistantReply(tool_calls=(ToolCall(f"c-{index}", "list_files", {}),))
            for index in range(3)
        ]
        result = self.agent(FakeModel(calls), max_steps=2).run("loop forever")
        self.assertEqual("max_steps_exceeded", result.status)
        self.assertEqual(2, result.steps)

    def test_write_denial_is_a_tool_result(self):
        model = FakeModel(
            [
                AssistantReply(
                    tool_calls=(
                        ToolCall(
                            "write-1",
                            "write_file",
                            {"path": "report.md", "content": "hello"},
                        ),
                    )
                ),
                AssistantReply("write was denied"),
            ]
        )
        result = self.agent(model).run("write a report")
        self.assertEqual("completed", result.status)
        self.assertFalse((self.workspace / "report.md").exists())
        payload = json.loads(model.requests[1][0][-1]["content"])
        self.assertEqual("permission_denied", payload["code"])

    def test_approved_write_changes_workspace(self):
        model = FakeModel(
            [
                AssistantReply(
                    tool_calls=(
                        ToolCall(
                            "write-1",
                            "write_file",
                            {"path": "report.md", "content": "hello"},
                        ),
                    )
                ),
                AssistantReply("written"),
            ]
        )
        result = self.agent(model, allow_writes=True).run("write a report")
        self.assertEqual("completed", result.status)
        self.assertEqual("hello", (self.workspace / "report.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
