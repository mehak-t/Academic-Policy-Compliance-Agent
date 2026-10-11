"""Observable agent behaviour: every goal, thought, tool call and observation
is recorded as an event, printed to the console, written to a JSONL trace and
a human-readable Markdown log, and forwarded to UI callbacks."""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

COLORS = {
    "goal": "\033[95m", "plan": "\033[96m", "thought": "\033[93m", "tool_call": "\033[94m",
    "observation": "\033[92m", "memory": "\033[36m", "final": "\033[1;97m", "error": "\033[91m",
    "human": "\033[35m", "info": "\033[90m",
}
RESET = "\033[0m"
LABELS = {
    "goal": "[Goal]", "plan": "[Plan]", "thought": "[Thought]", "tool_call": "[Tool Call]",
    "observation": "[Observation]", "memory": "[Memory]", "final": "[Final Answer]", "error": "[Error]",
    "human": "[Human]", "info": "[Info]",
}


class Tracer:
    def __init__(self, log_dir: str | Path, run_name: str = "audit", echo: bool = True):
        self.started = time.time()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_id = f"{run_name}_{stamp}"
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.jsonl_path = self.log_dir / f"{self.run_id}.jsonl"
        self.md_path = self.log_dir / f"{self.run_id}.md"
        self.events: list[dict] = []
        self.echo = echo
        self.callbacks = []
        self.md_path.write_text(f"# Agent interaction log - {self.run_id}\n\n", encoding="utf-8")

    def on_event(self, fn):
        self.callbacks.append(fn)

    def log(self, kind: str, content, step: int | None = None, **extra) -> dict:
        ev = {
            "t": round(time.time() - self.started, 2),
            "step": step,
            "type": kind,
            "content": content,
            **extra,
        }
        self.events.append(ev)
        with self.jsonl_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(ev, ensure_ascii=False, default=str) + "\n")
        with self.md_path.open("a", encoding="utf-8") as fh:
            fh.write(self._md(ev))
        if self.echo:
            self._print(ev)
        for cb in self.callbacks:
            try:
                cb(ev)
            except Exception:  # UI problems must never kill the agent
                pass
        return ev

    # ------------------------------------------------------------ formatting
    @staticmethod
    def render(ev: dict, limit: int = 1200) -> str:
        c = ev["content"]
        if ev["type"] == "tool_call":
            args = json.dumps(ev.get("args", {}), ensure_ascii=False)
            if len(args) > 300:
                args = args[:300] + "...}"
            text = f"{c}({args})"
        elif isinstance(c, (dict, list)):
            text = json.dumps(c, ensure_ascii=False, indent=1, default=str)
        else:
            text = str(c)
        return text if len(text) <= limit else text[:limit] + f"... [{len(text) - limit} more chars]"

    def _print(self, ev):
        step = f"step {ev['step']:>2} " if ev.get("step") is not None else ""
        color = COLORS.get(ev["type"], "") if sys.stdout.isatty() else ""
        reset = RESET if color else ""
        line = f"{color}{step}{LABELS.get(ev['type'], ev['type'])} {self.render(ev, 600)}{reset}"
        try:
            print(line, flush=True)
        except UnicodeEncodeError:
            print(line.encode("ascii", "replace").decode(), flush=True)

    def _md(self, ev) -> str:
        step = f"**Step {ev['step']}** · " if ev.get("step") is not None else ""
        label = LABELS.get(ev["type"], ev["type"])
        body = self.render(ev, 3000)
        if ev["type"] in ("observation", "tool_call") or "\n" in body:
            return f"{step}`{label}` _(t={ev['t']}s)_\n\n```\n{body}\n```\n\n"
        return f"{step}`{label}` {body}  \n\n"
