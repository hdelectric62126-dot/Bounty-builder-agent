# Daniel Local Operations Assistant

This is a local MCP memory server for Codex. Codex is the first consumer; Bounty
Builder is the first project it indexes. Data stays in a local SQLite database.
Ollama embeddings provide semantic retrieval and answer caching; lexical retrieval
keeps the server useful when Ollama is unavailable.

## Windows one-click setup

1. Install Python 3.11 or newer, Ollama, and the Codex CLI if they are not already installed.
2. Open the Bounty Builder repository folder.
3. Double-click `install_local_assistant.cmd`.
4. When it reports success, completely restart ChatGPT or Codex and open a new session.
5. Call `memory_status`, then call `ingest_project` with the absolute path to the
   Bounty Builder checkout.

The installer creates a private Python environment, installs the required packages,
downloads the local embedding model, registers the MCP server, and verifies that
Codex lists it. It uses its own repository location, so no path editing or command
typing is required.

## Manual Windows setup

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

Project ingestion is incremental: unchanged files are not embedded again, changed
files are refreshed, and deleted files are removed from memory. This keeps answers
current while reducing repeated local work.

## Exposed tools

- `memory_status` — memory/cache health and active embedding provider.
- `ingest_project` — incrementally synchronize supported files from an explicit path.
- `remember` — save a trusted decision or project note.
- `recall` — retrieve relevant evidence before work begins.
- `cache_lookup` — reuse a sufficiently similar verified answer.
- `cache_verified_answer` — store a completed answer and evidence.
- `get_task_context` — retrieve cache state, supporting evidence, and memory health
  with one request before starting work.
- `record_decision` — persist an active, tentative, or superseded decision with its
  evidence so later sessions do not silently reverse it.

Environment variables: `LOCAL_ASSISTANT_DATA_DIR`, `LOCAL_ASSISTANT_OLLAMA_URL`,
and `LOCAL_ASSISTANT_EMBED_MODEL`.

## Shell-agent bridge

Agents running in a workspace that cannot dynamically mount a new MCP server can
still use the same memory immediately:

```bash
python -m local_assistant.cli ingest .
python -m local_assistant.cli context "current task"
python -m local_assistant.cli decision "Decision title" "Decision text" --evidence source
```

The bridge writes to `.data/local-assistant/memory.db` by default. That directory
is ignored by Git and never becomes part of a commit.
