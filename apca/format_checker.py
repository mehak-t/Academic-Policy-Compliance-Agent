"""Deterministic format / structure checks (page count, file type, headings, figures...)."""

from __future__ import annotations

from .documents import Document
from .search import tokenize


def match_section(name: str, doc: Document) -> dict | None:
    """Fuzzy-match a required section name against the document headings."""
    want = set(tokenize(name))
    if not want:
        return None
    best, best_score = None, 0.0
    for h in doc.headings:
        have = set(tokenize(h.text))
        if not have:
            continue
        overlap = len(want & have) / len(want)
        if name.lower() in h.text.lower():
            overlap = 1.0
        if overlap > best_score:
            best, best_score = h, overlap
    if best is not None and best_score >= 0.6:
        return {"heading": best.text, "page": best.page, "match": round(best_score, 2)}
    return None


def check_format(doc: Document, rules: dict) -> dict:
    checks = []

    def add(name, expected, actual, passed, note=""):
        checks.append({"check": name, "expected": expected, "actual": actual, "passed": bool(passed), "note": note})

    types = [t.lower().lstrip(".") for t in rules.get("allowed_file_types", [])]
    if types:
        add("file_type", types, doc.file_type, doc.file_type in types)

    est = " (estimated - format has no fixed pages)" if doc.pages_estimated else ""
    if rules.get("min_pages") is not None:
        add("min_pages", rules["min_pages"], doc.pages, doc.pages >= int(rules["min_pages"]), est)
    if rules.get("max_pages") is not None:
        add("max_pages", rules["max_pages"], doc.pages, doc.pages <= int(rules["max_pages"]), est)
    if rules.get("min_words") is not None:
        add("min_words", rules["min_words"], doc.word_count, doc.word_count >= int(rules["min_words"]))
    if rules.get("min_images") is not None:
        add("min_images", rules["min_images"], doc.image_count, doc.image_count >= int(rules["min_images"]))
    if rules.get("min_tables") is not None:
        add("min_tables", rules["min_tables"], doc.table_count, doc.table_count >= int(rules["min_tables"]))
    if rules.get("require_code"):
        add("code_present", True, doc.code_count, doc.code_count > 0)

    for sec in rules.get("required_sections", []):
        m = match_section(sec, doc)
        add(f"section: {sec}", "present", m["heading"] + f" (p{m['page']})" if m else "missing", m is not None)

    passed = sum(c["passed"] for c in checks)
    return {"doc_id": doc.doc_id, "passed": passed, "total": len(checks), "checks": checks}
