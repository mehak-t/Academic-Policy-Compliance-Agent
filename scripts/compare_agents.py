"""Part C - run the classical rule-based checker on the sample reports and,
if saved LLM-agent audits exist in outputs/, put the two side by side.

    python scripts/compare_agents.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from apca.classical_agent import classical_check  # noqa: E402

SUBMISSIONS = sorted((ROOT / "samples" / "submissions").glob("travel_agent_report_*"))


def latest_llm_audit(file_name: str) -> dict | None:
    audits = sorted((ROOT / "outputs").glob("audit_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in audits:
        data = json.loads(p.read_text(encoding="utf-8"))
        if data.get("submission", {}).get("file") == file_name:
            return data
    return None


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    rows = []
    for sub in SUBMISSIONS:
        c = classical_check(str(sub))
        llm = latest_llm_audit(sub.name)
        print(f"\n=== {sub.name} ===")
        print(f"Classical rule-based: {c['passed']}/{c['total']} rules passed ({c['score_percent']}%)")
        failed = [r["requirement"] for r in c["results"] if r["status"] == "FAIL"]
        print("  failed rules:", failed or "none")
        if llm:
            sc = llm.get("score") or {}
            print(f"LLM agent:           {sc.get('score_percent')}%  status counts {sc.get('status_counts')}")
            print(f"  consistency findings: {len((llm.get('consistency') or {}).get('findings', []))}, "
                  f"open actions: {len(llm.get('actions', []))}, agent steps: {llm.get('steps')}")
        else:
            print("LLM agent:           (no saved audit yet - run the agent and approve the audit)")
        rows.append({"submission": sub.name, "classical_percent": c["score_percent"],
                     "llm_percent": (llm or {}).get("score", {}).get("score_percent") if llm else None})
    out = ROOT / "outputs" / "agent_comparison.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"\nSaved {out}")


if __name__ == "__main__":
    main()
