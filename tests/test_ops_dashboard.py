import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

_temp = tempfile.TemporaryDirectory()
os.environ["OPS_DB_PATH"] = str(Path(_temp.name) / "ops.db")
os.environ["OPS_BACKUP_DIR"] = str(Path(_temp.name) / "backups")
os.environ["OPS_ACCESS_TOKEN"] = "test-access-token-123456789012345"
os.environ["OPS_HEARTBEAT_TOKEN"] = "test-heartbeat-token-123456789012"

from ops_dashboard.app import (
    HeartbeatRequest,
    OpsStore,
    classify_health_payload,
    compute_overall,
    is_authenticated,
    session_cookie_value,
)


class CentralOperationsTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.store = OpsStore(Path(self.work.name) / "status.db")

    def tearDown(self):
        self.store.db.close()
        self.work.cleanup()

    def test_health_payload_classification(self):
        self.assertEqual(classify_health_payload({"status": "ok"})[0], "healthy")
        self.assertEqual(classify_health_payload({"status": "available"})[0], "healthy")
        self.assertEqual(classify_health_payload({"status": "degraded"})[0], "degraded")
        self.assertEqual(classify_health_payload("not-json")[0], "degraded")

    def test_auth_accepts_bearer_or_signed_session_cookie(self):
        self.assertTrue(
            is_authenticated(
                "Bearer test-access-token-123456789012345",
                None,
            )
        )
        self.assertTrue(is_authenticated(None, session_cookie_value()))
        self.assertFalse(is_authenticated("Bearer wrong", None))

    def test_signed_heartbeat_is_reported_healthy(self):
        self.store.heartbeat(
            "localmind",
            HeartbeatRequest(
                status="ok",
                version="1.3.0",
                host="test-pc",
                details={"model": "local"},
            ),
        )
        result = self.store.heartbeats(
            [{"id": "localmind", "name": "LocalMind", "critical": False}]
        )[0]
        self.assertEqual(result["status"], "healthy")
        self.assertEqual(result["version"], "1.3.0")
        self.assertEqual(result["details"]["model"], "local")

    def test_old_heartbeat_becomes_stale(self):
        self.store.heartbeat(
            "localmind",
            HeartbeatRequest(status="ok", version="1.0", details={}),
        )
        old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        self.store.db.execute(
            "UPDATE heartbeats SET last_seen=? WHERE system_id='localmind'", (old,)
        )
        self.store.db.commit()
        result = self.store.heartbeats(
            [{"id": "localmind", "name": "LocalMind", "critical": False}]
        )[0]
        self.assertEqual(result["status"], "stale")

    def test_overall_status_prioritizes_critical_runtime_failure(self):
        cloud = [
            {"critical": True, "status": "down"},
            {"critical": False, "status": "healthy"},
        ]
        local = [{"status": "healthy"}]
        repos = [{"status": "healthy"}]
        self.assertEqual(compute_overall(cloud, local, repos), "critical")

    def test_daily_backup_is_created(self):
        self.store.event("central-ops", "info", "test", "hello")
        import ops_dashboard.app as module
        original = module.BACKUP_DIR
        try:
            module.BACKUP_DIR = Path(self.work.name) / "backups"
            result = self.store.backup_if_needed()
            self.assertEqual(result["status"], "healthy")
            self.assertTrue(Path(result["path"]).exists())
        finally:
            module.BACKUP_DIR = original


if __name__ == "__main__":
    unittest.main()
