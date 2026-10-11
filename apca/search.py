"""Evidence search: a small BM25 index over document blocks.

Pure Python on purpose — no embeddings service is needed, results are
deterministic and every hit carries its page number and block type.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from .documents import Block, Document

STOP = set(
    """a an the and or of to in on for with by is are be as at from that this it its
    must should will shall can may at least one two any all each your their our use used
    using students student include includes including""".split()
)

# A few domain synonyms so "logs" also finds "trace", "diagram" finds "figure", ...
SYNONYMS = {
    "log": ["trace", "transcript", "observation"],
    "trace": ["log"],
    "diagram": ["figure", "architecture", "flow"],
    "screenshot": ["figure", "output", "screen"],
    "comparison": ["compare", "versus", "vs", "classical"],
    "memory": ["context", "history", "store"],
    "planning": ["plan", "react", "step"],
    "tool": ["tools", "function"],
    "reference": ["references", "bibliography", "citation"],
    "repository": ["github", "repo", "notebook", "code"],
    "llm": ["model", "gpt", "llama", "gemini", "language"],
}


def tokenize(text: str) -> list[str]:
    toks = re.findall(r"[a-z0-9]+", text.lower())
    out = []
    for t in toks:
        if t in STOP or len(t) < 2:
            continue
        # crude stemming keeps "tools"/"tool", "diagrams"/"diagram" together
        if len(t) > 4 and t.endswith("s") and not t.endswith("ss"):
            t = t[:-1]
        out.append(t)
    return out


class EvidenceIndex:
    def __init__(self, doc: Document, k1: float = 1.4, b: float = 0.75):
        self.doc = doc
        self.k1, self.b = k1, b
        # Each unit = one block, merged with the heading above it for context.
        self.units: list[tuple[Block, str, str]] = []  # (block, section heading, text)
        section = ""
        for blk in doc.blocks:
            if blk.kind == "heading":
                section = blk.text
            if blk.kind == "image":
                continue
            self.units.append((blk, section, blk.text))
        self.tfs = [Counter(tokenize(sec + " " + txt)) for _, sec, txt in self.units]
        self.lens = [sum(tf.values()) for tf in self.tfs]
        self.avg = (sum(self.lens) / len(self.lens)) if self.lens else 1
        df = Counter()
        for tf in self.tfs:
            df.update(tf.keys())
        n = len(self.tfs) or 1
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def _expand(self, query: str) -> list[str]:
        q = tokenize(query)
        extra = [s for t in q for s in SYNONYMS.get(t, [])]
        return q + [e for e in tokenize(" ".join(extra)) if e not in q]

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        terms = self._expand(query)
        scored = []
        for i, tf in enumerate(self.tfs):
            s = 0.0
            for t in terms:
                if t not in tf:
                    continue
                f = tf[t]
                s += self.idf.get(t, 0) * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.lens[i] / self.avg))
            if s > 0:
                scored.append((s, i))
        scored.sort(reverse=True)
        hits = []
        for s, i in scored[:top_k]:
            blk, sec, txt = self.units[i]
            hits.append(
                {
                    "page": blk.page,
                    "kind": blk.kind,
                    "section": sec[:80],
                    "snippet": _snippet(txt, terms),
                    "score": round(s, 2),
                }
            )
        return hits

    def nearby_images(self, page: int, window: int = 0) -> int:
        return sum(1 for b in self.doc.blocks if b.kind == "image" and abs(b.page - page) <= window)


def _snippet(text: str, terms: list[str], width: int = 220) -> str:
    low = text.lower()
    pos = min((low.find(t) for t in terms if low.find(t) >= 0), default=0)
    start = max(0, pos - 60)
    s = text[start : start + width]
    return ("…" if start else "") + s.strip() + ("…" if start + width < len(text) else "")
