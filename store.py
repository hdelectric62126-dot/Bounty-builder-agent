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
CREATE TABLE IF NOT EXISTS agent_records (
 id INTEGER PRIMARY KEY AUTOINCREMENT, external_id TEXT, agent TEXT,
 payload TEXT, created_at TEXT, UNIQUE(external_id, agent)
);
CREATE TABLE IF NOT EXISTS experience_cases (
 id INTEGER PRIMARY KEY AUTOINCREMENT, external_id TEXT UNIQUE, sampled_year INTEGER,
 repository TEXT, category TEXT, cycle_days INTEGER, comments INTEGER,
 labels TEXT, state_reason TEXT, source_url TEXT, learned_at TEXT
);
CREATE TABLE IF NOT EXISTS work_reviews (
 id INTEGER PRIMARY KEY AUTOINCREMENT, opportunity_id INTEGER, evidence_id TEXT UNIQUE,
 decision TEXT, payload TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS work_queue (
 id INTEGER PRIMARY KEY AUTOINCREMENT, opportunity_id INTEGER UNIQUE,
 stage TEXT, deliberation TEXT, created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS client_requests (
 id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, email TEXT, project TEXT,
 budget TEXT, status TEXT, quote_cents INTEGER, quote_description TEXT,
 stripe_session_id TEXT UNIQUE, payment_status TEXT, created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS practice_runs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, exercise_id TEXT, category TEXT,
 difficulty INTEGER, score INTEGER, verified_pass INTEGER, evidence_id TEXT UNIQUE,
 lesson TEXT, result TEXT, created_at TEXT
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
            db.execute("""INSERT INTO opportunities VALUES(NULL,?,?,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(external_id) DO UPDATE SET title=excluded.title,
              url=excluded.url, repository=excluded.repository, reward=excluded.reward,
              license=excluded.license, status=excluded.status,
              risk_score=excluded.risk_score, expected_value=excluded.expected_value,
              reason=excluded.reason""", (
                item["external_id"], item["title"], item["url"], item["repository"],
                item["reward"], item["license"], item["status"], item["risk_score"],
                item["expected_value"], item["reason"], now()))
            for key, agent in (("repository_analysis", "repository_analyst"),
                               ("risk_compliance", "risk_compliance_agent"),
                               ("solution_plan", "solution_planner")):
                if item.get(key) is not None:
                    db.execute("""INSERT INTO agent_records VALUES(NULL,?,?,?,?)
                      ON CONFLICT(external_id,agent) DO UPDATE SET
                      payload=excluded.payload, created_at=excluded.created_at""",
                      (item["external_id"], agent, json.dumps(item[key]), now()))

    def save_practice_run(self, result):
        with self.connect() as db:
            cursor = db.execute("""INSERT OR IGNORE INTO practice_runs
              VALUES(NULL,?,?,?,?,?,?,?,?,?)""", (
                result["exercise_id"], result["category"], result["difficulty"],
                result["score"], int(result["verified_pass"]), result["evidence_id"],
                result["lesson"], json.dumps(result), now(),
            ))
        return cursor.rowcount

    def practice_stats(self):
        with self.connect() as db:
            row = db.execute("""SELECT COUNT(*) drills,
              COALESCE(SUM(verified_pass),0) verified_passes,
              COALESCE(ROUND(AVG(score),1),0) average_score,
              COALESCE(MAX(difficulty),0) max_difficulty FROM practice_runs""").fetchone()
            return dict(row)

    def skill_profile(self):
        """Summarize only sandbox-verified practice evidence."""
        languages = {}
        verified_skills = set()
        scores = []
        max_difficulty = 0
        with self.connect() as db:
            rows = db.execute("""SELECT category, difficulty, score, result
              FROM practice_runs WHERE verified_pass=1""").fetchall()
        language_scores = {}
        for row in rows:
            payload = json.loads(row["result"])
            language = str(payload.get("language") or "unknown")
            language_scores.setdefault(language, []).append(row["score"])
            verified_skills.add(row["category"])
            scores.append(row["score"])
            max_difficulty = max(max_difficulty, row["difficulty"])
        for language, values in language_scores.items():
            languages[language] = {
                "verified_passes": len(values),
                "average_score": round(sum(values) / len(values), 1),
            }
        return {"verified_skills": sorted(verified_skills), "languages": languages,
                "verified_passes": len(scores),
                "average_score": round(sum(scores) / len(scores), 1) if scores else 0,
                "max_difficulty": max_difficulty}

    def reject_unseen_approvals(self, seen_external_ids):
        """Remove stale approvals after a complete scan without deleting history."""
        seen = {str(value) for value in seen_external_ids}
        with self.connect() as db:
            rows = db.execute(
                "SELECT external_id FROM opportunities WHERE status='APPROVED'"
            ).fetchall()
            stale = [row["external_id"] for row in rows if row["external_id"] not in seen]
            if stale:
                placeholders = ",".join("?" for _ in stale)
                db.execute(
                    f"""UPDATE opportunities SET status='REJECTED', risk_score=0,
                    reason='REJECT_NOT_IN_LATEST_COMPLETE_SCAN'
                    WHERE external_id IN ({placeholders})""",
                    stale,
                )
        return len(stale)

    def list_opportunities(self, limit=100):
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM opportunities ORDER BY risk_score DESC, id DESC LIMIT ?", (limit,))]

    def get_opportunity(self, opportunity_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM opportunities WHERE id=?", (opportunity_id,)).fetchone()
            return dict(row) if row else None

    def agent_records_for(self, external_id):
        with self.connect() as db:
            rows = db.execute("""SELECT agent, payload, created_at FROM agent_records
              WHERE external_id=? ORDER BY agent""", (external_id,))
            return [{**dict(row), "payload": json.loads(row["payload"])} for row in rows]

    def agent_record_map(self, external_id):
        return {row["agent"].replace("repository_analyst", "repository_analysis")
                .replace("risk_compliance_agent", "risk_compliance")
                .replace("solution_planner", "solution_plan"): row["payload"]
                for row in self.agent_records_for(external_id)}

    def recent_audit(self, limit=100):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))
            return [{**dict(row), "details": json.loads(row["details"])} for row in rows]

    def record_outcome(self, opportunity_id, result, income, cost, hours, notes):
        with self.connect() as db:
            exists = db.execute("SELECT 1 FROM opportunities WHERE id=?", (opportunity_id,)).fetchone()
            if not exists:
                raise KeyError("opportunity not found")
            cursor = db.execute("INSERT INTO outcomes VALUES(NULL,?,?,?,?,?,?,?)",
                (opportunity_id, result, income, cost, hours, now(), notes))
            outcome_id = cursor.lastrowid
        self.audit("outcome_recorded", {"outcome_id": outcome_id,
                   "opportunity_id": opportunity_id, "result": result,
                   "income": income, "cost": cost, "hours": hours})
        return outcome_id

    def outcomes(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM outcomes ORDER BY id")]

    def performance_rows(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("""SELECT o.*, p.url, p.repository,
              'unknown' language FROM outcomes o LEFT JOIN opportunities p
              ON p.id=o.opportunity_id ORDER BY o.id""")]

    def save_learning_proposal(self, proposal):
        with self.connect() as db:
            db.execute("INSERT INTO learning_proposals VALUES(NULL,?,?,?)",
                       (json.dumps(proposal), proposal.get("status", "proposal_only"), now()))

    def save_experience(self, cases):
        saved = 0
        with self.connect() as db:
            for case in cases:
                cursor = db.execute("""INSERT OR IGNORE INTO experience_cases
                  VALUES(NULL,?,?,?,?,?,?,?,?,?,?)""", (case["external_id"],
                  case["sampled_year"], case["repository"], case["category"],
                  case["cycle_days"], case["comments"], json.dumps(case["labels"]),
                  case["state_reason"], case["source_url"], now()))
                saved += cursor.rowcount
        return saved

    def experience_stats(self):
        with self.connect() as db:
            row = db.execute("""SELECT COUNT(*) cases, COUNT(DISTINCT sampled_year) years,
              ROUND(AVG(cycle_days),1) average_cycle_days FROM experience_cases""").fetchone()
            categories = {r["category"]: r["count"] for r in db.execute(
                "SELECT category, COUNT(*) count FROM experience_cases GROUP BY category")}
            return {**dict(row), "categories": categories}

    def save_work_review(self, opportunity_id, decision, payload):
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM opportunities WHERE id=?", (opportunity_id,)).fetchone():
                raise KeyError("opportunity not found")
            db.execute("INSERT OR REPLACE INTO work_reviews VALUES(NULL,?,?,?,?,?)",
                (opportunity_id, decision["evidence_id"], decision["status"],
                 json.dumps(payload), now()))
        self.audit("delivery_reviewed", {"opportunity_id": opportunity_id, **decision})

    def enqueue_work(self, opportunity_id, deliberation):
        stage = ({"AUTO_APPROVE_ISOLATED_BUILD": "READY_FOR_ISOLATED_BUILD",
                  "QUEUE_FOR_DANIEL_APPROVAL": "AWAITING_DANIEL_APPROVAL"}
                 .get(deliberation["recommendation"], "TRAINING_REQUIRED"))
        with self.connect() as db:
            db.execute("""INSERT INTO work_queue VALUES(NULL,?,?,?,?,?)
              ON CONFLICT(opportunity_id) DO UPDATE SET stage=excluded.stage,
              deliberation=excluded.deliberation, updated_at=excluded.updated_at""",
              (opportunity_id, stage, json.dumps(deliberation), now(), now()))
        return stage

    def work_queue(self, limit=100):
        with self.connect() as db:
            rows = db.execute("""SELECT q.*, p.title, p.repository, p.reward,
              p.expected_value, p.url FROM work_queue q JOIN opportunities p
              ON p.id=q.opportunity_id ORDER BY p.expected_value DESC LIMIT ?""", (limit,))
            return [{**dict(row), "deliberation": json.loads(row["deliberation"])} for row in rows]

    def agent_activity(self):
        with self.connect() as db:
            records = {row["agent"]: row["count"] for row in db.execute(
                "SELECT agent, COUNT(*) count FROM agent_records GROUP BY agent")}
            scans = db.execute("SELECT COUNT(*) FROM audit_log WHERE event LIKE 'scout_%'").fetchone()[0]
            proposals = db.execute("SELECT COUNT(*) FROM learning_proposals").fetchone()[0]
            return {
                "opportunity_scout": scans,
                "repository_analyst": records.get("repository_analyst", 0),
                "risk_compliance_agent": records.get("risk_compliance_agent", 0),
                "solution_planner": records.get("solution_planner", 0),
                "performance_learner": proposals,
                "historical_experience": self.experience_stats()["cases"],
                "delivery_reviews": db.execute("SELECT COUNT(*) FROM work_reviews").fetchone()[0],
                "deep_deliberations": db.execute("SELECT COUNT(*) FROM work_queue").fetchone()[0],
                "practice": self.practice_stats(),
            }

    def stats(self):
        with self.connect() as db:
            row = db.execute("""SELECT COUNT(*) found,
              SUM(status='APPROVED') approved,
              SUM(status='REJECTED') rejected,
              COALESCE(SUM(CASE WHEN status='APPROVED' THEN expected_value ELSE 0 END),0)
              expected_value FROM opportunities""").fetchone()
            money = db.execute("SELECT COALESCE(SUM(income-cost),0) FROM outcomes").fetchone()[0]
            return {**dict(row), "realized_income": round(money, 2),
                    "agent_activity": self.agent_activity()}

    def create_client_request(self, name, email, project, budget):
        timestamp = now()
        with self.connect() as db:
            cursor = db.execute("""INSERT INTO client_requests
              (name,email,project,budget,status,payment_status,created_at,updated_at)
              VALUES(?,?,?,?,?,?,?,?)""",
              (name, email, project, budget, "NEW", "UNPAID", timestamp, timestamp))
            request_id = cursor.lastrowid
        self.audit("client_request_received", {"client_request_id": request_id})
        return request_id

    def get_client_request(self, request_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM client_requests WHERE id=?", (request_id,)).fetchone()
            return dict(row) if row else None

    def list_client_requests(self, limit=100):
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM client_requests ORDER BY id DESC LIMIT ?", (limit,))]

    def quote_client_request(self, request_id, amount_cents, description):
        with self.connect() as db:
            cursor = db.execute("""UPDATE client_requests SET status='QUOTED',
              quote_cents=?, quote_description=?, updated_at=? WHERE id=?""",
              (amount_cents, description, now(), request_id))
            if not cursor.rowcount:
                raise KeyError("client request not found")
        self.audit("client_quote_approved", {"client_request_id": request_id,
                   "amount_cents": amount_cents})

    def set_checkout_session(self, request_id, session_id):
        with self.connect() as db:
            db.execute("""UPDATE client_requests SET stripe_session_id=?,
              status='CHECKOUT_READY', updated_at=? WHERE id=?""",
              (session_id, now(), request_id))

    def mark_client_request_paid(self, session_id, payment_status):
        with self.connect() as db:
            row = db.execute("SELECT id FROM client_requests WHERE stripe_session_id=?",
                             (session_id,)).fetchone()
            if not row:
                return None
            request_id = row["id"]
            db.execute("""UPDATE client_requests SET payment_status=?, status='PAID',
              updated_at=? WHERE id=?""", (payment_status, now(), request_id))
        self.audit("client_payment_confirmed", {"client_request_id": request_id,
                   "stripe_session_id": session_id})
        return request_id


def now():
    return datetime.now(timezone.utc).isoformat()
