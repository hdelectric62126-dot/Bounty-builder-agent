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
    """Index safe text/code files beneath one explicit local project directory."""
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


if __name__ == "__main__":
    mcp.run(transport="stdio")
