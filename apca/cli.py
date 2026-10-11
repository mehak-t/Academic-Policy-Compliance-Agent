"""Command line interface.

    python -m apca.cli audit --policy samples/policies/IA2_instructions.md --submission samples/submissions/report_v1.docx
"""

from __future__ import annotations

import argparse
import sys

from .config import load_settings
from .llm import LLMError
from .pipeline import approve_and_export, run_audit


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(prog="apca", description="Academic Policy Compliance Agent")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("audit", help="audit a submission against a policy")
    a.add_argument("--policy", required=True)
    a.add_argument("--submission", required=True)
    a.add_argument("--goal", help="custom goal for the agent")
    a.add_argument("--provider")
    a.add_argument("--model")
    a.add_argument("--max-steps", type=int)
    a.add_argument("--yes", action="store_true", help="approve without asking (non-interactive)")
    a.add_argument("--reviewer", default="student")
    args = ap.parse_args(argv)

    settings = load_settings(provider=args.provider, model=args.model, max_steps=args.max_steps)
    print(f"Model: {settings.model} via {settings.provider}\n")
    try:
        result, tracer = run_audit(args.policy, args.submission, settings, goal=args.goal)
    except LLMError as e:
        print(f"LLM error: {e}\nCheck LLM_PROVIDER / LLM_API_KEY in your .env file.")
        return 2

    sc = result.get("score") or {}
    print("\n" + "=" * 70)
    print(f"Compliance score: {sc.get('score_percent')}%", end="")
    if sc.get("rubric_estimate"):
        print(f"   (rubric estimate {sc['estimated_total']}/{sc['rubric_total']})", end="")
    print("\nStatus counts:", sc.get("status_counts"))
    print("\nTop corrections:")
    for act in result["actions"][:8]:
        print(f"  {act['rank']}. [{act['priority']}] {act['id']} {act['status']}: {act['action']}")
    print("=" * 70)

    # Human-in-the-loop: nothing is saved until the reviewer approves.
    overrides = {}
    if not args.yes:
        ans = input("\nApprove this audit and export the report? [y/N/e=edit a verdict] ").strip().lower()
        while ans == "e":
            rid = input("  requirement id: ").strip()
            st = input("  new status (Satisfied/Partially Satisfied/Not Satisfied/Not Verifiable/Not Applicable): ").strip()
            overrides[rid] = st
            ans = input("Approve now? [y/N/e] ").strip().lower()
        if ans != "y":
            tracer.log("human", "Reviewer did not approve - audit not saved.")
            print(f"Not exported. Trace: {tracer.md_path}")
            return 1
    paths = approve_and_export(result, settings, args.reviewer, overrides, tracer)
    print("\nExported:")
    for k, v in paths.items():
        print(f"  {k}: {v}")
    print(f"  trace: {tracer.md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
