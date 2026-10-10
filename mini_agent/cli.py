"""Command-line interface for the Mini Agent."""

from __future__ import annotations

import argparse
import importlib
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .agent import Agent
from .models import FakeModel, Model
from .tools import PermissionPolicy, WorkspaceGuard, default_tools


def _confirmation(action: str, relative_path: str) -> bool:
    answer = input(f"Allow agent to {action} at '{relative_path}'? [y/N] ")
    return answer.strip().lower() in {"y", "yes"}


def _load_factory(specification: str) -> Callable[[], Model]:
    if ":" not in specification:
        raise ValueError("Model factory must use module:callable syntax")
    module_name, attribute_name = specification.split(":", 1)
    module = importlib.import_module(module_name)
    factory: Any = getattr(module, attribute_name)
    if not callable(factory):
        raise ValueError(f"Model factory is not callable: {specification}")
    return factory


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mini-agent",
        description="Run a model/tool loop against a restricted workspace.",
    )
    parser.add_argument("request", nargs="*", help="Task text; omit to enter interactive mode.")
    parser.add_argument("--workspace", default="workspace", help="Existing workspace directory.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--script", help="JSON reply script for the built-in FakeModel.")
    source.add_argument(
        "--model-factory",
        help="External zero-argument model factory in module:callable form.",
    )
    parser.add_argument("--max-steps", type=int, default=10)
    parser.add_argument(
        "--approve-writes",
        action="store_true",
        help="Pre-authorize all workspace writes for this run.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        guard = WorkspaceGuard(Path(args.workspace))
        if args.script:
            model_factory: Callable[[], Model] = lambda: FakeModel.from_json_file(args.script)
        else:
            model_factory = _load_factory(args.model_factory)
        if args.max_steps < 1:
            raise ValueError("--max-steps must be at least 1")
    except (OSError, ImportError, AttributeError, ValueError) as exc:
        parser.error(str(exc))

    permissions = PermissionPolicy(
        allow_writes=args.approve_writes,
        confirm=None if args.approve_writes else _confirmation,
    )

    def execute(request: str) -> int:
        try:
            model = model_factory()
            agent = Agent(
                model,
                default_tools(),
                guard,
                permissions=permissions,
                max_steps=args.max_steps,
            )
            result = agent.run(request)
        except Exception as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(result.output)
        return 0 if result.status == "completed" else 1

    request = " ".join(args.request).strip()
    if request:
        return execute(request)

    print("Mini Agent interactive mode. Type 'exit' or press Ctrl-D to stop.")
    while True:
        try:
            request = input("mini-agent> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if request.lower() in {"exit", "quit"}:
            return 0
        if request:
            execute(request)


if __name__ == "__main__":
    raise SystemExit(main())
