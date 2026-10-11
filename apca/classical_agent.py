"""Classical rule-based compliance checker (the syllabus-style baseline for Part C).

A simple reflex agent: percept = the submission text, condition-action rules =
a hand-written keyword table for ONE specific policy (IA2). No LLM, no planning,
no memory, a single pass, and a binary pass/fail per rule.

It is deliberately written the way a classical agent would be, so that its
limitations can be compared with the LLM agent on the same inputs.
"""

from __future__ import annotations

from .documents import read_document

# condition -> action rules, hand-coded for the IA2 instructions only
RULES = [
    ("R01", "Goal of the agent explained", ["goal"]),
    ("R02", "Agent role explained", ["role"]),
    ("R03", "Tools used listed", ["tools"]),
    ("R04", "Memory type explained", ["memory"]),
    ("R05", "Planning strategy explained", ["planning", "react"]),
    ("R06", "LLM-based agent used", ["llm", "gpt", "llama", "gemini"]),
    ("R07", "At least two tools", ["tool"]),
    ("R08", "Architecture diagram", ["architecture"]),
    ("R09", "Tool flow diagram", ["tool flow"]),
    ("R10", "Interaction logs / traces", ["log"]),
    ("R11", "Prompts and output screenshots", ["screenshot"]),
    ("R12", "Code repository / notebook", ["github", "notebook"]),
    ("R13", "Classical vs modern comparison", ["classical"]),
    ("R14", "Conclusion", ["conclusion"]),
    ("R15", "References", ["references"]),
]


def classical_check(submission_path: str) -> dict:
    doc = read_document(submission_path)
    text = doc.text().lower()
    results = []
    for rid, name, keywords in RULES:
        hit = next((k for k in keywords if k in text), None)  # IF keyword present THEN pass
        results.append({"id": rid, "requirement": name, "status": "PASS" if hit else "FAIL", "matched": hit})
    passed = sum(r["status"] == "PASS" for r in results)
    return {
        "agent": "classical rule-based",
        "submission": doc.summary()["file"],
        "results": results,
        "passed": passed,
        "total": len(results),
        "score_percent": round(100 * passed / len(results), 1),
    }


if __name__ == "__main__":
    import json
    import sys

    print(json.dumps(classical_check(sys.argv[1]), indent=2))
