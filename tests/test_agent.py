"""End-to-end test of the ReAct loop with a scripted (offline) LLM."""

import json
from pathlib import Path

from apca.agent import ComplianceAgent, parse_reply
from apca.config import load_settings
from apca.llm import ScriptedLLM
from apca.memory import MemoryStore
from apca.pipeline import approve_and_export
from apca.trace import Tracer

ROOT = Path(__file__).resolve().parent.parent
POLICY = ROOT / "samples/policies/IA2_instructions.md"
V1 = ROOT / "samples/submissions/travel_agent_report_v1.docx"


def j(**kw):
    return json.dumps(kw)


CHECKLIST = [
    {"id": "R1", "description": "Explain memory type", "rubric_category": "Architecture & design clarity", "priority": "High",
     "weight": 2, "evidence_type": "section", "keywords": ["memory", "short-term"]},
    {"id": "R2", "description": "Include agent interaction logs", "rubric_category": "Agent reasoning & tool orchestration",
     "priority": "High", "weight": 3, "evidence_type": "log", "keywords": ["log", "tool call"]},
]

SCRIPT = [
    j(thought="Check memory first", plan=["recall", "extract", "evidence", "assess", "score"], action="recall_policy_memory", action_input={"role": "policy"}),
    j(thought="Read the policy", action="get_document_text", action_input={"role": "policy"}),
    j(thought="Save checklist", action="save_checklist", action_input={
        "requirements": CHECKLIST, "rubric": {"Architecture & design clarity": 5, "Agent reasoning & tool orchestration": 5},
        "format_rules": {"allowed_file_types": ["pdf"], "required_sections": ["References"]}}),
    "this is not json",  # agent must recover from a bad reply
    j(thought="Find evidence", action="find_evidence", action_input={"requirement_ids": "all"}),
    j(thought="Trying to finish early", final_answer="done"),  # guardrail must block this
    j(thought="Assess", action="record_assessments", action_input={"assessments": [
        {"id": "R1", "status": "Not Satisfied", "confidence": 0.9, "reason": "No memory section", "suggested_fix": "Add a Memory type subsection in Part A"},
        {"id": "R2", "status": "Partially Satisfied", "evidence": "[Tool Call] web_search('hotels in goa')", "page": 2, "confidence": 0.8,
         "reason": "Only one tool in log", "suggested_fix": "Show calls to all three tools"}]}),
    j(thought="Format", action="check_format", action_input={}),
    j(thought="Consistency", action="check_consistency", action_input={"claimed_tools": ["web_search", "calculator"]}),
    j(thought="Score", action="calculate_compliance_score", action_input={}),
    j(thought="History", action="compare_with_previous_audit", action_input={}),
    j(thought="Done", final_answer="Score 30%. Fix memory section and logs."),
]


def test_parse_reply_tolerates_fences():
    r = parse_reply('Sure!\n```json\n{"thought": "x", "action": "calculator", "action_input": {"expression": "1+1"}}\n```')
    assert r["action"] == "calculator"


def test_full_run(tmp_path):
    settings = load_settings()
    settings.memory_dir = tmp_path / "mem"
    settings.output_dir = tmp_path / "out"
    llm = ScriptedLLM(list(SCRIPT))
    tracer = Tracer(tmp_path / "logs", echo=False)
    agent = ComplianceAgent(llm, MemoryStore(settings.memory_dir), tracer, max_steps=20)
    res = agent.run(str(POLICY), str(V1))

    assert res["final_answer"].startswith("Score")
    types = [e["type"] for e in tracer.events]
    assert types[0] == "goal" and "plan" in types and "error" in types
    assert any(e["type"] == "info" and "Guardrail" in e["content"] for e in tracer.events)
    assert res["score"]["score_percent"] == 30.0  # (2*0 + 3*0.5) / 5
    assert res["actions"][0]["id"] == "R1"
    assert any(f["type"] == "tool_not_demonstrated" for f in res["consistency"]["findings"])

    # second run uses policy memory, and approval stores audit memory
    paths = approve_and_export(res, settings, "tester", overrides={"R1": "Partially Satisfied"}, tracer=tracer)
    assert Path(paths["docx"]).exists() and Path(paths["markdown"]).read_text(encoding="utf-8").count("R2") >= 1
    assert res["score"]["score_percent"] == 50.0
    llm2 = ScriptedLLM([j(thought="memory?", plan=["recall"], action="recall_policy_memory", action_input={"role": "policy"})])
    agent2 = ComplianceAgent(llm2, MemoryStore(settings.memory_dir), Tracer(tmp_path / "logs", echo=False), max_steps=3)
    res2 = agent2.run(str(POLICY), str(V1))
    assert res2["policy_from_memory"] is True and len(res2["checklist"]) == 2
