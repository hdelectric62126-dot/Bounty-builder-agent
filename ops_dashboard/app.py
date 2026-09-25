"""Central Operations Dashboard.

Read-only operations console for the user's automation stack. It aggregates
public/internal health endpoints, selected authenticated read-only metrics,
GitHub source/CI state, and signed heartbeats from local applications.

The dashboard never places trades, submits bounties, or mutates downstream
systems. Operational write access is deliberately limited to receiving signed
heartbeats and maintaining its own status/event database.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import hmac
import json
import os
import re
import shutil
import sqlite3
import threading
import time
from typing import Any

import requests
from fastapi import Cookie, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field


APP_NAME = "Central Operations"
APP_VERSION = "1.0.0"
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DB_PATH = Path(os.getenv("OPS_DB_PATH", "/data/ops_dashboard.db"))
BACKUP_DIR = Path(os.getenv("OPS_BACKUP_DIR", "/data/backups"))
HTTP_TIMEOUT = float(os.getenv("OPS_HTTP_TIMEOUT_SECONDS", "4"))
GITHUB_CACHE_SECONDS = int(os.getenv("OPS_GITHUB_CACHE_SECONDS", "3600"))
HEARTBEAT_STALE_SECONDS = int(os.getenv("OPS_HEARTBEAT_STALE_SECONDS", "180"))

ACCESS_TOKEN = os.getenv("OPS_ACCESS_TOKEN", "")
HEARTBEAT_TOKEN = os.getenv("OPS_HEARTBEAT_TOKEN", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
ALPACA_READ_TOKEN = os.getenv("ALPACA_DASHBOARD_READ_TOKEN", "")

BASIC_ID_RE = re.compile(r"^[a-z0-9_-]{1,40}$")

app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat()


def session_cookie_value() -> str:
    if not ACCESS_TOKEN:
        return ""
    return sha256(("central-ops-session:" + ACCESS_TOKEN).encode("utf-8")).hexdigest()


def is_authenticated(
    authorization: str | None,
    ops_session: str | None,
) -> bool:
    if len(ACCESS_TOKEN) < 24:
        return False
    if ops_session and hmac.compare_digest(ops_session, session_cookie_value()):
        return True
    if authorization and authorization.startswith("Bearer "):
        supplied = authorization[7:]
        return hmac.compare_digest(supplied, ACCESS_TOKEN)
    return False


def require_auth(
    authorization: str | None = Header(default=None),
    ops_session: str | None = Cookie(default=None),
) -> None:
    if not is_authenticated(authorization, ops_session):
        raise HTTPException(status_code=401, detail="Authentication required")


class LoginRequest(BaseModel):
    token: str = Field(min_length=1, max_length=512)


class HeartbeatRequest(BaseModel):
    status: str = Field(default="ok", min_length=1, max_length=32)
    version: str | None = Field(default=None, max_length=120)
    host: str | None = Field(default=None, max_length=200)
    details: dict[str, Any] = Field(default_factory=dict)


class OpsStore:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path), check_same_thread=False, timeout=5)
        self.db.row_factory = sqlite3.Row
        self._migrate()

    def _migrate(self) -> None:
        with self.lock, self.db:
            self.db.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS heartbeats (
                    system_id TEXT PRIMARY KEY,
                    last_seen TEXT NOT NULL,
                    status TEXT NOT NULL,
                    version TEXT,
                    host TEXT,
                    details_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS service_state (
                    system_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    reason TEXT,
                    changed_at TEXT NOT NULL,
                    checked_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    system_id TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    details_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_timestamp
                    ON events(timestamp DESC);
                """
            )

    def event(
        self,
        system_id: str,
        severity: str,
        event_type: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        with self.lock, self.db:
            self.db.execute(
                """INSERT INTO events
                   (timestamp,system_id,severity,event_type,message,details_json)
                   VALUES (?,?,?,?,?,?)""",
                (
                    iso_now(),
                    system_id,
                    severity,
                    event_type,
                    message[:1000],
                    json.dumps(details or {}, sort_keys=True, allow_nan=False),
                ),
            )

    def record_state(self, system_id: str, status: str, reason: str = "") -> None:
        now = iso_now()
        with self.lock, self.db:
            existing = self.db.execute(
                "SELECT status,reason FROM service_state WHERE system_id=?",
                (system_id,),
            ).fetchone()
            if existing is None:
                self.db.execute(
                    """INSERT INTO service_state
                       (system_id,status,reason,changed_at,checked_at)
                       VALUES (?,?,?,?,?)""",
                    (system_id, status, reason[:1000], now, now),
                )
                self.event(
                    system_id,
                    "info" if status == "healthy" else "warning",
                    "state_initialized",
                    f"{system_id} initialized as {status}",
                    {"reason": reason},
                )
                return
            changed = existing["status"] != status or (existing["reason"] or "") != reason
            self.db.execute(
                """UPDATE service_state
                   SET status=?,reason=?,changed_at=CASE WHEN ? THEN ? ELSE changed_at END,
                       checked_at=?
                   WHERE system_id=?""",
                (status, reason[:1000], 1 if changed else 0, now, now, system_id),
            )
            if changed:
                severity = "info" if status == "healthy" else (
                    "critical" if status == "down" else "warning"
                )
                self.event(
                    system_id,
                    severity,
                    "state_changed",
                    f"{system_id} changed to {status}",
                    {"reason": reason},
                )

    def heartbeat(self, system_id: str, payload: HeartbeatRequest) -> None:
        now = iso_now()
        previous = self.db.execute(
            "SELECT status,last_seen FROM heartbeats WHERE system_id=?",
            (system_id,),
        ).fetchone()
        with self.lock, self.db:
            self.db.execute(
                """INSERT INTO heartbeats
                   (system_id,last_seen,status,version,host,details_json)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(system_id) DO UPDATE SET
                     last_seen=excluded.last_seen,
                     status=excluded.status,
                     version=excluded.version,
                     host=excluded.host,
                     details_json=excluded.details_json""",
                (
                    system_id,
                    now,
                    payload.status,
                    payload.version,
                    payload.host,
                    json.dumps(payload.details, sort_keys=True, allow_nan=False),
                ),
            )
        if previous is None or previous["status"] != payload.status:
            self.event(
                system_id,
                "info" if payload.status.lower() in {"ok", "healthy", "ready"} else "warning",
                "heartbeat",
                f"{system_id} heartbeat reports {payload.status}",
                {"version": payload.version, "host": payload.host},
            )

    def heartbeats(self, expected: list[dict[str, Any]]) -> list[dict[str, Any]]:
        now = utc_now()
        rows = {
            row["system_id"]: row
            for row in self.db.execute("SELECT * FROM heartbeats").fetchall()
        }
        output = []
        for config in expected:
            system_id = config["id"]
            row = rows.get(system_id)
            if row is None:
                output.append(
                    {
                        **config,
                        "status": "waiting",
                        "reason": "No runtime heartbeat received yet",
                        "last_seen": None,
                        "age_seconds": None,
                        "version": None,
                        "host": None,
                        "details": {},
                    }
                )
                continue
            try:
                seen = datetime.fromisoformat(row["last_seen"]).astimezone(timezone.utc)
                age = max(0.0, (now - seen).total_seconds())
            except Exception:
                age = float("inf")
            raw_status = str(row["status"]).lower()
            stale = age > HEARTBEAT_STALE_SECONDS
            status = "stale" if stale else (
                "healthy" if raw_status in {"ok", "healthy", "ready"} else "degraded"
            )
            output.append(
                {
                    **config,
                    "status": status,
                    "reason": (
                        f"Heartbeat is {int(age)}s old" if stale
                        else f"Heartbeat reports {row['status']}"
                    ),
                    "last_seen": row["last_seen"],
                    "age_seconds": None if age == float("inf") else round(age, 1),
                    "version": row["version"],
                    "host": row["host"],
                    "details": json.loads(row["details_json"] or "{}"),
                }
            )
        return output

    def recent_events(self, limit: int = 40) -> list[dict[str, Any]]:
        rows = self.db.execute(
            """SELECT timestamp,system_id,severity,event_type,message,details_json
               FROM events ORDER BY id DESC LIMIT ?""",
            (int(limit),),
        ).fetchall()
        return [
            {
                "timestamp": row["timestamp"],
                "system_id": row["system_id"],
                "severity": row["severity"],
                "event_type": row["event_type"],
                "message": row["message"],
                "details": json.loads(row["details_json"] or "{}"),
            }
            for row in rows
        ]

    def backup_if_needed(self) -> dict[str, Any]:
        if str(self.path) == ":memory:":
            return {"status": "not_applicable", "last_backup": None}
        try:
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            stamp = utc_now().strftime("%Y%m%d")
            target = BACKUP_DIR / f"ops-dashboard-{stamp}.db"
            if not target.exists():
                with self.lock:
                    destination = sqlite3.connect(str(target))
                    try:
                        self.db.backup(destination)
                    finally:
                        destination.close()
            stat = target.stat()
            return {
                "status": "healthy",
                "last_backup": datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                ).isoformat(),
                "path": str(target),
            }
        except Exception as exc:
            return {
                "status": "degraded",
                "last_backup": None,
                "reason": type(exc).__name__,
            }


store = OpsStore(DB_PATH)


HTTP_MONITORS = [
    {
        "id": "bounty-builder",
        "name": "Bounty Builder",
        "category": "Revenue Automation",
        "critical": True,
        "health_url": os.getenv(
            "BOUNTY_HEALTH_URL",
            "https://bounty-builder-agent-production.up.railway.app/health",
        ),
        "link": os.getenv(
            "BOUNTY_APP_URL",
            "https://bounty-builder-agent-production.up.railway.app",
        ),
        "storage": "Railway persistent /data volume",
        "capabilities": ["bounty discovery", "isolated builds", "approval-gated submission"],
    },
    {
        "id": "alpaca-agent",
        "name": "Alpaca Trading Agent",
        "category": "Trading Research",
        "critical": True,
        "health_url": os.getenv(
            "ALPACA_HEALTH_URL",
            "https://alpaca-trading-agent-86-production.up.railway.app/health",
        ),
        "link": os.getenv(
            "ALPACA_APP_URL",
            "https://alpaca-trading-agent-86-production.up.railway.app",
        ),
        "storage": "Railway persistent /data volume",
        "capabilities": [
            "paper trading",
            "guardian",
            "strategy ensemble",
            "counterfactual learning",
        ],
    },
    {
        "id": "opportunity-scout",
        "name": "Opportunity Scout",
        "category": "Legacy / Discovery",
        "critical": False,
        "health_url": os.getenv(
            "SCOUT_HEALTH_URL",
            "https://web-production-71de9.up.railway.app/health",
        ),
        "link": os.getenv(
            "SCOUT_APP_URL",
            "https://web-production-71de9.up.railway.app",
        ),
        "storage": "No persistent Railway volume detected",
        "capabilities": ["opportunity scanning"],
    },
]


EXPECTED_LOCAL_SYSTEMS = [
    {
        "id": "localmind",
        "name": "Native Mind / LocalMind",
        "category": "Local AI",
        "critical": False,
        "capabilities": ["local Qwen", "memory", "tools", "browser automation"],
    },
    {
        "id": "1099-agent",
        "name": "1099 Business OS",
        "category": "Business Operations",
        "critical": False,
        "capabilities": ["receipts", "expenses", "jobs", "reports", "accountant export"],
    },
    {
        "id": "license-tools",
        "name": "License Navigator + Scraper",
        "category": "Electrical Licensing",
        "critical": False,
        "capabilities": ["municipality research", "license workflow", "study tracking"],
    },
]


REPOSITORIES = [
    {
        "id": "repo-bounty",
        "name": "Bounty Builder source",
        "repo": "hdelectric62126-dot/Bounty-builder-agent",
        "branch": "main",
        "private": False,
    },
    {
        "id": "repo-alpaca",
        "name": "Alpaca agent source",
        "repo": "hdelectric62126-dot/Alpaca-trading-agent-86",
        "branch": "main",
        "private": False,
    },
    {
        "id": "repo-1099",
        "name": "1099 source",
        "repo": "hdelectric62126-dot/1099",
        "branch": "main",
        "private": False,
    },
    {
        "id": "repo-localmind",
        "name": "LocalMind source",
        "repo": "hdelectric62126-dot/LocalMind",
        "branch": "main",
        "private": True,
    },
    {
        "id": "repo-scout",
        "name": "Opportunity Scout source",
        "repo": "hdelectric62126-dot/opportunity-scout-agent",
        "branch": "main",
        "private": False,
    },
]


_repo_cache: dict[str, Any] = {"expires": 0.0, "data": []}
_repo_cache_lock = threading.Lock()


def safe_json(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def request_with_retry(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    attempts: int = 2,
) -> tuple[requests.Response, int]:
    """GET a fixed operations endpoint with one bounded transient retry."""
    last_error: requests.RequestException | None = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            response = requests.get(
                url,
                timeout=HTTP_TIMEOUT,
                headers=headers or {"User-Agent": f"CentralOperations/{APP_VERSION}"},
            )
            return response, attempt
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(0.15 * attempt)
                continue
            raise
        except requests.RequestException:
            raise
    assert last_error is not None
    raise last_error


def classify_health_payload(payload: Any) -> tuple[str, str]:
    if not isinstance(payload, dict):
        return "degraded", "Endpoint returned non-JSON health data"
    raw = str(payload.get("status", "")).strip().lower()
    if raw in {"ok", "healthy", "ready", "available", "up"}:
        return "healthy", raw or "healthy"
    if raw in {"degraded", "warning", "partial", "isolation_unavailable"}:
        return "degraded", raw
    if raw:
        return "degraded", raw
    return "healthy", "HTTP health endpoint responded"


def fetch_http_monitor(config: dict[str, Any]) -> dict[str, Any]:
    started = time.monotonic()
    try:
        response, attempts = request_with_retry(
            config["health_url"],
            attempts=2 if config.get("critical") else 1,
        )
        latency = round((time.monotonic() - started) * 1000.0, 1)
        payload = safe_json(response)
        if response.status_code >= 500:
            status, reason = "down", f"HTTP {response.status_code}"
        elif response.status_code >= 400:
            status, reason = "degraded", f"HTTP {response.status_code}"
        else:
            status, reason = classify_health_payload(payload)
        result = {
            **config,
            "status": status,
            "reason": reason,
            "checked_at": iso_now(),
            "latency_ms": latency,
            "http_status": response.status_code,
            "attempts": attempts,
            "details": payload if isinstance(payload, dict) else {},
        }
    except requests.RequestException as exc:
        result = {
            **config,
            "status": "down" if config.get("critical") else "degraded",
            "reason": type(exc).__name__,
            "checked_at": iso_now(),
            "latency_ms": round((time.monotonic() - started) * 1000.0, 1),
            "http_status": None,
            "attempts": 2 if config.get("critical") else 1,
            "details": {},
        }
    store.record_state(config["id"], result["status"], result["reason"])
    return result


def fetch_alpaca_detail() -> dict[str, Any]:
    if len(ALPACA_READ_TOKEN) < 24:
        return {
            "status": "unavailable",
            "reason": "Read-only Alpaca dashboard token is not connected",
        }
    base = os.getenv(
        "ALPACA_DETAIL_URL",
        "https://alpaca-trading-agent-86-production.up.railway.app/api/dashboard?days=7",
    )
    started = time.monotonic()
    try:
        response, attempts = request_with_retry(
            base,
            attempts=2,
            headers={
                "Authorization": "Bearer " + ALPACA_READ_TOKEN,
                "User-Agent": f"CentralOperations/{APP_VERSION}",
            },
        )
        if response.status_code != 200:
            return {
                "status": "degraded",
                "reason": f"HTTP {response.status_code}",
                "latency_ms": round((time.monotonic() - started) * 1000.0, 1),
            }
        payload = safe_json(response)
        if not isinstance(payload, dict):
            return {"status": "degraded", "reason": "Invalid dashboard payload"}
        return {
            "status": "healthy",
            "reason": "Authenticated read-only metrics connected",
            "latency_ms": round((time.monotonic() - started) * 1000.0, 1),
            "attempts": attempts,
            "mode": payload.get("mode"),
            "runtime": payload.get("runtime"),
            "research": payload.get("research"),
            "metrics": payload.get("metrics") or {},
            "tracked_positions": payload.get("tracked_positions") or [],
            "guardian": payload.get("guardian") or [],
            "last_cycle": payload.get("last_cycle"),
        }
    except requests.RequestException as exc:
        return {"status": "degraded", "reason": type(exc).__name__}


def github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"CentralOperations/{APP_VERSION}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = "Bearer " + GITHUB_TOKEN
    return headers


def fetch_repository_status(config: dict[str, Any]) -> dict[str, Any]:
    repo = config["repo"]
    branch = config["branch"]
    headers = github_headers()
    try:
        commit_response = requests.get(
            f"https://api.github.com/repos/{repo}/commits",
            params={"sha": branch, "per_page": 1},
            headers=headers,
            timeout=HTTP_TIMEOUT,
        )
        if commit_response.status_code == 404 and config.get("private") and not GITHUB_TOKEN:
            return {
                **config,
                "status": "auth_needed",
                "reason": "Private repository requires optional GITHUB_TOKEN",
                "latest_commit": None,
                "ci": None,
            }
        if commit_response.status_code in {403, 429}:
            return {
                **config,
                "status": "rate_limited",
                "reason": "GitHub source monitor is temporarily rate limited",
                "latest_commit": None,
                "ci": None,
            }
        commit_response.raise_for_status()
        commits = commit_response.json()
        commit = commits[0] if commits else {}
        commit_info = commit.get("commit") or {}
        author_info = commit_info.get("author") or {}

        actions_response = requests.get(
            f"https://api.github.com/repos/{repo}/actions/runs",
            params={"branch": branch, "per_page": 1},
            headers=headers,
            timeout=HTTP_TIMEOUT,
        )
        ci = None
        if actions_response.status_code == 200:
            runs = (actions_response.json() or {}).get("workflow_runs") or []
            if runs:
                run = runs[0]
                ci = {
                    "status": run.get("status"),
                    "conclusion": run.get("conclusion"),
                    "name": run.get("name"),
                    "updated_at": run.get("updated_at"),
                    "url": run.get("html_url"),
                }
        bad_ci = ci and ci.get("status") == "completed" and ci.get("conclusion") not in {
            "success",
            "neutral",
            "skipped",
        }
        return {
            **config,
            "status": "degraded" if bad_ci else "healthy",
            "reason": "Latest CI is failing" if bad_ci else "Source reachable",
            "latest_commit": {
                "sha": str(commit.get("sha", ""))[:10],
                "message": str(commit_info.get("message", "")).splitlines()[0][:200],
                "date": author_info.get("date"),
                "url": commit.get("html_url"),
            },
            "ci": ci,
        }
    except requests.RequestException as exc:
        return {
            **config,
            "status": "degraded",
            "reason": type(exc).__name__,
            "latest_commit": None,
            "ci": None,
        }


def repository_statuses() -> list[dict[str, Any]]:
    now_mono = time.monotonic()
    with _repo_cache_lock:
        if _repo_cache["data"] and now_mono < _repo_cache["expires"]:
            return _repo_cache["data"]
    # GitHub applies secondary throttles more aggressively to bursts from shared
    # cloud egress IPs. Keep source checks intentionally low-concurrency.
    with ThreadPoolExecutor(max_workers=min(2, len(REPOSITORIES))) as pool:
        futures = [pool.submit(fetch_repository_status, config) for config in REPOSITORIES]
        results = [future.result() for future in as_completed(futures)]
    order = {config["id"]: index for index, config in enumerate(REPOSITORIES)}
    results.sort(key=lambda item: order[item["id"]])
    with _repo_cache_lock:
        _repo_cache["data"] = results
        _repo_cache["expires"] = now_mono + GITHUB_CACHE_SECONDS
    return results


def external_statuses() -> list[dict[str, Any]]:
    with ThreadPoolExecutor(max_workers=len(HTTP_MONITORS)) as pool:
        futures = [pool.submit(fetch_http_monitor, config) for config in HTTP_MONITORS]
        results = [future.result() for future in as_completed(futures)]
    order = {config["id"]: index for index, config in enumerate(HTTP_MONITORS)}
    results.sort(key=lambda item: order[item["id"]])
    return results


def summarize_bounty(monitor: dict[str, Any]) -> dict[str, Any]:
    details = monitor.get("details") or {}
    stats = details.get("stats") if isinstance(details, dict) else {}
    execution = details.get("bounty_execution") if isinstance(details, dict) else {}
    return {
        "database": details.get("database") if isinstance(details, dict) else None,
        "worker_enabled": (execution or {}).get("worker_enabled"),
        "model_configured": (execution or {}).get("model_configured"),
        "cloud_budget": (execution or {}).get("cloud_budget"),
        "found": (stats or {}).get("found"),
        "approved": (stats or {}).get("approved"),
        "rejected": (stats or {}).get("rejected"),
        "expected_value": (stats or {}).get("expected_value"),
        "realized_income": (stats or {}).get("realized_income"),
        "agent_activity": (stats or {}).get("agent_activity"),
    }


def action_center(
    cloud: list[dict[str, Any]],
    local: list[dict[str, Any]],
    repos: list[dict[str, Any]],
    backup: dict[str, Any],
    alpaca_detail: dict[str, Any],
    bounty_summary: dict[str, Any],
) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    for item in cloud:
        if item["status"] == "down":
            actions.append({
                "severity": "critical",
                "system": item["name"],
                "message": f"Runtime health check failed: {item['reason']}",
            })
        elif item["status"] == "degraded":
            actions.append({
                "severity": "warning",
                "system": item["name"],
                "message": f"Runtime is degraded: {item['reason']}",
            })
    for item in local:
        if item["status"] in {"waiting", "stale", "degraded"}:
            actions.append({
                "severity": "warning",
                "system": item["name"],
                "message": item["reason"],
            })
    for item in repos:
        if item["status"] == "degraded":
            actions.append({
                "severity": "warning",
                "system": item["name"],
                "message": item["reason"],
            })
    if backup.get("status") != "healthy":
        actions.append({
            "severity": "warning",
            "system": "Central Operations",
            "message": "Dashboard status database backup is not healthy",
        })
    if alpaca_detail.get("status") != "healthy":
        actions.append({
            "severity": "warning",
            "system": "Alpaca Trading Agent",
            "message": alpaca_detail.get("reason", "Read-only metrics unavailable"),
        })
    elif str(alpaca_detail.get("mode") or "").upper() not in {"", "PAPER"}:
        actions.append({
            "severity": "critical",
            "system": "Alpaca Trading Agent",
            "message": "Trading dashboard is not reporting PAPER mode",
        })
    else:
        unhealthy_guardian = [
            row for row in (alpaca_detail.get("guardian") or [])
            if int(row.get("failures") or 0) > 0
        ]
        if unhealthy_guardian:
            actions.append({
                "severity": "warning",
                "system": "Alpaca Trading Agent",
                "message": f"Guardian reports failures in {len(unhealthy_guardian)} subsystem(s)",
            })

    if bounty_summary.get("worker_enabled") is False:
        actions.append({
            "severity": "critical",
            "system": "Bounty Builder",
            "message": "Bounty execution worker is disabled",
        })
    if bounty_summary.get("model_configured") is False:
        actions.append({
            "severity": "warning",
            "system": "Bounty Builder",
            "message": "Cloud model is not configured; automatic bounty generation is blocked",
        })
    budget = bounty_summary.get("cloud_budget")
    if isinstance(budget, dict):
        remaining_jobs = budget.get("remaining_jobs")
        remaining_calls = budget.get("remaining_calls")
        if remaining_jobs == 0 or remaining_calls == 0:
            actions.append({
                "severity": "warning",
                "system": "Bounty Builder",
                "message": "Today's cloud-model budget is exhausted",
            })
    return actions[:12]


def compute_overall(
    cloud: list[dict[str, Any]],
    local: list[dict[str, Any]],
    repos: list[dict[str, Any]],
) -> str:
    if any(item.get("critical") and item["status"] == "down" for item in cloud):
        return "critical"
    if any(item["status"] in {"down", "degraded"} for item in cloud):
        return "degraded"
    if any(item["status"] in {"stale", "degraded"} for item in local):
        return "degraded"
    if any(item["status"] == "degraded" for item in repos):
        return "degraded"
    if any(item["status"] == "waiting" for item in local):
        return "attention"
    return "healthy"


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers[
        "Content-Security-Policy"
    ] = (
        "default-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "frame-ancestors 'none'"
    )
    return response


@app.get("/health")
def health():
    configured = len(ACCESS_TOKEN) >= 24 and len(HEARTBEAT_TOKEN) >= 24
    return {
        "status": "ok" if configured else "configuration_required",
        "service": APP_NAME,
        "version": APP_VERSION,
        "auth_configured": len(ACCESS_TOKEN) >= 24,
        "heartbeat_configured": len(HEARTBEAT_TOKEN) >= 24,
    }


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/login")
def login(payload: LoginRequest, response: Response):
    if len(ACCESS_TOKEN) < 24:
        raise HTTPException(status_code=503, detail="Dashboard access token is not configured")
    if not hmac.compare_digest(payload.token, ACCESS_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid access code")
    response.set_cookie(
        "ops_session",
        session_cookie_value(),
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=60 * 60 * 24 * 30,
        path="/",
    )
    return {"status": "ok"}


@app.post("/api/logout")
def logout(response: Response):
    response.delete_cookie("ops_session", path="/")
    return {"status": "ok"}


@app.get("/api/overview")
def overview(
    authorization: str | None = Header(default=None),
    ops_session: str | None = Cookie(default=None),
):
    if not is_authenticated(authorization, ops_session):
        raise HTTPException(status_code=401, detail="Authentication required")

    cloud = external_statuses()
    local = store.heartbeats(EXPECTED_LOCAL_SYSTEMS)
    repos = repository_statuses()
    alpaca_detail = fetch_alpaca_detail()
    backup = store.backup_if_needed()

    bounty_monitor = next(
        (item for item in cloud if item["id"] == "bounty-builder"),
        {},
    )
    bounty_summary = summarize_bounty(bounty_monitor)
    overall = compute_overall(cloud, local, repos)
    actions = action_center(
        cloud, local, repos, backup, alpaca_detail, bounty_summary
    )
    if any(item["severity"] == "critical" for item in actions):
        overall = "critical"
    elif overall == "healthy" and actions:
        overall = "attention"

    healthy_cloud = sum(item["status"] == "healthy" for item in cloud)
    healthy_local = sum(item["status"] == "healthy" for item in local)
    healthy_repos = sum(item["status"] == "healthy" for item in repos)

    return {
        "generated_at": iso_now(),
        "service": {"name": APP_NAME, "version": APP_VERSION},
        "overall": overall,
        "summary": {
            "cloud_healthy": healthy_cloud,
            "cloud_total": len(cloud),
            "local_healthy": healthy_local,
            "local_total": len(local),
            "repos_healthy": healthy_repos,
            "repos_total": len(repos),
            "open_actions": len(actions),
        },
        "cloud": cloud,
        "local": local,
        "repositories": repos,
        "alpaca": alpaca_detail,
        "bounty": bounty_summary,
        "backup": backup,
        "actions": actions,
        "events": store.recent_events(),
    }


@app.post("/api/heartbeat/{system_id}")
def heartbeat(
    system_id: str,
    payload: HeartbeatRequest,
    x_ops_heartbeat: str | None = Header(default=None),
):
    if not BASIC_ID_RE.fullmatch(system_id):
        raise HTTPException(status_code=404, detail="Unknown system identifier")
    if len(HEARTBEAT_TOKEN) < 24:
        raise HTTPException(status_code=503, detail="Heartbeat receiver is not configured")
    if not x_ops_heartbeat or not hmac.compare_digest(x_ops_heartbeat, HEARTBEAT_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid heartbeat token")
    if system_id not in {item["id"] for item in EXPECTED_LOCAL_SYSTEMS}:
        raise HTTPException(status_code=404, detail="Unknown system identifier")
    store.heartbeat(system_id, payload)
    return {"status": "accepted", "system_id": system_id, "received_at": iso_now()}


@app.get("/api/connectors")
def connectors(
    request: Request,
    authorization: str | None = Header(default=None),
    ops_session: str | None = Cookie(default=None),
):
    if not is_authenticated(authorization, ops_session):
        raise HTTPException(status_code=401, detail="Authentication required")
    origin = str(request.base_url).rstrip("/")
    token = HEARTBEAT_TOKEN if len(HEARTBEAT_TOKEN) >= 24 else ""
    powershell = (
        f'[Environment]::SetEnvironmentVariable("OPS_DASHBOARD_URL","{origin}","User")\n'
        f'[Environment]::SetEnvironmentVariable("OPS_HEARTBEAT_TOKEN","{token}","User")\n'
        'Write-Host "Central Operations connector saved. Restart LocalMind."'
    )
    return {
        "dashboard_url": origin,
        "heartbeat_configured": bool(token),
        "localmind": {
            "system_id": "localmind",
            "powershell_setup": powershell,
            "heartbeat_endpoint": origin + "/api/heartbeat/localmind",
        },
        "generic_heartbeat": {
            "header": "X-Ops-Heartbeat",
            "token": token,
            "body_example": {
                "status": "ok",
                "version": "1.0",
                "host": "Windows-PC",
                "details": {"note": "runtime heartbeat"},
            },
        },
    }


@app.get("/api/events")
def events(
    authorization: str | None = Header(default=None),
    ops_session: str | None = Cookie(default=None),
):
    if not is_authenticated(authorization, ops_session):
        raise HTTPException(status_code=401, detail="Authentication required")
    return {"events": store.recent_events(100)}


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    # Do not leak internal exception text into the browser.
    store.event(
        "central-ops",
        "critical",
        "unhandled_error",
        type(exc).__name__,
        {"path": request.url.path},
    )
    return JSONResponse(status_code=500, content={"detail": "Internal dashboard error"})
