# Daniel Local Operations Assistant

This is a local MCP memory server for Codex. Codex is the first consumer; Bounty
Builder is the first project it indexes. Data stays in a local SQLite database.
Ollama embeddings provide semantic retrieval and answer caching; lexical retrieval
keeps the server useful when Ollama is unavailable.

## Windows setup

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
ollama pull embeddinggemma
```

Add the server to Codex's MCP configuration using the repository's absolute path:

```toml
[mcp_servers.local-operations-assistant]
command = "C:\\absolute\\path\\Bounty-builder-agent\\.venv\\Scripts\\python.exe"
args = ["-m", "local_assistant.server"]
cwd = "C:\\absolute\\path\\Bounty-builder-agent"
env = { LOCAL_ASSISTANT_DATA_DIR = "C:\\Users\\Daniel\\.local-operations-assistant" }
```

Restart Codex, call `memory_status`, then call `ingest_project` with the absolute
path to the Bounty Builder checkout. The tools never deploy, merge, submit work,
spend money, or weaken the existing approval gates.

## Exposed tools

- `memory_status` — memory/cache health and active embedding provider.
- `ingest_project` — index supported text and code files from an explicit path.
- `remember` — save a trusted decision or project note.
- `recall` — retrieve relevant evidence before work begins.
- `cache_lookup` — reuse a sufficiently similar verified answer.
- `cache_verified_answer` — store a completed answer and evidence.

Environment variables: `LOCAL_ASSISTANT_DATA_DIR`, `LOCAL_ASSISTANT_OLLAMA_URL`,
and `LOCAL_ASSISTANT_EMBED_MODEL`.
