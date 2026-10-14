"""The LLM compliance agent: a ReAct (Reason -> Act -> Observe) loop.

    User goal -> LLM thought + plan -> tool call -> observation -> next thought ... -> final answer

The LLM decides which tool to call next; Python executes the tool and feeds
the observation back. Guardrails stop the agent from finishing before every
requirement has an evidence-backed verdict.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import prompts
from .memory import MemoryStore
from .scoring import calculate_compliance_score, normalize_status, prioritized_actions
from .tools import ToolError, Workspace, execute, tool_descriptions
from .trace import Tracer

MAX_OBS_CHARS = 9000      # observation size sent to the LLM
OLD_OBS_CHARS = 700       # older observations are compressed to this size
KEEP_RECENT = 4           # number of most recent observations kept in full


def parse_reply(text: str) -> dict:
    """Extract the first JSON object from a model reply (tolerates code fences / chatter)."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        obj = json.loads(t)
    except json.JSONDecodeError:
        start = t.find("{")
        if start < 0:
            raise ValueError("no JSON object found")
        depth, in_str, esc = 0, False, False
        for i, ch in enumerate(t[start:], start):
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    obj = json.loads(t[start : i + 1])
                    break
        else:
            raise ValueError("unbalanced JSON object")
    if not isinstance(obj, dict):
        raise ValueError("reply is not a JSON object")
    if "action" not in obj and "final_answer" not in obj:
        raise ValueError("missing 'action' or 'final_answer'")
    if "action" in obj and not isinstance(obj.get("action_input", {}), dict):
        raise ValueError("'action_input' must be an object")
    return obj


class ComplianceAgent:
    def __init__(self, llm, memory: MemoryStore, tracer: Tracer, max_steps: int = 20):
        self.llm = llm
        self.memory = memory
        self.tracer = tracer
        self.max_steps = max_steps

    # ------------------------------------------------------------------ run
    def run(self, policy_path: str, submission_path: str, goal: str | None = None) -> dict:
        goal = goal or prompts.DEFAULT_GOAL
        ws = Workspace(files={"policy": str(policy_path), "submission": str(submission_path)}, memory=self.memory)
        log = self.tracer.log
        log("goal", goal, files={"policy": Path(policy_path).name, "submission": Path(submission_path).name})

        messages = [
            {"role": "system", "content": prompts.SYSTEM_PROMPT.format(tools=tool_descriptions())},
            {"role": "user", "content": prompts.USER_GOAL.format(
                goal=goal, policy_name=Path(policy_path).name, submission_name=Path(submission_path).name)},
        ]
        final_answer, bad_replies, step = None, 0, 0

        while step < self.max_steps:
            step += 1
            raw = self.llm.chat(self._compressed(messages))
            try:
                reply = parse_reply(raw)
            except ValueError as e:
                bad_replies += 1
                log("error", f"Unparseable reply ({e}): {raw[:300]}", step)
                if bad_replies >= 3:
                    break
                messages += [{"role": "assistant", "content": raw},
                             {"role": "user", "content": prompts.FORMAT_REMINDER.format(error=e)}]
                continue
            messages.append({"role": "assistant", "content": json.dumps(reply, ensure_ascii=False)})

            if reply.get("plan"):
                log("plan", reply["plan"], step)
            if reply.get("thought"):
                log("thought", reply["thought"], step)

            if "final_answer" in reply and "action" not in reply:
                missing = self._missing_before_finish(ws)
                if missing:
                    log("info", "Guardrail: finish blocked - " + missing, step)
                    messages.append({"role": "user", "content": prompts.FINISH_BLOCKED.format(missing=missing)})
                    continue
                final_answer = reply["final_answer"]
                log("final", final_answer, step)
                break

            name, args = reply["action"], reply.get("action_input", {}) or {}
            log("tool_call", name, step, args=args)
            try:
                obs = execute(ws, name, args)
                if name in ("recall_policy_memory", "save_checklist", "compare_with_previous_audit"):
                    log("memory", f"{name}: " + ("hit" if obs.get("found") or obs.get("saved") else "miss"), step)
            except ToolError as e:
                obs = {"error": str(e)}
            except Exception as e:  # noqa: BLE001 - report any tool crash back to the agent
                obs = {"error": f"{type(e).__name__}: {e}"}
            log("observation", obs, step, tool=name)
            obs_text = json.dumps(obs, ensure_ascii=False, default=str)
            if len(obs_text) > MAX_OBS_CHARS:
                obs_text = obs_text[:MAX_OBS_CHARS] + ' ..."[truncated - request fewer items per call]"'
            messages.append({"role": "user", "content": f"Observation ({name}): {obs_text}"})

        if final_answer is None:
            final_answer = self._fallback_finish(ws, step)

        return self._result(ws, final_answer, step)

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _compressed(messages: list[dict]) -> list[dict]:
        """Short-term memory management: keep recent observations in full,
        shrink older ones (their full data stays in the Workspace)."""
        obs_idx = [i for i, m in enumerate(messages) if m["role"] == "user" and m["content"].startswith("Observation")]
        old = set(obs_idx[:-KEEP_RECENT])
        out = []
        for i, m in enumerate(messages):
            if i in old and len(m["content"]) > OLD_OBS_CHARS:
                m = {"role": m["role"], "content": m["content"][:OLD_OBS_CHARS] + ' ..."[older observation compressed]"'}
            out.append(m)
        return out

    @staticmethod
    def _missing_before_finish(ws: Workspace) -> str:
        if not ws.checklist:
            return "no checklist has been saved (use save_checklist or recall_policy_memory)"
        todo = [r["id"] for r in ws.checklist if r["id"] not in ws.assessments]
        if todo:
            return f"requirements without a verdict: {todo} (use find_evidence then record_assessments)"
        if ws.format_result is None:
            return "check_format has not been run"
        if ws.consistency_result is None:
            return "check_consistency has not been run"
        if ws.score is None:
            return "calculate_compliance_score has not been run since the last assessments were recorded"
        return ""

    def _fallback_finish(self, ws: Workspace, step: int) -> str:
        """Agent ran out of steps: close the audit deterministically and say so."""
        self.tracer.log("info", "Step budget exhausted - completing audit with deterministic fallback.", step)
        for r in ws.checklist:
            ws.assessments.setdefault(r["id"], {
                "status": "Not Verifiable", "evidence": "", "page": None, "confidence": 0.0,
                "reason": "Agent did not reach a verdict within the step budget.",
                "suggested_fix": "Review manually."})
        if ws.checklist:
            ws.score = calculate_compliance_score(ws.checklist, ws.assessments, ws.rubric or None)
        msg = "The agent stopped before finishing; unassessed items are marked Not Verifiable. Review manually."
        self.tracer.log("final", msg, step)
        return msg

    def _result(self, ws: Workspace, final_answer: str, steps: int) -> dict:
        if ws.checklist and ws.assessments and ws.score is None:
            ws.score = calculate_compliance_score(ws.checklist, ws.assessments, ws.rubric or None)
        if ws.comparison is not None and ws.assessments:
            # the agent may have compared before its last verdicts - recompute from the final ones
            execute(ws, "compare_with_previous_audit", {})
        for a in ws.assessments.values():
            a["status"] = normalize_status(a["status"])
        sub = ws.docs.get("submission")
        pol = ws.docs.get("policy")
        return {
            "run_id": self.tracer.run_id,
            "final_answer": final_answer,
            "steps": steps,
            "policy": pol.summary() | {"sha1": pol.sha1} if pol else {"file": Path(ws.files["policy"]).name},
            "submission": sub.summary() | {"sha1": sub.sha1} if sub else {"file": Path(ws.files["submission"]).name},
            "policy_from_memory": ws.policy_from_memory,
            "checklist": ws.checklist,
            "rubric": ws.rubric,
            "format_rules": ws.format_rules,
            "assessments": ws.assessments,
            "evidence": ws.evidence,
            "format": ws.format_result,
            "consistency": ws.consistency_result,
            "score": ws.score,
            "actions": prioritized_actions(ws.checklist, ws.assessments) if ws.checklist else [],
            "comparison": ws.comparison,
            "tool_usage": ws.tool_counts,
            "llm_usage": self.llm.usage(),
            "logs": {"jsonl": str(self.tracer.jsonl_path), "markdown": str(self.tracer.md_path)},
        }
