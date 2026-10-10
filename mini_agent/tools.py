"""Workspace-scoped tools and their common registry."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable, Iterable, Mapping, Protocol


class WorkspaceViolation(ValueError):
    """Raised when a requested path is outside the configured workspace."""


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    data: Any = None
    error: str | None = None
    code: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"ok": self.ok}
        if self.data is not None:
            result["data"] = self.data
        if self.error is not None:
            result["error"] = self.error
        if self.code is not None:
            result["code"] = self.code
        return result


class WorkspaceGuard:
    """Resolve relative paths while preventing traversal and symlink escapes."""

    def __init__(self, root: str | Path) -> None:
        candidate = Path(root).resolve(strict=True)
        if not candidate.is_dir():
            raise ValueError(f"Workspace is not a directory: {candidate}")
        self.root = candidate

    def resolve(self, user_path: str, *, must_exist: bool = True) -> Path:
        if not isinstance(user_path, str) or not user_path.strip():
            raise WorkspaceViolation("path must be a non-empty relative path")

        # Check both path dialects so a Windows path is also rejected when the
        # project happens to be tested on POSIX, and vice versa.
        windows_path = PureWindowsPath(user_path)
        posix_path = PurePosixPath(user_path)
        if (
            windows_path.is_absolute()
            or bool(windows_path.drive)
            or posix_path.is_absolute()
        ):
            raise WorkspaceViolation("absolute paths are not allowed")

        normalized_parts = user_path.replace("\\", "/").split("/")
        if ".." in normalized_parts:
            raise WorkspaceViolation("parent path traversal ('..') is not allowed")

        candidate = (self.root / Path(*normalized_parts)).resolve(strict=False)
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise WorkspaceViolation("path resolves outside the workspace") from exc

        if must_exist and not candidate.exists():
            raise FileNotFoundError(f"Path does not exist in workspace: {user_path}")
        return candidate

    def relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix() or "."


Authorizer = Callable[[str, str], bool]


@dataclass
class PermissionPolicy:
    """Permission policy for state-changing tools.

    ``allow_writes`` is useful for a pre-approved automation run. Otherwise the
    optional callback can ask a human about each exact action and relative path.
    """

    allow_writes: bool = False
    confirm: Authorizer | None = None

    def authorize(self, action: str, relative_path: str) -> bool:
        if self.allow_writes:
            return True
        if self.confirm is None:
            return False
        try:
            return bool(self.confirm(action, relative_path))
        except (EOFError, KeyboardInterrupt):
            return False


@dataclass
class ToolContext:
    workspace: WorkspaceGuard
    permissions: PermissionPolicy = field(default_factory=PermissionPolicy)


class Tool(Protocol):
    name: str
    description: str
    parameters: dict[str, Any]
    read_only: bool

    def run(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        """Execute a validated-looking argument mapping and return a result."""


def _error(exc: Exception) -> ToolResult:
    if isinstance(exc, WorkspaceViolation):
        return ToolResult(False, error=str(exc), code="workspace_violation")
    if isinstance(exc, FileNotFoundError):
        return ToolResult(False, error=str(exc), code="not_found")
    if isinstance(exc, PermissionError):
        return ToolResult(False, error=str(exc), code="filesystem_permission_error")
    if isinstance(exc, (UnicodeError, OSError)):
        return ToolResult(False, error=str(exc), code="io_error")
    if isinstance(exc, (TypeError, ValueError)):
        return ToolResult(False, error=str(exc), code="invalid_arguments")
    return ToolResult(False, error=f"Unexpected tool failure: {exc}", code="tool_failure")


def _string(
    arguments: Mapping[str, Any], key: str, *, default: str | None = None
) -> str:
    value = arguments.get(key, default)
    if not isinstance(value, str) or not value:
        raise ValueError(f"'{key}' must be a non-empty string")
    return value


def _boolean(arguments: Mapping[str, Any], key: str, *, default: bool) -> bool:
    value = arguments.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"'{key}' must be a boolean")
    return value


def _bounded_integer(
    arguments: Mapping[str, Any], key: str, *, default: int, minimum: int, maximum: int
) -> int:
    value = arguments.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"'{key}' must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"'{key}' must be between {minimum} and {maximum}")
    return value


def _iter_files(directory: Path) -> Iterable[Path]:
    """Walk without following directory or file symlinks."""

    for current, directories, files in os.walk(directory, followlinks=False):
        current_path = Path(current)
        directories[:] = sorted(
            name
            for name in directories
            if not (current_path / name).is_symlink()
        )
        for name in sorted(files):
            candidate = current_path / name
            if not candidate.is_symlink():
                yield candidate


def _iter_entries(directory: Path, *, recursive: bool) -> Iterable[Path]:
    """Yield sorted directory entries and never descend through a symlink."""

    pending = [directory]
    while pending:
        current = pending.pop()
        children = sorted(current.iterdir(), key=lambda item: item.name.lower())
        child_directories: list[Path] = []
        for child in children:
            yield child
            if recursive and child.is_dir() and not child.is_symlink():
                child_directories.append(child)
        pending.extend(reversed(child_directories))


class ListFilesTool:
    name = "list_files"
    description = "List files and directories inside the workspace without following symlinks."
    read_only = True
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative directory path."},
            "recursive": {"type": "boolean", "default": False},
            "max_entries": {"type": "integer", "minimum": 1, "maximum": 1000},
        },
        "additionalProperties": False,
    }

    def run(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        try:
            relative = _string(arguments, "path", default=".")
            recursive = _boolean(arguments, "recursive", default=False)
            maximum = _bounded_integer(
                arguments, "max_entries", default=200, minimum=1, maximum=1000
            )
            target = context.workspace.resolve(relative)
            if not target.is_dir():
                raise ValueError("'path' must identify a directory")

            entries: list[dict[str, str]] = []
            truncated = False
            for entry in _iter_entries(target, recursive=recursive):
                if len(entries) >= maximum:
                    truncated = True
                    break
                if entry.is_symlink():
                    entry_type = "symlink"
                elif entry.is_dir():
                    entry_type = "directory"
                elif entry.is_file():
                    entry_type = "file"
                else:
                    entry_type = "other"
                entries.append(
                    {"path": context.workspace.relative(entry), "type": entry_type}
                )
            return ToolResult(True, {"entries": entries, "truncated": truncated})
        except Exception as exc:  # Tool errors are data for the next model turn.
            return _error(exc)


class ReadFileTool:
    name = "read_file"
    description = "Read a UTF-8 text file inside the workspace."
    read_only = True
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative file path."},
            "max_chars": {
                "type": "integer",
                "minimum": 1,
                "maximum": 1_000_000,
            },
        },
        "required": ["path"],
        "additionalProperties": False,
    }

    def run(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        try:
            relative = _string(arguments, "path")
            maximum = _bounded_integer(
                arguments, "max_chars", default=100_000, minimum=1, maximum=1_000_000
            )
            target = context.workspace.resolve(relative)
            if not target.is_file():
                raise ValueError("'path' must identify a regular file")
            raw = target.read_bytes()
            if b"\x00" in raw[:8192]:
                raise ValueError("binary files cannot be read by this tool")
            content = raw.decode("utf-8")
            truncated = len(content) > maximum
            return ToolResult(
                True,
                {
                    "path": context.workspace.relative(target),
                    "content": content[:maximum],
                    "truncated": truncated,
                },
            )
        except Exception as exc:
            return _error(exc)


class SearchTextTool:
    name = "search_text"
    description = "Search UTF-8 text files in the workspace and return matching lines."
    read_only = True
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "path": {"type": "string", "description": "Relative file or directory."},
            "regex": {"type": "boolean", "default": False},
            "case_sensitive": {"type": "boolean", "default": False},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 200},
        },
        "required": ["query"],
        "additionalProperties": False,
    }

    def run(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        try:
            query = _string(arguments, "query")
            relative = _string(arguments, "path", default=".")
            use_regex = _boolean(arguments, "regex", default=False)
            case_sensitive = _boolean(arguments, "case_sensitive", default=False)
            maximum = _bounded_integer(
                arguments, "max_results", default=50, minimum=1, maximum=200
            )
            target = context.workspace.resolve(relative)
            flags = 0 if case_sensitive else re.IGNORECASE
            pattern = re.compile(query if use_regex else re.escape(query), flags)

            if target.is_file():
                candidates: Iterable[Path] = (target,)
            elif target.is_dir():
                candidates = _iter_files(target)
            else:
                raise ValueError("'path' must identify a regular file or directory")

            matches: list[dict[str, Any]] = []
            skipped_files = 0
            truncated = False
            for file_path in candidates:
                try:
                    if file_path.stat().st_size > 2_000_000:
                        skipped_files += 1
                        continue
                    raw = file_path.read_bytes()
                    if b"\x00" in raw[:8192]:
                        skipped_files += 1
                        continue
                    text = raw.decode("utf-8")
                except (OSError, UnicodeError):
                    skipped_files += 1
                    continue
                for line_number, line in enumerate(text.splitlines(), start=1):
                    if pattern.search(line):
                        matches.append(
                            {
                                "path": context.workspace.relative(file_path),
                                "line": line_number,
                                "text": line[:500],
                            }
                        )
                        if len(matches) >= maximum:
                            truncated = True
                            break
                if truncated:
                    break
            return ToolResult(
                True,
                {
                    "matches": matches,
                    "truncated": truncated,
                    "skipped_files": skipped_files,
                },
            )
        except re.error as exc:
            return ToolResult(False, error=f"Invalid regular expression: {exc}", code="invalid_arguments")
        except Exception as exc:
            return _error(exc)


class WriteFileTool:
    name = "write_file"
    description = "Create, overwrite, or append to a UTF-8 file after write authorization."
    read_only = False
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative file path."},
            "content": {"type": "string"},
            "mode": {"type": "string", "enum": ["create", "overwrite", "append"]},
            "create_parents": {"type": "boolean", "default": False},
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    }

    def run(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        try:
            relative = _string(arguments, "path")
            content = arguments.get("content")
            if not isinstance(content, str):
                raise ValueError("'content' must be a string")
            mode = _string(arguments, "mode", default="create")
            if mode not in {"create", "overwrite", "append"}:
                raise ValueError("'mode' must be create, overwrite, or append")
            create_parents = _boolean(arguments, "create_parents", default=False)
            target = context.workspace.resolve(relative, must_exist=False)
            if target.exists() and not target.is_file():
                raise ValueError("'path' must identify a regular file")
            if mode == "create" and target.exists():
                return ToolResult(
                    False,
                    error="File already exists; use overwrite or append explicitly",
                    code="already_exists",
                )

            action = f"{mode} UTF-8 file"
            safe_relative = context.workspace.relative(target)
            if not context.permissions.authorize(action, safe_relative):
                return ToolResult(
                    False,
                    error=f"Permission denied for {action}: {safe_relative}",
                    code="permission_denied",
                )

            if create_parents:
                target.parent.mkdir(parents=True, exist_ok=True)
            elif not target.parent.exists():
                raise FileNotFoundError(
                    "Parent directory does not exist; set create_parents to true"
                )
            file_mode = "a" if mode == "append" else ("x" if mode == "create" else "w")
            with target.open(file_mode, encoding="utf-8", newline="") as stream:
                written = stream.write(content)
            return ToolResult(
                True,
                {"path": safe_relative, "characters_written": written, "mode": mode},
            )
        except Exception as exc:
            return _error(exc)


class ToolRegistry:
    """Register tools and convert all invocation failures into tool results."""

    def __init__(self, tools: Iterable[Tool] = ()) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        if not tool.name or tool.name in self._tools:
            raise ValueError(f"Invalid or duplicate tool name: {tool.name!r}")
        self._tools[tool.name] = tool

    def specifications(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
                "read_only": tool.read_only,
            }
            for tool in self._tools.values()
        ]

    def execute(self, name: str, arguments: Any, context: ToolContext) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(False, error=f"Unknown tool: {name}", code="unknown_tool")

        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError as exc:
                return ToolResult(
                    False,
                    error=f"Tool arguments are not valid JSON: {exc}",
                    code="invalid_arguments",
                )
        if not isinstance(arguments, dict):
            return ToolResult(
                False, error="Tool arguments must be an object", code="invalid_arguments"
            )
        properties = tool.parameters.get("properties", {})
        if isinstance(properties, dict):
            unexpected = sorted(set(arguments) - set(properties))
            if unexpected:
                return ToolResult(
                    False,
                    error=f"Unknown tool argument(s): {', '.join(unexpected)}",
                    code="invalid_arguments",
                )
        required = tool.parameters.get("required", [])
        if isinstance(required, list):
            missing = [key for key in required if key not in arguments]
            if missing:
                return ToolResult(
                    False,
                    error=f"Missing required argument(s): {', '.join(missing)}",
                    code="invalid_arguments",
                )
        try:
            return tool.run(arguments, context)
        except Exception as exc:  # A third-party tool must not crash the loop.
            return _error(exc)


def default_tools() -> ToolRegistry:
    return ToolRegistry(
        [ListFilesTool(), ReadFileTool(), SearchTextTool(), WriteFileTool()]
    )
