"""Long-term memory stored as JSON / CSV files.

* Policy memory  - checklist + rubric extracted from a policy file, keyed by the
                   file hash, so the same instructions are not re-parsed every run.
* Audit memory   - every approved audit, so a new version of a report can be
                   compared with the previous one (what got fixed, what is still open).
"""

from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path


def submission_key(name: str) -> str:
    """'Group4_Report_v2.docx' and 'group4 report final.pdf' -> 'group4_report'."""
    stem = Path(name).stem.lower()
    stem = re.sub(r"[\s\-]+", "_", stem)
    stem = re.sub(r"(_?(v\d+|version_?\d+|final|draft|revised|updated|new|old))+$", "", stem)
    return stem.strip("_") or "submission"


class MemoryStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.policy_file = self.root / "policy_memory.json"
        self.audit_file = self.root / "audit_memory.json"
        self.csv_file = self.root / "audit_history.csv"

    # ---------------------------------------------------------------- helpers
    def _load(self, path: Path, default):
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return default
        return default

    def _save(self, path: Path, data):
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    # --------------------------------------------------------- policy memory
    def get_policy(self, policy_sha1: str) -> dict | None:
        return self._load(self.policy_file, {}).get(policy_sha1)

    def save_policy(self, policy_sha1: str, name: str, checklist: list, rubric: dict, format_rules: dict):
        data = self._load(self.policy_file, {})
        data[policy_sha1] = {
            "policy_name": name,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "rubric": rubric,
            "format_rules": format_rules,
            "checklist": checklist,
        }
        self._save(self.policy_file, data)

    def forget_policy(self, policy_sha1: str):
        data = self._load(self.policy_file, {})
        data.pop(policy_sha1, None)
        self._save(self.policy_file, data)

    # ---------------------------------------------------------- audit memory
    def audits(self) -> list[dict]:
        return self._load(self.audit_file, [])

    def last_audit(self, key: str, policy_sha1: str | None = None, exclude_sha1: str | None = None) -> dict | None:
        for a in reversed(self.audits()):
            if a["submission_key"] != key:
                continue
            if policy_sha1 and a.get("policy_sha1") != policy_sha1:
                continue
            if exclude_sha1 and a.get("submission_sha1") == exclude_sha1:
                continue
            return a
        return None

    def save_audit(self, record: dict) -> dict:
        record = dict(record)
        record.setdefault("timestamp", datetime.now().isoformat(timespec="seconds"))
        record.setdefault("audit_id", f"AUD-{datetime.now():%Y%m%d-%H%M%S}")
        data = self.audits()
        data.append(record)
        self._save(self.audit_file, data)

        new = not self.csv_file.exists()
        with self.csv_file.open("a", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            if new:
                w.writerow(["audit_id", "timestamp", "submission", "requirement_id", "status", "confidence", "score_percent"])
            for rid, a in record.get("assessments", {}).items():
                w.writerow([record["audit_id"], record["timestamp"], record.get("submission_file"), rid,
                            a.get("status"), a.get("confidence"), record.get("score_percent")])
        return record


def compare_audits(previous: dict, current_assessments: dict, current_score: float | None = None) -> dict:
    """Diff two audits requirement by requirement."""
    rank = {"Satisfied": 3, "Not Applicable": 3, "Partially Satisfied": 2, "Not Verifiable": 1, "Not Satisfied": 0}
    prev = previous.get("assessments", {})
    fixed, improved, regressed, still_open, unchanged = [], [], [], [], []
    for rid, cur in current_assessments.items():
        c = cur.get("status")
        p = prev.get(rid, {}).get("status")
        if p is None:
            continue
        rp, rc = rank.get(p, 0), rank.get(c, 0)
        item = {"id": rid, "before": p, "after": c}
        if rc > rp and rc == 3:
            fixed.append(item)
        elif rc > rp:
            improved.append(item)
        elif rc < rp:
            regressed.append(item)
        elif rc < 3:
            still_open.append(item)
        else:
            unchanged.append(item)
    return {
        "previous_audit": previous.get("audit_id"),
        "previous_file": previous.get("submission_file"),
        "previous_score": previous.get("score_percent"),
        "current_score": current_score,
        "fixed": fixed,
        "improved": improved,
        "regressed": regressed,
        "still_open": still_open,
        "unchanged_ok": len(unchanged),
    }
