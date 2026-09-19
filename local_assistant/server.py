"""MCP entry point used by Codex as Daniel's local operations assistant."""

import os
from pathlib import Path

from mcp.server import MCPServer

from local_assistant.memory import LocalMemory

DATA_DIR = Path(os.getenv("LOCAL_ASSISTANT_DATA_DIR", Path.home() / ".local-operations-assistant"))
memory = LocalMemory(DATA_DIR / "memory.db")
mcp = MCPServer("Daniel Local Operations Assistant")


@mcp.tool()
def memory_status() -> dict:
    """Report local memory, semantic cache, and embedding-provider status."""
    return memory.status()


@mcp.tool()
def ingest_project(root: str) -> dict:
    """Incrementally sync safe text/code files and remove deleted-file memory."""
    return memory.ingest_directory(root)


@mcp.tool()
def remember(source: str, text: str) -> dict:
    """Store trusted project notes or decisions in local durable memory."""
    return memory.remember(source, text)


@mcp.tool()
def recall(query: str, limit: int = 6) -> list[dict]:
    """Retrieve the most relevant local project evidence for a task."""
    return memory.search(query, limit)


@mcp.tool()
def cache_lookup(question: str, threshold: float = 0.84) -> dict:
    """Reuse a previously verified answer only when semantic similarity clears the threshold."""
    return memory.lookup_answer(question, threshold)


@mcp.tool()
def cache_verified_answer(question: str, answer: str, evidence: list[str] | None = None) -> dict:
    """Cache a completed answer with its evidence after verification."""
    return memory.cache_answer(question, answer, evidence)


@mcp.tool()
def get_task_context(query: str, limit: int = 6, cache_threshold: float = 0.84) -> dict:
    """Return verified cache state, relevant evidence, and memory health in one call."""
    return memory.context_bundle(query, limit, cache_threshold)


@mcp.tool()
def record_decision(title: str, decision: str, evidence: list[str] | None = None,
                    status: str = "active") -> dict:
    """Persist an explicit project decision with evidence and lifecycle status."""
    return memory.record_decision(title, decision, evidence, status)


if __name__ == "__main__":
    mcp.run(transport="stdio")
