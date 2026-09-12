"""Outcome analysis for bounty opportunities.

This module is deliberately proposal-only.  It summarizes measured performance by
source, repository, and language, then recommends small scoring multipliers.  It
does not read or write production policy and has no promotion capability.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class PerformanceConfig:
    minimum_samples: int = 5
    maximum_adjustment: float = 0.05
    minimum_multiplier: float = 0.50
    maximum_multiplier: float = 2.00


class PerformanceLearner:
    """Measure cohort performance and return bounded, reviewable proposals."""

    dimensions = ("source", "repository", "language")

    def __init__(self, config: PerformanceConfig | None = None):
        self.config = config or PerformanceConfig()
        if self.config.minimum_samples < 2:
            raise ValueError("minimum_samples must be at least 2")
        if not 0 < self.config.maximum_adjustment <= 0.05:
            raise ValueError("maximum_adjustment must be between 0 and 0.05")

    def measure(self, outcomes: list[dict]) -> dict:
        """Return aggregate results, excluding cohorts without enough evidence."""
        buckets: dict[str, dict[str, list[dict]]] = {
            dimension: defaultdict(list) for dimension in self.dimensions
        }
        for outcome in outcomes:
            normalized = self._normalize(outcome)
            for dimension in self.dimensions:
                value = normalized[dimension]
                if value:
                    buckets[dimension][value].append(normalized)

        measured = {}
        excluded = {}
        for dimension in self.dimensions:
            measured[dimension] = {}
            excluded[dimension] = {}
            for name, rows in sorted(buckets[dimension].items()):
                summary = self._summarize(rows)
                target = (measured if len(rows) >= self.config.minimum_samples else excluded)
                target[dimension][name] = summary
        return {
            "observed": len(outcomes),
            "minimum_samples": self.config.minimum_samples,
            "cohorts": measured,
            "insufficient_evidence": excluded,
        }

    def propose(self, outcomes: list[dict], current_weights: dict | None = None) -> dict:
        """Recommend bounded multipliers; never persist or activate them."""
        report = self.measure(outcomes)
        current_weights = current_weights or {}
        recommendations = {}

        for dimension, cohorts in report["cohorts"].items():
            recommendations[dimension] = {}
            for name, summary in cohorts.items():
                current = float(current_weights.get(dimension, {}).get(name, 1.0))
                # Net-positive, frequently successful cohorts get a small boost;
                # net-negative cohorts get a small reduction; neutral stays fixed.
                signal = summary["net_income"] * summary["success_rate"]
                direction = 1 if signal > 0 else -1 if summary["net_income"] < 0 else 0
                delta = self.config.maximum_adjustment * direction
                proposed = current * (1 + delta)
                bounded = min(self.config.maximum_multiplier,
                              max(self.config.minimum_multiplier, proposed))
                recommendations[dimension][name] = {
                    "current_multiplier": round(current, 4),
                    "proposed_multiplier": round(bounded, 4),
                    "change": round(bounded - current, 4),
                    "evidence": summary,
                }

        return {
            "status": "proposal_only",
            "approval_required": True,
            "auto_promote": False,
            "recommendations": recommendations,
            "report": report,
        }

    def promote(self, *_args, **_kwargs):
        """Fail closed even if a caller attempts automatic promotion."""
        raise PermissionError("PerformanceLearner can only create proposals")

    @staticmethod
    def _normalize(outcome: dict) -> dict:
        url = str(outcome.get("url") or "")
        source = str(outcome.get("source") or urlparse(url).hostname or "unknown")
        income = float(outcome.get("income") or 0)
        cost = float(outcome.get("cost") or 0)
        return {
            **outcome,
            "source": source.lower(),
            "repository": str(outcome.get("repository") or "unknown").lower(),
            "language": str(outcome.get("language") or "unknown").lower(),
            "income": income,
            "cost": cost,
            "hours": float(outcome.get("hours") or 0),
            "net_income": income - cost,
        }

    @staticmethod
    def _summarize(rows: list[dict]) -> dict:
        samples = len(rows)
        net_income = sum(row["net_income"] for row in rows)
        hours = sum(row["hours"] for row in rows)
        wins = sum(row["net_income"] > 0 for row in rows)
        return {
            "samples": samples,
            "wins": wins,
            "success_rate": round(wins / samples, 4),
            "net_income": round(net_income, 2),
            "income_per_hour": round(net_income / hours, 2) if hours else 0.0,
        }
