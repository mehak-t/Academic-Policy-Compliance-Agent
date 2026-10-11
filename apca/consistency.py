"""Consistency / contradiction checks on a submission.

Looks for things a human reviewer usually catches late:
  * claims like "we use three tools" while logs only show calls to one tool
  * tools named in the report that never appear in code or logs
  * "see Figure 4" when the document has fewer figures
  * template placeholders left in ("Topic Name", "TODO", "Lorem ipsum")
  * empty sections and copy-pasted paragraphs
"""

from __future__ import annotations

import re

from .documents import Document

NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8}
CLAIM_RE = re.compile(r"\b(one|two|three|four|five|six|seven|eight|\d)\s+(?:different\s+|distinct\s+|external\s+)?tools\b", re.I)
TOOL_CALL_RES = [
    re.compile(r"\[tool call\]\s*([a-z_][a-z0-9_]*)\s*\(", re.I),
    re.compile(r"\baction\s*:\s*([a-z_][a-z0-9_]*)", re.I),
    re.compile(r"\"action\"\s*:\s*\"([a-z_][a-z0-9_]*)\"", re.I),
    re.compile(r"\btool\s*=\s*['\"]?([a-z_][a-z0-9_]*)", re.I),
]
REF_RE = re.compile(r"\b(figure|fig\.|table)\s*(\d+)", re.I)
PLACEHOLDERS = ["topic name", "roll no: name", "lorem ipsum", "todo", "tbd", "insert here", "xx-xx", "your name"]


def _log_text(doc: Document) -> str:
    """Text that looks like code or agent logs."""
    parts = []
    for b in doc.blocks:
        if b.kind == "code" or re.search(r"\[(tool call|observation|agent)\]|thought:|observation:", b.text, re.I):
            parts.append(b.text)
    return "\n".join(parts)


def check_consistency(doc: Document, claimed_tools: list[str] | None = None) -> dict:
    findings = []
    full = "\n".join(b.text for b in doc.blocks if b.kind != "image")
    logs = _log_text(doc)

    # 1. tool-count claims vs tools visible in logs
    called = set()
    for rx in TOOL_CALL_RES:
        called.update(m.group(1).lower() for m in rx.finditer(logs))
    called.discard("final_answer")
    for m in CLAIM_RE.finditer(full):
        word = m.group(1).lower()
        n = int(word) if word.isdigit() else NUM_WORDS[word]
        page = _page_of(doc, m.group(0))
        if not logs:
            findings.append(_f("claim_unverifiable", "Medium", page,
                               f'Report claims "{m.group(0)}" but contains no code or interaction logs to confirm it.'))
        elif len(called) < n:
            findings.append(_f("claim_contradiction", "High", page,
                               f'Report claims "{m.group(0)}" but logs/code only show calls to {len(called)} tool(s): {sorted(called) or "none"}.'))

    # 2. tools named in prose but never seen in code/logs
    for t in claimed_tools or []:
        key = t.lower().replace(" ", "_")
        if logs and key not in logs.lower() and t.lower() not in logs.lower():
            findings.append(_f("tool_not_demonstrated", "High", _page_of(doc, t),
                               f'Tool "{t}" is described but never appears in the code or interaction logs.'))

    # 3. figure/table references beyond what exists
    n_fig = max(doc.image_count, sum(1 for b in doc.blocks if b.kind == "caption" and b.text.lower().startswith(("fig", "diagram", "screenshot"))))
    n_tab = doc.table_count
    seen = set()
    for m in REF_RE.finditer(full):
        kind, num = m.group(1).lower(), int(m.group(2))
        if (kind, num) in seen:
            continue
        seen.add((kind, num))
        have = n_tab if kind == "table" else n_fig
        if num > have:
            findings.append(_f("dangling_reference", "Medium", _page_of(doc, m.group(0)),
                               f'Text refers to "{m.group(0)}" but the document only contains {have} {"tables" if kind == "table" else "figures/images"}.'))

    # 4. placeholders
    low = full.lower()
    for p in PLACEHOLDERS:
        if re.search(r"\b" + re.escape(p) + r"\b", low):
            findings.append(_f("placeholder_text", "Medium", _page_of(doc, p), f'Template placeholder "{p}" is still present.'))

    # 5. empty sections (heading immediately followed by a heading of same or higher level)
    blocks = doc.blocks
    for i, b in enumerate(blocks[:-1]):
        nxt = blocks[i + 1]
        if b.kind == "heading" and nxt.kind == "heading" and nxt.level <= b.level and b.level >= 2:
            findings.append(_f("empty_section", "Medium", b.page, f'Section "{b.text}" has no content.'))
    if blocks and blocks[-1].kind == "heading":
        findings.append(_f("empty_section", "Medium", blocks[-1].page, f'Section "{blocks[-1].text}" has no content.'))

    # 6. duplicated paragraphs
    paras = [(b, set(b.text.lower().split())) for b in doc.blocks if b.kind == "para" and len(b.text.split()) >= 20]
    for i in range(len(paras)):
        for j in range(i + 1, len(paras)):
            a, b = paras[i][1], paras[j][1]
            if len(a & b) / len(a | b) > 0.9:
                findings.append(_f("duplicate_paragraph", "Low", paras[j][0].page,
                                   f"Paragraph on p{paras[j][0].page} repeats a paragraph from p{paras[i][0].page}."))

    return {"doc_id": doc.doc_id, "tools_seen_in_logs": sorted(called), "findings": findings, "count": len(findings)}


def _f(kind, severity, page, message):
    return {"type": kind, "severity": severity, "page": page, "message": message}


def _page_of(doc: Document, needle: str) -> int | None:
    n = needle.lower()
    for b in doc.blocks:
        if n in b.text.lower():
            return b.page
    return None
