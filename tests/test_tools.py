import shutil
import unittest
import uuid
from pathlib import Path

from mini_agent.tools import (
    PermissionPolicy,
    ToolContext,
    WorkspaceGuard,
    default_tools,
)


class ToolSafetyTests(unittest.TestCase):
    def setUp(self):
        self.workspace = (
            Path.cwd() / "workspace" / ".test-workspaces" / uuid.uuid4().hex
        )
        self.workspace.mkdir(parents=True)
        self.guard = WorkspaceGuard(self.workspace)
        self.registry = default_tools()
        self.context = ToolContext(self.guard, PermissionPolicy(allow_writes=True))
        (self.workspace / "a.txt").write_text("Alpha\nbeta Agent Loop\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.workspace)

    def test_absolute_path_is_rejected(self):
        result = self.registry.execute(
            "read_file", {"path": str((self.workspace / "a.txt").resolve())}, self.context
        )
        self.assertFalse(result.ok)
        self.assertEqual("workspace_violation", result.code)

    def test_parent_traversal_is_rejected(self):
        result = self.registry.execute(
            "read_file", {"path": "../outside.txt"}, self.context
        )
        self.assertFalse(result.ok)
        self.assertEqual("workspace_violation", result.code)

    def test_bad_argument_type_is_returned_not_raised(self):
        result = self.registry.execute("read_file", {"path": 42}, self.context)
        self.assertFalse(result.ok)
        self.assertEqual("invalid_arguments", result.code)

    def test_unknown_argument_is_rejected(self):
        result = self.registry.execute(
            "read_file", {"path": "a.txt", "surprise": True}, self.context
        )
        self.assertFalse(result.ok)
        self.assertEqual("invalid_arguments", result.code)

    def test_json_string_arguments_are_supported(self):
        result = self.registry.execute("read_file", '{"path":"a.txt"}', self.context)
        self.assertTrue(result.ok)
        self.assertIn("Agent Loop", result.data["content"])

    def test_search_is_case_insensitive_by_default(self):
        result = self.registry.execute(
            "search_text", {"query": "agent loop"}, self.context
        )
        self.assertTrue(result.ok)
        self.assertEqual(2, result.data["matches"][0]["line"])

    def test_create_does_not_silently_overwrite(self):
        result = self.registry.execute(
            "write_file", {"path": "a.txt", "content": "new"}, self.context
        )
        self.assertFalse(result.ok)
        self.assertEqual("already_exists", result.code)
        self.assertIn("Alpha", (self.workspace / "a.txt").read_text(encoding="utf-8"))

    def test_invalid_regex_is_reported(self):
        result = self.registry.execute(
            "search_text", {"query": "[", "regex": True}, self.context
        )
        self.assertFalse(result.ok)
        self.assertEqual("invalid_arguments", result.code)


if __name__ == "__main__":
    unittest.main()
