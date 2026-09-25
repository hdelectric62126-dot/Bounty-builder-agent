import json
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from central_ops import build_ops_router


class FakeStore:
    postgres = True
    def stats(self):
        return {
            "found": 12, "approved": 3, "rejected": 9,
            "expected_value": 425.0, "realized_income": 75.0,
        }


class CentralOpsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = dict(os.environ)
        os.environ["ADMIN_TOKEN"] = "admin-secret"
        os.environ["OPS_HEARTBEAT_TOKEN"] = "heartbeat-secret"
        app = FastAPI()
        app.include_router(build_ops_router(FakeStore(), self.tmp.name, {"status": "ok"}))
        self.client = TestClient(app)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.old)
        self.tmp.cleanup()

    def test_dashboard_page_loads(self):
        response = self.client.get("/ops")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Central Operations", response.text)
        self.assertIn("READ ONLY", response.text)

    def test_summary_requires_admin_token(self):
        self.assertEqual(self.client.get("/ops/api/summary").status_code, 403)

    @patch("central_ops.requests.get")
    def test_summary_reports_bounty_and_remote_health_without_secrets(self, get):
        alpaca_health = Mock(status_code=200, headers={"content-type": "application/json"})
        alpaca_health.json.return_value = {"status": "available"}
        alpaca_dash = Mock(status_code=200, headers={"content-type": "application/json"})
        alpaca_dash.json.return_value = {
            "mode": "PAPER",
            "runtime": {"phase": "market_closed"},
            "metrics": {"realized_pnl": 1.25, "closed_trades": 2, "win_rate": 50.0,
                        "drawdown": 0.5, "pending_orders": 0},
            "guardian": [],
            "last_cycle": "2026-09-25T00:00:00+00:00",
        }
        sandbox = Mock(status_code=200, headers={"content-type": "application/json"})
        sandbox.json.return_value = {"status": "ready"}
        get.side_effect = [sandbox, alpaca_health, alpaca_dash]
        os.environ["SANDBOX_URL"] = "https://sandbox.example"
        os.environ["SANDBOX_TOKEN"] = "sandbox-secret"
        os.environ["OPS_READ_TOKEN"] = "ops-read-secret"

        response = self.client.get(
            "/ops/api/summary", headers={"X-Admin-Token": "admin-secret"}
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["systems"]["bounty"]["status"], "healthy")
        self.assertEqual(payload["systems"]["alpaca"]["status"], "healthy")
        self.assertEqual(payload["systems"]["workspace"]["status"], "healthy")
        serialized = json.dumps(payload)
        self.assertNotIn("admin-secret", serialized)
        self.assertNotIn("ops-read-secret", serialized)
        self.assertNotIn("sandbox-secret", serialized)

    def test_signed_local_heartbeat_becomes_healthy(self):
        response = self.client.post(
            "/ops/api/heartbeat/localmind",
            headers={"X-Ops-Token": "heartbeat-secret"},
            json={"detail": "Qwen ready", "meta": {"model": "qwen3-agent"}},
        )
        self.assertEqual(response.status_code, 200)
        summary = self.client.get(
            "/ops/api/summary", headers={"X-Admin-Token": "admin-secret"}
        ).json()
        self.assertEqual(summary["systems"]["localmind"]["status"], "healthy")
        self.assertEqual(summary["systems"]["localmind"]["detail"], "Qwen ready")


if __name__ == "__main__":
    unittest.main()
