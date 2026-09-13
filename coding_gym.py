"""Private, isolated coding drills for idle-time engineering practice."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Callable

from diagnostic_toolchain import DiagnosticPolicy, DiagnosticToolchain


@dataclass(frozen=True)
class Exercise:
    exercise_id: str
    category: str
    difficulty: int
    starter: str
    solution: str
    tests: str
    lesson: str
    language: str = "python"


EXERCISES = (
    Exercise(
        "normalize-repository", "data_cleaning", 1,
        "def normalize(value):\n    return value\n",
        "def normalize(value):\n    return '/'.join(part.strip().lower() for part in value.split('/') if part.strip())\n",
        "from unittest import TestCase\nfrom solution import normalize\n\nclass T(TestCase):\n    def test_normalizes(self):\n        self.assertEqual('owner/repo', normalize(' Owner / Repo '))\n    def test_removes_empty_segments(self):\n        self.assertEqual('a/b', normalize('a//b'))\n",
        "Normalize at system boundaries and test whitespace, case, and empty segments.",
    ),
    Exercise(
        "stable-deduplication", "algorithm", 2,
        "def unique(values):\n    return list(set(values))\n",
        "def unique(values):\n    return list(dict.fromkeys(values))\n",
        "from unittest import TestCase\nfrom solution import unique\n\nclass T(TestCase):\n    def test_deduplicates_without_reordering(self):\n        self.assertEqual([3, 1, 2], unique([3, 1, 3, 2, 1]))\n",
        "Preserve ordering when deduplicating user-visible or priority-ranked data.",
    ),
    Exercise(
        "bounded-retry", "reliability", 3,
        "def call_with_retry(call, attempts=3):\n    return call()\n",
        "def call_with_retry(call, attempts=3):\n    if attempts < 1:\n        raise ValueError('attempts must be positive')\n    last = None\n    for _ in range(attempts):\n        try:\n            return call()\n        except RuntimeError as exc:\n            last = exc\n    raise last\n",
        "from unittest import TestCase\nfrom solution import call_with_retry\n\nclass T(TestCase):\n    def test_retries_then_succeeds(self):\n        calls=[]\n        def work():\n            calls.append(1)\n            if len(calls)<3: raise RuntimeError('temporary')\n            return 'ok'\n        self.assertEqual('ok', call_with_retry(work))\n        self.assertEqual(3, len(calls))\n    def test_rejects_unbounded_configuration(self):\n        with self.assertRaises(ValueError): call_with_retry(lambda: None, 0)\n",
        "Retries must be bounded, validate configuration, and preserve the last failure.",
    ),
    Exercise(
        "money-integer-cents", "correctness", 4,
        "def total_cents(lines):\n    return int(sum(qty * price for qty, price in lines) * 100)\n",
        "def total_cents(lines):\n    total = 0\n    for quantity, unit_cents in lines:\n        if quantity < 0 or unit_cents < 0:\n            raise ValueError('negative invoice value')\n        total += quantity * unit_cents\n    return total\n",
        "from unittest import TestCase\nfrom solution import total_cents\n\nclass T(TestCase):\n    def test_uses_integer_cents(self):\n        self.assertEqual(1097, total_cents([(3, 299), (1, 200)]))\n    def test_rejects_negative_values(self):\n        with self.assertRaises(ValueError): total_cents([(-1, 100)])\n",
        "Represent money as integer cents and reject invalid negative inputs.",
    ),
    Exercise(
        "node-invoice-rounding", "javascript_correctness", 5,
        "export function invoiceTotal(lines) {\n  return lines.reduce((sum, [qty, price]) => sum + qty * price, 0);\n}\n",
        "export function invoiceTotal(lines) {\n  return lines.reduce((sum, [qty, cents]) => {\n    if (!Number.isInteger(qty) || !Number.isInteger(cents) || qty < 0 || cents < 0) throw new RangeError('invalid invoice line');\n    return sum + qty * cents;\n  }, 0);\n}\n",
        "import test from 'node:test';\nimport assert from 'node:assert/strict';\nimport { invoiceTotal } from './solution.mjs';\n\ntest('totals integer cents', () => assert.equal(invoiceTotal([[3, 299], [1, 200]]), 1097));\ntest('rejects invalid lines', () => assert.throws(() => invoiceTotal([[-1, 100]]), RangeError));\n",
        "Use integer cents and validate invoice inputs in JavaScript before calculating totals.",
        "node",
    ),
)


class CodingGym:
    """Run fail-then-pass drills and emit evidence without retaining source code."""

    def __init__(self, execute: Callable[[dict[str, str], str], dict]):
        self.execute = execute
        self.diagnostics = DiagnosticToolchain(execute, DiagnosticPolicy(max_attempts=2))

    def run(self, sequence: int) -> dict:
        exercise = EXERCISES[sequence % len(EXERCISES)]
        source_name = "solution.mjs" if exercise.language == "node" else "solution.py"
        test_name = "solution.test.mjs" if exercise.language == "node" else "test_solution.py"
        initial = {source_name: exercise.starter, test_name: exercise.tests}
        diagnosis = self.diagnostics.run(initial, lambda files, _failure, _attempt: {
            **files, source_name: exercise.solution,
        })
        attempts = diagnosis["attempts"]
        baseline_status = attempts[0]["status"]
        repair_status = attempts[-1]["status"] if len(attempts) > 1 else "NOT_ATTEMPTED"
        baseline_failed = baseline_status == "FAILED"
        repair_passed = repair_status == "PASSED"
        score = (40 if baseline_failed else 0) + (60 if repair_passed else 0)
        evidence = hashlib.sha256(
            f"{sequence}:{exercise.exercise_id}:{baseline_status}:{repair_status}".encode()
        ).hexdigest()[:20]
        return {
            "exercise_id": exercise.exercise_id,
            "sequence": sequence,
            "category": exercise.category,
            "difficulty": exercise.difficulty,
            "language": exercise.language,
            "baseline_status": baseline_status,
            "repair_status": repair_status,
            "score": score,
            "verified_pass": baseline_failed and repair_passed,
            "lesson": exercise.lesson,
            "evidence_id": evidence,
            "network": diagnosis.get("network", "unknown"),
            "isolation": diagnosis.get("isolation", "unknown"),
            "attempt_count": diagnosis.get("attempt_count", len(attempts)),
            "failure_classification": diagnosis.get("classification", "unknown"),
            "practice_only": True,
        }
