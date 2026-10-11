"""Glue between the agent, the human reviewer and the exporters.

run_audit()           -> agent produces a draft audit (nothing is saved yet)
approve_and_export()  -> human may override verdicts, then the audit is saved to
                         audit memory and exported. Nothing is persisted without approval.
"""

from __future__ import annotations

from pathlib import Path

from .agent import ComplianceAgent
from .config import Settings
from .memory import MemoryStore, submission_key
from .report import export
from .scoring import calculate_compliance_score, normalize_status, prioritized_actions
from .trace import Tracer


def run_audit(policy: str, submission: str, settings: Settings, goal: str | None = None,
              llm=None, echo: bool = True, on_event=None) -> tuple[dict, Tracer]:
    if llm is None:
        from .llm import LLMClient
        llm = LLMClient(settings)
    tracer = Tracer(settings.log_dir, run_name=Path(submission).stem.replace(" ", "_")[:40], echo=echo)
    if on_event:
        tracer.on_event(on_event)
    agent = ComplianceAgent(llm, MemoryStore(settings.memory_dir), tracer, max_steps=settings.max_steps)
    return agent.run(policy, submission, goal), tracer


def apply_overrides(result: dict, overrides: dict | None, tracer: Tracer | None = None) -> dict:
    """overrides: {req_id: new_status} chosen by the human reviewer."""
    for rid, status in (overrides or {}).items():
        a = result["assessments"].get(rid)
        if not a:
            continue
        new = normalize_status(status)
        if new != a["status"]:
            if tracer:
                tracer.log("human", f"Reviewer changed {rid}: {a['status']} -> {new}")
            a["reason"] = f"[Reviewer override, agent said {a['status']}] " + a.get("reason", "")
            a["status"] = new
            a["human_override"] = True
    if result.get("checklist"):
        result["score"] = calculate_compliance_score(result["checklist"], result["assessments"], result.get("rubric") or None)
        result["actions"] = prioritized_actions(result["checklist"], result["assessments"])
        result["score"]["top_actions"] = result["actions"][:5]
    return result


def approve_and_export(result: dict, settings: Settings, approved_by: str, overrides: dict | None = None,
                       tracer: Tracer | None = None) -> dict:
    result = apply_overrides(result, overrides, tracer)
    if tracer:
        tracer.log("human", f"Audit approved by {approved_by}; saving to audit memory and exporting.")
    memory = MemoryStore(settings.memory_dir)
    memory.save_audit({
        "audit_id": f"AUD-{result['run_id']}",
        "submission_file": result["submission"].get("file"),
        "submission_key": submission_key(result["submission"].get("file", "")),
        "submission_sha1": result["submission"].get("sha1"),
        "policy_sha1": result["policy"].get("sha1"),
        "score_percent": (result.get("score") or {}).get("score_percent"),
        "assessments": {k: {"status": v["status"], "confidence": v.get("confidence")} for k, v in result["assessments"].items()},
        "approved_by": approved_by,
    })
    return export(result, settings.output_dir, approved_by)
