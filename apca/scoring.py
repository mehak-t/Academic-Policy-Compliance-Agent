"""Advisory compliance score.

score = sum(weight * status_value) / sum(weight) * 100

Not Applicable items are excluded from the denominator. Not Verifiable items
count as 0 by default (configurable), because "we could not find it" should
still push the student to make the evidence visible.
"""

from __future__ import annotations

from collections import defaultdict

STATUS_VALUES = {
    "Satisfied": 1.0,
    "Partially Satisfied": 0.5,
    "Not Satisfied": 0.0,
    "Not Verifiable": 0.0,
    "Not Applicable": None,
}

PRIORITY_RANK = {"High": 0, "Medium": 1, "Low": 2}


def normalize_status(s: str) -> str:
    s = (s or "").strip().lower().replace("_", " ")
    for k in STATUS_VALUES:
        if s == k.lower():
            return k
    if s.startswith("partial"):
        return "Partially Satisfied"
    if "not verif" in s or "unverif" in s:
        return "Not Verifiable"
    if "not app" in s or s == "n/a":
        return "Not Applicable"
    if s.startswith("not") or s in {"missing", "fail", "failed", "no"}:
        return "Not Satisfied"
    if s in {"met", "pass", "passed", "yes", "ok", "satisfied"}:
        return "Satisfied"
    return "Not Verifiable"


def calculate_compliance_score(checklist: list[dict], assessments: dict, rubric: dict | None = None,
                               exclude_not_verifiable: bool = False) -> dict:
    """checklist: requirement dicts (id, weight, rubric_category, priority)
    assessments: {req_id: {"status": ...}}
    rubric: {category: max_marks} -> also returns estimated marks per category.
    """
    num = den = 0.0
    counts = defaultdict(int)
    per_cat = defaultdict(lambda: [0.0, 0.0])
    rows = []
    for req in checklist:
        rid = req["id"]
        status = normalize_status(assessments.get(rid, {}).get("status", "Not Verifiable"))
        counts[status] += 1
        value = STATUS_VALUES[status]
        if value is None or (exclude_not_verifiable and status == "Not Verifiable"):
            continue
        w = float(req.get("weight", 1) or 1)
        num += w * value
        den += w
        cat = req.get("rubric_category") or "General"
        per_cat[cat][0] += w * value
        per_cat[cat][1] += w
        rows.append(f"{rid}: {w:g} x {value:g}")

    score = round(100 * num / den, 1) if den else 0.0
    result = {
        "score_percent": score,
        "status_counts": dict(counts),
        "formula": "sum(weight x status_value) / sum(weight) x 100",
        "status_values": {k: v for k, v in STATUS_VALUES.items()},
        "terms": rows,
        "category_coverage": {c: round(100 * a / b, 1) if b else 0 for c, (a, b) in per_cat.items()},
    }
    if rubric:
        marks = {}
        for cat, max_marks in rubric.items():
            a, b = per_cat.get(cat, (0, 0))
            marks[cat] = {"max": max_marks, "estimated": round(max_marks * a / b, 1) if b else None}
        known = [m["estimated"] for m in marks.values() if m["estimated"] is not None]
        result["rubric_estimate"] = marks
        result["estimated_total"] = round(sum(known), 1)
        result["rubric_total"] = sum(rubric.values())
        result["note"] = "Advisory estimate only - not an official grade."
    return result


def prioritized_actions(checklist: list[dict], assessments: dict) -> list[dict]:
    """Order open items: priority first, then Not Satisfied before Partial, then weight."""
    order = {"Not Satisfied": 0, "Not Verifiable": 1, "Partially Satisfied": 2}
    acts = []
    for req in checklist:
        a = assessments.get(req["id"], {})
        st = normalize_status(a.get("status", "Not Verifiable"))
        if st not in order:
            continue
        acts.append(
            {
                "id": req["id"],
                "requirement": req["description"],
                "status": st,
                "priority": req.get("priority", "Medium"),
                "action": a.get("suggested_fix") or f"Add clear evidence for: {req['description']}",
                "_key": (PRIORITY_RANK.get(req.get("priority", "Medium"), 1), order[st], -float(req.get("weight", 1) or 1)),
            }
        )
    acts.sort(key=lambda x: x["_key"])
    for i, a in enumerate(acts, 1):
        a.pop("_key")
        a["rank"] = i
    return acts
