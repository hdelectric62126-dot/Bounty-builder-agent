"""Adaptive, deterministic scheduling for sandbox-verified practice."""

from collections import defaultdict


def plan_training(exercises, history, rounds):
    """Prioritize missing evidence, weak languages, then the stalest skill."""
    if rounds < 1 or not exercises:
        return []
    stats = defaultdict(lambda: {"attempts": 0, "passes": 0, "last": -1})
    language_passes = defaultdict(int)
    maximum_sequence = -1
    for result in history:
        exercise_id = str(result.get("exercise_id") or "")
        if not exercise_id:
            continue
        sequence = int(result.get("sequence", -1))
        passed = bool(result.get("verified_pass"))
        stats[exercise_id]["attempts"] += 1
        stats[exercise_id]["passes"] += int(passed)
        stats[exercise_id]["last"] = max(stats[exercise_id]["last"], sequence)
        if passed:
            language_passes[str(result.get("language") or "unknown")] += 1
        maximum_sequence = max(maximum_sequence, sequence)

    ranked = sorted(enumerate(exercises), key=lambda pair: (
        stats[pair[1].exercise_id]["passes"] > 0,
        language_passes[pair[1].language] >= 3,
        stats[pair[1].exercise_id]["passes"] >= 2,
        stats[pair[1].exercise_id]["last"],
        -pair[1].difficulty,
        pair[0],
    ))
    count = min(rounds, len(ranked))
    generation = maximum_sequence // len(exercises) + 1
    planned = []
    for position, (index, exercise) in enumerate(ranked[:count]):
        sequence = (generation + position) * len(exercises) + index
        planned.append({
            "sequence": sequence,
            "exercise_id": exercise.exercise_id,
            "category": exercise.category,
            "language": exercise.language,
            "difficulty": exercise.difficulty,
            "reason": _reason(stats[exercise.exercise_id], language_passes[exercise.language]),
        })
    return planned


def _reason(stat, language_passes):
    if stat["passes"] == 0:
        return "UNVERIFIED_SKILL"
    if language_passes < 3:
        return "LANGUAGE_EVIDENCE_GAP"
    if stat["passes"] < 2:
        return "MASTERY_CONFIRMATION"
    return "SPACED_REFRESH"
