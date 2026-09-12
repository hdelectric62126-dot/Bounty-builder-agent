import json
import sqlite3
from datetime import datetime, timezone


SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunities (
 id INTEGER PRIMARY KEY AUTOINCREMENT, external_id TEXT UNIQUE, title TEXT,
 url TEXT, repository TEXT, reward REAL, license TEXT, status TEXT,
 risk_score INTEGER, expected_value REAL, reason TEXT, discovered_at TEXT
);
CREATE TABLE IF NOT EXISTS outcomes (
 id INTEGER PRIMARY KEY AUTOINCREMENT, opportunity_id INTEGER, result TEXT,
 income REAL DEFAULT 0, cost REAL DEFAULT 0, hours REAL DEFAULT 0,
 recorded_at TEXT, notes TEXT
);
CREATE TABLE IF NOT EXISTS audit_log (
 id INTEGER PRIMARY KEY AUTOINCREMENT, event TEXT, details TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS learning_proposals (
 id INTEGER PRIMARY KEY AUTOINCREMENT, proposal TEXT, status TEXT, created_at TEXT
);
"""


class Store:
    def __init__(self, path: str):
        self.path = path
        with self.connect() as db:
            db.executescript(SCHEMA)

    def connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def audit(self, event, details):
        with self.connect() as db:
            db.execute("INSERT INTO audit_log VALUES(NULL,?,?,?)",
                       (event, json.dumps(details), now()))

    def save_opportunity(self, item):
        with self.connect() as db:
            db.execute("""INSERT OR IGNORE INTO opportunities
              VALUES(NULL,?,?,?,?,?,?,?,?,?,?,?)""", (
                item["external_id"], item["title"], item["url"], item["repository"],
                item["reward"], item["license"], item["status"], item["risk_score"],
                item["expected_value"], item["reason"], now()))

    def list_opportunities(self, limit=100):
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM opportunities ORDER BY risk_score DESC, id DESC LIMIT ?", (limit,))]

    def outcomes(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM outcomes ORDER BY id")]

    def stats(self):
        with self.connect() as db:
            row = db.execute("""SELECT COUNT(*) found,
              SUM(status='APPROVED') approved,
              SUM(status='REJECTED') rejected,
              COALESCE(SUM(expected_value),0) expected_value FROM opportunities""").fetchone()
            money = db.execute("SELECT COALESCE(SUM(income-cost),0) FROM outcomes").fetchone()[0]
            return {**dict(row), "realized_income": round(money, 2)}


def now():
    return datetime.now(timezone.utc).isoformat()

