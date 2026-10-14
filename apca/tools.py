"""Tools the LLM agent can call.

Every tool is a plain Python function that works on a shared Workspace
(the agent's short-term / working memory) and returns a JSON-serialisable
observation. The registry also produces the tool descriptions that go
into the system prompt.
"""

from __future__ import annotations

import ast
import operator
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .consistency import check_consistency as _check_consistency
from .documents import Document, read_document as _read_document
from .format_checker import check_format as _check_format
from .memory import MemoryStore, compare_audits, submission_key
from .scoring import calculate_compliance_score as _score, normalize_status, prioritized_actions
from .search import EvidenceIndex

EVIDENCE_TYPES = {"text", "section", "figure", "table", "log", "code", "screenshot", "link"}
PRIORITIES = {"High", "Medium", "Low"}


@dataclass
class Workspace:
    files: dict[str, str]  # role -> path
    memory: MemoryStore
    docs: dict[str, Document] = field(default_factory=dict)
    indexes: dict[str, EvidenceIndex] = field(default_factory=dict)
    checklist: list[dict] = field(default_factory=list)
    rubric: dict = field(default_factory=dict)
    format_rules: dict = field(default_factory=dict)
    policy_from_memory: bool = False
    evidence: dict = field(default_factory=dict)
    assessments: dict = field(default_factory=dict)
    format_result: dict | None = None
    consistency_result: dict | None = None
    score: dict | None = None
    comparison: dict | None = None
    tool_counts: dict = field(default_factory=dict)

    def doc(self, role: str) -> Document:
        role = role.lower().strip()
        if role not in self.files:
            raise ToolError(f"Unknown document role '{role}'. Available: {list(self.files)}")
        if role not in self.docs:
            self.docs[role] = _read_document(self.files[role], doc_id=role)
        return self.docs[role]

    def index(self, role: str = "submission") -> EvidenceIndex:
        if role not in self.indexes:
            self.indexes[role] = EvidenceIndex(self.doc(role))
        return self.indexes[role]

    def req(self, rid: str) -> dict | None:
        return next((r for r in self.checklist if r["id"] == rid), None)


class ToolError(Exception):
    pass


@dataclass
class Tool:
    name: str
    description: str
    params: dict  # name -> description
    fn: Callable

    def signature(self) -> str:
        args = ", ".join(self.params)
        lines = [f"- {self.name}({args}): {self.description}"]
        for p, d in self.params.items():
            lines.append(f"    * {p}: {d}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def t_read_document(ws: Workspace, role: str) -> dict:
    d = ws.doc(role)
    out = d.summary()
    out["role"] = role
    if role == "policy":
        if ws.memory.get_policy(d.sha1) and not ws.checklist:
            out["policy_memory"] = "A checklist for this exact policy file is already stored - call recall_policy_memory instead of re-extracting it."
        else:
            out["hint"] = "Call get_document_text('policy') to read the full instructions before building the checklist."
    return out


def t_get_document_text(ws: Workspace, role: str, start_page: int = 1, end_page: int | None = None, max_chars: int = 12000) -> dict:
    d = ws.doc(role)
    text = d.text(int(start_page or 1), int(end_page) if end_page else None)
    truncated = len(text) > max_chars
    return {"role": role, "pages": f"{start_page}-{end_page or d.pages}", "text": text[:max_chars],
            "truncated": truncated, "note": "Request later pages separately." if truncated else ""}


def t_recall_policy_memory(ws: Workspace, role: str = "policy") -> dict:
    d = ws.doc(role)
    mem = ws.memory.get_policy(d.sha1)
    if not mem:
        return {"found": False, "message": "No checklist stored for this policy file yet. Extract it with save_checklist."}
    ws.checklist = mem["checklist"]
    ws.rubric = mem.get("rubric", {})
    ws.format_rules = mem.get("format_rules", {})
    ws.policy_from_memory = True
    return {
        "found": True,
        "saved_at": mem["saved_at"],
        "requirements": [f'{r["id"]} [{r["priority"]}] {r["description"]}' for r in ws.checklist],
        "rubric": ws.rubric,
        "format_rules": ws.format_rules,
        "message": "Checklist loaded from policy memory; no need to re-extract.",
    }


def t_save_checklist(ws: Workspace, requirements: list, rubric: dict | None = None, format_rules: dict | None = None) -> dict:
    if not isinstance(requirements, list) or not requirements:
        raise ToolError("requirements must be a non-empty list of objects")
    clean, problems, seen = [], [], set()
    for i, r in enumerate(requirements, 1):
        if not isinstance(r, dict) or not r.get("description"):
            problems.append(f"item {i} has no description")
            continue
        rid = str(r.get("id") or f"REQ-{i:02d}").strip()
        if rid in seen:
            rid = f"{rid}-{i}"
        seen.add(rid)
        pr = str(r.get("priority", "Medium")).title()
        ev = str(r.get("evidence_type", "text")).lower()
        kws = r.get("keywords") or []
        if isinstance(kws, str):
            kws = [k.strip() for k in kws.split(",")]
        try:
            weight = float(r.get("weight", 1))
        except (TypeError, ValueError):
            weight = 1.0
        clean.append({
            "id": rid,
            "description": str(r["description"]).strip(),
            "category": str(r.get("category", "General")),
            "rubric_category": str(r.get("rubric_category") or r.get("category") or "General"),
            "priority": pr if pr in PRIORITIES else "Medium",
            "weight": max(0.5, min(weight, 5.0)),
            "evidence_type": ev if ev in EVIDENCE_TYPES else "text",
            "keywords": [str(k) for k in kws][:10],
            "source": str(r.get("source", "")),
        })
    if len(clean) < 10:
        raise ToolError(f"Only {len(clean)} requirements - split compound items so each one is a single checkable "
                        "requirement (aim for 10-20, e.g. goal, role, tools, memory and planning are separate items). Nothing was saved.")
    rubric = {str(k): float(v) for k, v in (rubric or {}).items() if _is_num(v)}
    unknown_cats = sorted({r["rubric_category"] for r in clean} - set(rubric)) if rubric else []
    if unknown_cats:
        # marks can only be estimated if every item maps onto a real rubric component
        raise ToolError(f"rubric_category values {unknown_cats} are not rubric components. "
                        f"Use exactly one of {list(rubric)} for every item (keep Part A/B/C in 'category'). Nothing was saved.")
    ws.checklist, ws.rubric, ws.format_rules = clean, rubric, format_rules or {}
    pol = ws.doc("policy")
    ws.memory.save_policy(pol.sha1, Path(pol.path).name, clean, rubric, ws.format_rules)
    return {
        "saved": len(clean),
        "ids": [r["id"] for r in clean],
        "rubric": rubric,
        "format_rules": ws.format_rules,
        "warnings": problems,
        "stored_in_policy_memory": True,
    }


def _signals(ws: Workspace, req: dict, hits: list[dict]) -> dict:
    d = ws.doc("submission")
    et = req["evidence_type"]
    sig = {}
    if et in ("figure", "screenshot"):
        pages = {h["page"] for h in hits}
        sig["images_total"] = d.image_count
        sig["images_on_hit_pages"] = sum(1 for b in d.blocks if b.kind == "image" and b.page in pages)
        caps = [b for b in d.blocks if b.kind == "caption"]
        words = set(w.lower() for k in req["keywords"] for w in k.split()) | ({"screenshot", "output"} if et == "screenshot" else {"diagram", "architecture"})
        sig["matching_captions"] = [f"p{b.page}: {b.text[:90]}" for b in caps if words & set(b.text.lower().split())][:4]
    elif et == "table":
        sig["tables_total"] = d.table_count
    elif et in ("log", "code"):
        logs = [b for b in d.blocks if b.kind == "code" or re.search(r"\[(tool call|observation)\]|thought:|observation:", b.text, re.I)]
        sig["code_or_log_blocks"] = len(logs)
        sig["log_pages"] = sorted({b.page for b in logs})[:10]
    elif et == "link":
        links = re.findall(r"https?://\S+|github\.com/\S+", d.text())
        sig["links"] = links[:5]
    return sig


def t_find_evidence(ws: Workspace, requirement_ids: list | str = "all", top_k: int = 2) -> dict:
    if not ws.checklist:
        raise ToolError("No checklist yet. Build it with save_checklist (or recall_policy_memory) first.")
    ids = [r["id"] for r in ws.checklist] if requirement_ids in ("all", None, []) else list(requirement_ids)
    ix = ws.index("submission")
    results = []
    for rid in ids:
        req = ws.req(rid)
        if not req:
            results.append({"id": rid, "error": "unknown requirement id"})
            continue
        query = req["description"] + " " + " ".join(req["keywords"])
        hits = ix.search(query, top_k=int(top_k))
        for h in hits:
            h["snippet"] = h["snippet"][:180]
        sig = _signals(ws, req, hits)
        best = hits[0]["score"] if hits else 0
        strength = "strong" if best >= 8 else "weak" if best >= 3 else "none"
        ws.evidence[rid] = {"hits": hits, "signals": sig, "strength": strength}
        results.append({"id": rid, "evidence_type": req["evidence_type"], "match_strength": strength, "hits": hits, **({"signals": sig} if sig else {})})
    return {"searched": len(results), "results": results,
            "note": "match_strength is lexical only - judge the snippets yourself; use search_submission to dig deeper on weak items."}


def t_search_submission(ws: Workspace, query: str, top_k: int = 4) -> dict:
    hits = ws.index("submission").search(query, top_k=int(top_k))
    return {"query": query, "hits": hits}


def t_check_format(ws: Workspace, rules: dict | None = None) -> dict:
    rules = rules or ws.format_rules
    if not rules:
        raise ToolError("No format rules given and none saved with the checklist.")
    ws.format_result = _check_format(ws.doc("submission"), rules)
    return ws.format_result


def t_check_consistency(ws: Workspace, claimed_tools: list | None = None) -> dict:
    ws.consistency_result = _check_consistency(ws.doc("submission"), claimed_tools or [])
    return ws.consistency_result


def t_record_assessments(ws: Workspace, assessments: list) -> dict:
    if isinstance(assessments, dict):
        assessments = [assessments]
    saved, errors = [], []
    for a in assessments:
        rid = str(a.get("id", "")).strip()
        if not ws.req(rid):
            errors.append(f"unknown id {rid!r}")
            continue
        status = normalize_status(a.get("status", ""))
        try:
            conf = max(0.0, min(1.0, float(a.get("confidence", 0.7))))
        except (TypeError, ValueError):
            conf = 0.7
        page = a.get("page")
        ws.assessments[rid] = {
            "status": status,
            "evidence": str(a.get("evidence", "")).strip()[:400],
            "page": page if isinstance(page, int) or (isinstance(page, str) and page.isdigit()) else None,
            "confidence": round(conf, 2),
            "reason": str(a.get("reason", "")).strip()[:400],
            "suggested_fix": str(a.get("suggested_fix", "")).strip()[:400],
        }
        if status in ("Satisfied", "Partially Satisfied") and not ws.assessments[rid]["evidence"]:
            errors.append(f"{rid}: status {status} needs an evidence quote")
        saved.append(rid)
    if saved:
        ws.score = None  # verdicts changed -> score must be recalculated
    remaining = [r["id"] for r in ws.checklist if r["id"] not in ws.assessments]
    return {"recorded": saved, "errors": errors, "remaining_unassessed": remaining}


def t_calculate_compliance_score(ws: Workspace) -> dict:
    if not ws.assessments:
        raise ToolError("Nothing assessed yet. Use record_assessments first.")
    ws.score = _score(ws.checklist, ws.assessments, ws.rubric or None)
    ws.score["top_actions"] = prioritized_actions(ws.checklist, ws.assessments)[:5]
    return ws.score


def t_compare_with_previous_audit(ws: Workspace) -> dict:
    sub = ws.doc("submission")
    key = submission_key(Path(sub.path).name)
    prev = ws.memory.last_audit(key, policy_sha1=ws.doc("policy").sha1, exclude_sha1=sub.sha1)
    if not prev:
        return {"found": False, "submission_key": key, "message": "No earlier approved audit of this submission in memory."}
    cur = ws.score["score_percent"] if ws.score else None
    ws.comparison = compare_audits(prev, ws.assessments, cur)
    ws.comparison["found"] = True
    return ws.comparison


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.USub: operator.neg, ast.Mod: operator.mod}


def t_calculator(ws: Workspace, expression: str) -> dict:
    def ev(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.operand))
        raise ToolError("Only arithmetic is allowed")
    val = ev(ast.parse(str(expression), mode="eval").body)
    return {"expression": expression, "result": round(val, 4)}


def _is_num(v) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool("read_document", "Load a document and get its structure (pages, headings, images, tables).",
             {"role": "'policy' or 'submission'"}, t_read_document),
        Tool("get_document_text", "Read the text of a document (page range optional).",
             {"role": "'policy' or 'submission'", "start_page": "optional int", "end_page": "optional int"}, t_get_document_text),
        Tool("recall_policy_memory", "Look up a checklist previously extracted from this exact policy file (long-term memory).",
             {"role": "'policy'"}, t_recall_policy_memory),
        Tool("save_checklist", "Store the structured compliance checklist you extracted from the policy (also saved to policy memory).",
             {"requirements": "list of {id, description, category, rubric_category, priority(High|Medium|Low), weight(1-3), evidence_type(text|section|figure|table|log|code|screenshot|link), keywords[list], source}",
              "rubric": "object {rubric category: marks} if the policy has a marking rubric, else {}",
              "format_rules": "object with any of: allowed_file_types[list], min_pages, max_pages, min_images, min_tables, require_code(bool), required_sections[list]"},
             t_save_checklist),
        Tool("find_evidence", "Search the submission for evidence of each checklist requirement; returns snippets with page numbers.",
             {"requirement_ids": "list of ids or 'all'"}, t_find_evidence),
        Tool("search_submission", "Free-text search inside the submission (use to double-check weak or missing evidence).",
             {"query": "text to look for", "top_k": "optional int"}, t_search_submission),
        Tool("check_format", "Run deterministic format checks on the submission (uses the saved format_rules if rules omitted).",
             {"rules": "optional format_rules object"}, t_check_format),
        Tool("check_consistency", "Detect contradictions: claimed tools not shown in logs, dangling figure references, placeholders, empty sections.",
             {"claimed_tools": "tool names the SUBMISSION says its own project uses (e.g. web_search) - not the audit tools you are calling"}, t_check_consistency),
        Tool("record_assessments", "Record your verdict for one or more requirements.",
             {"assessments": "list of {id, status(Satisfied|Partially Satisfied|Not Satisfied|Not Verifiable|Not Applicable), evidence(short quote from submission), page, confidence(0-1), reason, suggested_fix}"},
             t_record_assessments),
        Tool("calculate_compliance_score", "Compute the weighted advisory compliance score and rubric estimate.", {}, t_calculate_compliance_score),
        Tool("compare_with_previous_audit", "Compare this audit with the last approved audit of an earlier version of the same submission.",
             {}, t_compare_with_previous_audit),
        Tool("calculator", "Evaluate an arithmetic expression.", {"expression": "e.g. '(5*0.5+3)/8*100'"}, t_calculator),
    ]
}


def tool_descriptions() -> str:
    return "\n".join(t.signature() for t in TOOLS.values())


def execute(ws: Workspace, name: str, args: dict) -> dict:
    if name not in TOOLS:
        raise ToolError(f"Unknown tool '{name}'. Available: {list(TOOLS)}")
    if not isinstance(args, dict):
        raise ToolError("action_input must be a JSON object")
    tool = TOOLS[name]
    unknown = set(args) - set(tool.params) - {"top_k", "max_chars"}
    if unknown:
        raise ToolError(f"Unexpected arguments {sorted(unknown)} for {name}; expected {list(tool.params)}")
    ws.tool_counts[name] = ws.tool_counts.get(name, 0) + 1
    try:
        return tool.fn(ws, **args)
    except TypeError as e:
        raise ToolError(f"Bad arguments for {name}: {e}") from e
