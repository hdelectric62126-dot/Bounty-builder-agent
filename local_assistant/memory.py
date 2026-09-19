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
            """)

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
        files = chunks = skipped = 0
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES or any(part in SKIP_PARTS for part in path.parts):
                continue
            if path.stat().st_size > max_file_bytes:
                skipped += 1
                continue
            try:
                result = self.remember(str(path.relative_to(root)), path.read_text(encoding="utf-8"))
                files += 1
                chunks += result["chunks"]
            except UnicodeDecodeError:
                skipped += 1
        return {"root": str(root), "files": files, "chunks": chunks, "skipped": skipped}

    def search(self, query: str, limit: int = 6) -> list[dict]:
        query_embedding = self.embedder.embed(query)
        with self._connect() as db:
            rows = db.execute("SELECT * FROM documents").fetchall()
        results = []
        for row in rows:
            lexical = _lexical(query, row["content"])
            vector = _cosine(query_embedding.vector, json.loads(row["embedding"] or "[]"))
            score = vector if vector else lexical
            if score > 0:
                results.append({"source": row["source"], "chunk": row["chunk_index"],
                                "score": round(score, 4), "content": row["content"]})
        return sorted(results, key=lambda item: item["score"], reverse=True)[:max(1, min(limit, 20))]

    def cache_answer(self, question: str, answer: str, evidence: list[str] | None = None) -> dict:
        embedded = self.embedder.embed(question)
        with self._connect() as db:
            cursor = db.execute("""INSERT INTO answer_cache
              (question,answer,evidence,question_embedding,embedding_provider,created_at,last_used_at,hits)
              VALUES(?,?,?,?,?,?,?,0)""", (question, answer, json.dumps(evidence or []),
              json.dumps(embedded.vector), embedded.provider, _now(), _now()))
        return {"cache_id": cursor.lastrowid, "provider": embedded.provider}

    def lookup_answer(self, question: str, threshold: float = 0.84) -> dict:
        embedded = self.embedder.embed(question)
        with self._connect() as db:
            rows = db.execute("SELECT * FROM answer_cache").fetchall()
            best, best_score = None, 0.0
            for row in rows:
                vector = _cosine(embedded.vector, json.loads(row["question_embedding"] or "[]"))
                score = vector if vector else _lexical(question, row["question"])
                if score > best_score:
                    best, best_score = row, score
            if best is None or best_score < threshold:
                return {"hit": False, "score": round(best_score, 4)}
            db.execute("UPDATE answer_cache SET hits=hits+1,last_used_at=? WHERE id=?", (_now(), best["id"]))
        return {"hit": True, "score": round(best_score, 4), "answer": best["answer"],
                "evidence": json.loads(best["evidence"]), "cache_id": best["id"]}

    def status(self) -> dict:
        with self._connect() as db:
            docs = db.execute("SELECT COUNT(*) count, COUNT(DISTINCT source) sources FROM documents").fetchone()
            cache = db.execute("SELECT COUNT(*) count, COALESCE(SUM(hits),0) hits FROM answer_cache").fetchone()
            providers = [row[0] for row in db.execute("SELECT DISTINCT embedding_provider FROM documents")]
        return {"documents": docs["count"], "sources": docs["sources"],
                "cached_answers": cache["count"], "cache_hits": cache["hits"],
                "providers": providers or ["not-yet-used"], "database": self.path}
