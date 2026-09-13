"""One-time, idempotent migration from the Railway SQLite volume to Postgres."""

import os
import sqlite3


TABLES = (
    "opportunities", "outcomes", "audit_log", "learning_proposals",
    "agent_records", "experience_cases", "work_reviews", "work_queue",
    "client_requests", "crm_syncs", "client_jobs", "authority_decisions",
    "practice_runs", "teacher_cycles",
)


def migrate_sqlite_to_postgres(sqlite_path, store):
    if not store.postgres or not os.path.isfile(sqlite_path):
        return {"status": "not_needed", "rows": 0}
    source = sqlite3.connect(sqlite_path)
    source.row_factory = sqlite3.Row
    copied = 0
    try:
        with store.connect() as target:
            target.execute("SELECT pg_advisory_xact_lock(82462126)")
            done = target.execute(
                "SELECT 1 present FROM migration_state WHERE name=?",
                ("railway_sqlite_v1",),
            ).fetchone()
            if done:
                return {"status": "already_complete", "rows": 0}
            for table in TABLES:
                exists = source.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
                ).fetchone()
                if not exists:
                    continue
                rows = source.execute(f'SELECT * FROM "{table}" ORDER BY id').fetchall()
                if not rows:
                    continue
                columns = rows[0].keys()
                names = ",".join(f'"{name}"' for name in columns)
                placeholders = ",".join("?" for _ in columns)
                for row in rows:
                    target.execute(
                        f'INSERT INTO "{table}" ({names}) VALUES ({placeholders}) ON CONFLICT DO NOTHING',
                        tuple(row),
                    )
                    copied += 1
                target.execute(
                    "SELECT setval(pg_get_serial_sequence(?, 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM \"{table}\"), 1), "
                    f"EXISTS(SELECT 1 FROM \"{table}\"))",
                    (f"bounty_builder.{table}",),
                )
            target.execute(
                "INSERT INTO migration_state(name,completed_at) VALUES(?,?) ON CONFLICT DO NOTHING",
                ("railway_sqlite_v1", _now()),
            )
    finally:
        source.close()
    return {"status": "complete", "rows": copied}


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
