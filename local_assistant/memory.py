"""Local-first project memory with optional Ollama embeddings."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

TOKEN = re.compile(r"[a-z0-9_]{2,}")
TEXT_SUFFIXES = {".md", ".txt", ".py", ".js", ".mjs", ".ts", ".tsx", ".json", ".toml", ".yaml", ".yml"}
SKIP_PARTS = {".git", ".venv", "venv", "node_modules", "dist", "build", "__pycache__", ".data"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    norm = math.sqrt(sum(a * a for a in left) * sum(b * b for b in right))
    return dot / norm if norm else 0.0


def _lexical(left: str, right: str) -> float:
    a, b = set(TOKEN.findall(left.casefold())), set(TOKEN.findall(right.casefold()))
    return len(a & b) / len(a | b) if a and b else 0.0


@dataclass(frozen=True)
class EmbeddingResult:
    vector: list[float]
    provider: str


class OllamaEmbedder:
    def __init__(self, url: str | None = None, model: str | None = None, timeout: float = 8):
        self.url = (url or os.getenv("LOCAL_ASSISTANT_OLLAMA_URL", "http://127.0.0.1:11434")).rstrip("/")
        self.model = model or os.getenv("LOCAL_ASSISTANT_EMBED_MODEL", "embeddinggemma")
        self.timeout = timeout

    def embed(self, text: str) -> EmbeddingResult:
        body = json.dumps({"model": self.model, "input": text}).encode()
        request = Request(f"{self.url}/api/embed", data=body, headers={"Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.load(response)
            vector = payload.get("embeddings", [[]])[0]
            if vector:
                return EmbeddingResult([float(item) for item in vector], f"ollama:{self.model}")
        except (OSError, ValueError, KeyError, IndexError):
            pass
        return EmbeddingResult([], "lexical-fallback")


class LocalMemory:
    def __init__(self, path: str | Path, embedder: OllamaEmbedder | None = None):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.embedder = embedder or OllamaEmbedder()
        with self._connect() as db:
            db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS documents (
              id INTEGER PRIMARY KEY, source TEXT NOT NULL, chunk_index INTEGER NOT NULL,
              content TEXT NOT NULL, content_hash TEXT NOT NULL, embedding TEXT,
              embedding_provider TEXT NOT NULL, updated_at TEXT NOT NULL,
              UNIQUE(source, chunk_index)
            );
            CREATE TABLE IF NOT EXISTS answer_cache (
              id INTEGER PRIMARY KEY, question TEXT NOT NULL, answer TEXT NOT NULL,
              evidence TEXT NOT NULL, question_embedding TEXT, embedding_provider TEXT NOT NULL,
              created_at TEXT NOT NULL, last_used_at TEXT NOT NULL, hits INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_documents_source ON documents(source);
            CREATE TABLE IF NOT EXISTS project_files (
              root TEXT NOT NULL, source TEXT NOT NULL, content_hash TEXT NOT NULL,
              updated_at TEXT NOT NULL, PRIMARY KEY(root, source)
            );
            """)
            cache_columns = {row[1] for row in db.execute("PRAGMA table_info(answer_cache)")}
            if "evidence_state" not in cache_columns:
                db.execute("ALTER TABLE answer_cache ADD COLUMN evidence_state TEXT NOT NULL DEFAULT '[]'")

    def _connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=5000")
        return db

    @staticmethod
    def _chunks(text: str, size: int = 2400, overlap: int = 240):
        text = text.strip()
        if not text:
            return []
        return [text[start:start + size] for start in range(0, len(text), size - overlap)]

    def remember(self, source: str, text: str) -> dict:
        chunks = self._chunks(text)
        with self._connect() as db:
            db.execute("DELETE FROM documents WHERE source=?", (source,))
            for index, chunk in enumerate(chunks):
                embedded = self.embedder.embed(chunk)
                db.execute("""INSERT INTO documents
                    (source,chunk_index,content,content_hash,embedding,embedding_provider,updated_at)
                    VALUES(?,?,?,?,?,?,?)""", (source, index, chunk,
                    hashlib.sha256(chunk.encode()).hexdigest(), json.dumps(embedded.vector),
                    embedded.provider, _now()))
        return {"source": source, "chunks": len(chunks)}

    def ingest_directory(self, root: str | Path, max_file_bytes: int = 1_000_000) -> dict:
        root = Path(root).resolve()
        if not root.is_dir():
            raise ValueError("root must be an existing directory")
        root_key = str(root)
        root_fingerprint = hashlib.sha256(root_key.encode()).hexdigest()[:10]
        prefix = f"{root.name or 'project'}@{root_fingerprint}"
        files = chunks = skipped = unchanged = 0
        discovered: set[str] = set()
        with self._connect() as db:
            known = {row["source"]: row["content_hash"] for row in db.execute(
                "SELECT source, content_hash FROM project_files WHERE root=?", (root_key,)
            )}
        for path in sorted(root.rglob("*")):
            if (path.is_symlink() or not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES
                    or any(part in SKIP_PARTS for part in path.parts)):
                continue
            if path.stat().st_size > max_file_bytes:
                skipped += 1
                continue
            try:
                relative = path.relative_to(root).as_posix()
                source = f"{prefix}/{relative}"
                text = path.read_text(encoding="utf-8")
                content_hash = hashlib.sha256(text.encode()).hexdigest()
                discovered.add(source)
                if known.get(source) == content_hash:
                    files += 1
                    unchanged += 1
                    continue
                result = self.remember(source, text)
                with self._connect() as db:
                    db.execute("""INSERT INTO project_files(root,source,content_hash,updated_at)
                        VALUES(?,?,?,?) ON CONFLICT(root,source) DO UPDATE SET
                        content_hash=excluded.content_hash, updated_at=excluded.updated_at""",
                        (root_key, source, content_hash, _now()))
                files += 1
                chunks += result["chunks"]
            except UnicodeDecodeError:
                skipped += 1
        stale = set(known) - discovered
        if stale:
            with self._connect() as db:
                db.executemany("DELETE FROM documents WHERE source=?", [(source,) for source in stale])
                db.executemany("DELETE FROM project_files WHERE root=? AND source=?",
                               [(root_key, source) for source in stale])
        return {"root": root_key, "files": files, "indexed": files - unchanged,
                "unchanged": unchanged, "removed": len(stale), "chunks": chunks,
                "skipped": skipped}

    def search(self, query: str, limit: int = 6) -> list[dict]:
        query_embedding = self.embedder.embed(query)
        with self._connect() as db:
            rows = db.execute("SELECT * FROM documents").fetchall()
        results = []
        query_tokens = set(TOKEN.findall(query.casefold()))
        for row in rows:
            lexical = _lexical(query, row["content"])
            vector = _cosine(query_embedding.vector, json.loads(row["embedding"] or "[]"))
            score = (0.72 * vector + 0.28 * lexical) if vector else lexical
            content_tokens = set(TOKEN.findall(row["content"].casefold()))
            if query_tokens and query_tokens.issubset(content_tokens):
                score = min(1.0, score + 0.08)
            if score > 0:
                results.append({"source": row["source"], "chunk": row["chunk_index"],
                                "score": round(score, 4), "lexical_score": round(lexical, 4),
                                "semantic_score": round(vector, 4), "updated_at": row["updated_at"],
                                "content": row["content"]})
        return sorted(results, key=lambda item: item["score"], reverse=True)[:max(1, min(limit, 20))]

    @staticmethod
    def _evidence_snapshot(db: sqlite3.Connection, evidence: list[str]) -> list[dict]:
        snapshot = []
        for source in evidence:
            rows = db.execute(
                "SELECT content_hash FROM documents WHERE source=? ORDER BY chunk_index", (source,)
            ).fetchall()
            if rows:
                digest = hashlib.sha256("".join(row["content_hash"] for row in rows).encode()).hexdigest()
                snapshot.append({"source": source, "digest": digest})
        return snapshot

    @classmethod
    def _evidence_is_current(cls, db: sqlite3.Connection, state: list[dict]) -> bool:
        if not state:
            return True
        sources = [item["source"] for item in state]
        return cls._evidence_snapshot(db, sources) == state

    def cache_answer(self, question: str, answer: str, evidence: list[str] | None = None) -> dict:
        question = question.strip()
        answer = answer.strip()
        if not question or not answer:
            raise ValueError("question and answer are required")
        embedded = self.embedder.embed(question)
        with self._connect() as db:
            evidence = evidence or []
            evidence_state = self._evidence_snapshot(db, evidence)
            existing = db.execute(
                "SELECT id FROM answer_cache WHERE lower(trim(question))=lower(trim(?)) ORDER BY id DESC LIMIT 1",
                (question,),
            ).fetchone()
            if existing:
                db.execute("""UPDATE answer_cache SET answer=?,evidence=?,evidence_state=?,question_embedding=?,
                    embedding_provider=?,created_at=?,last_used_at=?,hits=0 WHERE id=?""",
                    (answer, json.dumps(evidence), json.dumps(evidence_state), json.dumps(embedded.vector),
                     embedded.provider, _now(), _now(), existing["id"]))
                return {"cache_id": existing["id"], "provider": embedded.provider, "updated": True}
            cursor = db.execute("""INSERT INTO answer_cache
              (question,answer,evidence,evidence_state,question_embedding,embedding_provider,created_at,last_used_at,hits)
              VALUES(?,?,?,?,?,?,?,?,0)""", (question, answer, json.dumps(evidence),
              json.dumps(evidence_state), json.dumps(embedded.vector), embedded.provider, _now(), _now()))
        return {"cache_id": cursor.lastrowid, "provider": embedded.provider, "updated": False,
                "tracked_evidence": len(evidence_state)}

    def record_decision(self, title: str, decision: str, evidence: list[str] | None = None,
                        status: str = "active") -> dict:
        title, decision = title.strip(), decision.strip()
        if not title or not decision:
            raise ValueError("title and decision are required")
        if status not in {"active", "superseded", "tentative"}:
            raise ValueError("status must be active, superseded, or tentative")
        slug = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")[:72] or "decision"
        payload = {"title": title, "decision": decision, "evidence": evidence or [],
                   "status": status, "recorded_at": _now()}
        result = self.remember(f"decisions/{slug}.json", json.dumps(payload, indent=2))
        return {"source": result["source"], "status": status}

    def context_bundle(self, query: str, limit: int = 6, cache_threshold: float = 0.84) -> dict:
        query = query.strip()
        if not query:
            raise ValueError("query is required")
        return {"query": query, "cached_answer": self.lookup_answer(query, cache_threshold),
                "evidence": self.search(query, limit), "memory": self.status()}

    def lookup_answer(self, question: str, threshold: float = 0.84) -> dict:
        embedded = self.embedder.embed(question)
        with self._connect() as db:
            rows = db.execute("SELECT * FROM answer_cache").fetchall()
            candidates = []
            for row in rows:
                vector = _cosine(embedded.vector, json.loads(row["question_embedding"] or "[]"))
                lexical = _lexical(question, row["question"])
                score = (0.8 * vector + 0.2 * lexical) if vector else lexical
                candidates.append((score, row))
            candidates.sort(key=lambda item: item[0], reverse=True)
            best_score = candidates[0][0] if candidates else 0.0
            stale = 0
            best = None
            for score, row in candidates:
                if score < threshold:
                    break
                state = json.loads(row["evidence_state"] or "[]")
                if not self._evidence_is_current(db, state):
                    stale += 1
                    continue
                best, best_score = row, score
                break
            if best is None:
                return {"hit": False, "score": round(best_score, 4), "stale_candidates": stale}
            db.execute("UPDATE answer_cache SET hits=hits+1,last_used_at=? WHERE id=?", (_now(), best["id"]))
        return {"hit": True, "score": round(best_score, 4), "answer": best["answer"],
                "evidence": json.loads(best["evidence"]), "cache_id": best["id"],
                "evidence_current": True}

    def status(self) -> dict:
        with self._connect() as db:
            docs = db.execute("SELECT COUNT(*) count, COUNT(DISTINCT source) sources FROM documents").fetchone()
            cache = db.execute("SELECT COUNT(*) count, COALESCE(SUM(hits),0) hits FROM answer_cache").fetchone()
            providers = [row[0] for row in db.execute("SELECT DISTINCT embedding_provider FROM documents")]
        return {"documents": docs["count"], "sources": docs["sources"],
                "cached_answers": cache["count"], "cache_hits": cache["hits"],
                "providers": providers or ["not-yet-used"], "database": self.path}
