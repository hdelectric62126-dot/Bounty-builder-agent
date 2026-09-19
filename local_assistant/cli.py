"""Command bridge for agents that have shell access but no dynamic MCP mounting."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from local_assistant.memory import LocalMemory


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="local-assistant")
    parser.add_argument("--data-dir", default=os.getenv("LOCAL_ASSISTANT_DATA_DIR", ".data/local-assistant"))
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("status")
    ingest = commands.add_parser("ingest")
    ingest.add_argument("root")

    context = commands.add_parser("context")
    context.add_argument("query")
    context.add_argument("--limit", type=int, default=6)

    remember = commands.add_parser("remember")
    remember.add_argument("source")
    remember.add_argument("text")

    decision = commands.add_parser("decision")
    decision.add_argument("title")
    decision.add_argument("decision")
    decision.add_argument("--evidence", action="append", default=[])
    decision.add_argument("--status", choices=("active", "tentative", "superseded"), default="active")

    cache = commands.add_parser("cache")
    cache.add_argument("question")
    cache.add_argument("answer")
    cache.add_argument("--evidence", action="append", default=[])
    return parser


def execute(args: argparse.Namespace, memory: LocalMemory) -> dict:
    if args.command == "status":
        return memory.status()
    if args.command == "ingest":
        return memory.ingest_directory(args.root)
    if args.command == "context":
        return memory.context_bundle(args.query, args.limit)
    if args.command == "remember":
        return memory.remember(args.source, args.text)
    if args.command == "decision":
        return memory.record_decision(args.title, args.decision, args.evidence, args.status)
    if args.command == "cache":
        return memory.cache_answer(args.question, args.answer, args.evidence)
    raise ValueError(f"unsupported command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    data_dir = Path(args.data_dir).resolve()
    result = execute(args, LocalMemory(data_dir / "memory.db"))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
