from pathlib import Path

import pytest

from apca.consistency import check_consistency
from apca.documents import read_document
from apca.format_checker import check_format
from apca.memory import MemoryStore, compare_audits, submission_key
from apca.scoring import calculate_compliance_score, normalize_status, prioritized_actions
from apca.search import EvidenceIndex
from apca.tools import TOOLS, ToolError, Workspace, execute

ROOT = Path(__file__).resolve().parent.parent
POLICY = ROOT / "samples/policies/IA2_instructions.md"
V1 = ROOT / "samples/submissions/travel_agent_report_v1.docx"
V2 = ROOT / "samples/submissions/travel_agent_report_v2.docx"
V2PDF = ROOT / "samples/submissions/travel_agent_report_v2.pdf"


def test_read_formats():
    pol = read_document(POLICY)
    assert pol.file_type == "md" and any("Evaluation Rubrics" in h.text for h in pol.headings)
    v2 = read_document(V2)
    assert v2.image_count == 3 and v2.table_count == 1 and v2.code_count == 1
    pdf = read_document(V2PDF)
    assert pdf.pages >= 2 and pdf.image_count >= 3 and not pdf.pages_estimated


def test_search_finds_page():
    ix = EvidenceIndex(read_document(V2))
    hits = ix.search("memory type short-term context")
    assert hits and "memory" in hits[0]["section"].lower()


def test_format_rules():
    res = check_format(read_document(V1), {"allowed_file_types": ["pdf"], "min_images": 1,
                                           "required_sections": ["Part C Analysis Comparison", "References", "Conclusion"]})
    by = {c["check"]: c["passed"] for c in res["checks"]}
    assert by["file_type"] is False and by["min_images"] is False
    assert by["section: Conclusion"] is True and by["section: References"] is False


def test_consistency_v1_vs_v2():
    tools = ["web_search", "calculator", "weather_api"]
    f1 = {f["type"] for f in check_consistency(read_document(V1), tools)["findings"]}
    assert {"claim_contradiction", "tool_not_demonstrated", "dangling_reference", "placeholder_text"} <= f1
    assert check_consistency(read_document(V2), tools)["count"] == 0


def test_scoring():
    checklist = [{"id": "A", "weight": 3, "rubric_category": "Tools", "priority": "High", "description": "a"},
                 {"id": "B", "weight": 1, "rubric_category": "Tools", "priority": "Low", "description": "b"},
                 {"id": "C", "weight": 2, "rubric_category": "Design", "priority": "Medium", "description": "c"}]
    a = {"A": {"status": "Satisfied"}, "B": {"status": "partial"}, "C": {"status": "Not Applicable"}}
    s = calculate_compliance_score(checklist, a, {"Tools": 5, "Design": 5})
    assert s["score_percent"] == pytest.approx(87.5)
    assert s["rubric_estimate"]["Design"]["estimated"] is None
    assert normalize_status("missing") == "Not Satisfied"
    acts = prioritized_actions(checklist, a)
    assert [x["id"] for x in acts] == ["B"]


def test_memory_roundtrip(tmp_path):
    m = MemoryStore(tmp_path)
    m.save_policy("abc", "p.md", [{"id": "X"}], {"T": 5}, {})
    assert m.get_policy("abc")["checklist"][0]["id"] == "X"
    m.save_audit({"submission_key": "rep", "submission_sha1": "1", "policy_sha1": "abc",
                  "assessments": {"X": {"status": "Not Satisfied"}}, "score_percent": 0})
    prev = m.last_audit("rep", "abc", exclude_sha1="2")
    diff = compare_audits(prev, {"X": {"status": "Satisfied"}}, 100)
    assert diff["fixed"][0]["id"] == "X"
    assert submission_key("My Report_v3.docx") == "my_report"


def test_tool_errors(tmp_path):
    ws = Workspace(files={"policy": str(POLICY), "submission": str(V1)}, memory=MemoryStore(tmp_path))
    with pytest.raises(ToolError):
        execute(ws, "find_evidence", {"requirement_ids": "all"})  # no checklist yet
    with pytest.raises(ToolError):
        execute(ws, "nope", {})
    assert execute(ws, "calculator", {"expression": "(5*0.5+3)/8*100"})["result"] == 68.75
    with pytest.raises(ToolError):
        execute(ws, "calculator", {"expression": "__import__('os')"})
    assert set(TOOLS) >= {"read_document", "find_evidence", "record_assessments", "calculate_compliance_score"}
