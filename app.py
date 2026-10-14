"""Streamlit demo UI for the Academic Policy Compliance Agent.

    streamlit run app.py
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import streamlit as st

from apca.classical_agent import classical_check
from apca.config import DEFAULT_MODELS, PROVIDERS, ROOT, load_settings
from apca.llm import LLMError
from apca.pipeline import approve_and_export, run_audit
from apca.prompts import DEFAULT_GOAL
from apca.report import checklist_rows
from apca.scoring import STATUS_VALUES
from apca.trace import LABELS, Tracer

st.set_page_config(page_title="Academic Policy Compliance Agent", page_icon="📋", layout="wide")

SAMPLES = ROOT / "samples"
STATUS_COLOR = {"Satisfied": "🟢", "Partially Satisfied": "🟡", "Not Satisfied": "🔴", "Not Verifiable": "⚪", "Not Applicable": "➖"}
EVENT_ICON = {"goal": "🎯", "plan": "🗺️", "thought": "💭", "tool_call": "🔧", "observation": "👁️", "memory": "🧠",
              "final": "✅", "error": "⚠️", "human": "🙋", "info": "ℹ️"}


def save_upload(upload) -> str:
    folder = ROOT / "outputs" / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / upload.name
    path.write_bytes(upload.getvalue())
    return str(path)


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.header("LLM settings")
    base = load_settings()
    providers = list(PROVIDERS)
    provider = st.selectbox("Provider", providers, index=providers.index(base.provider) if base.provider in providers else 0)
    model = st.text_input("Model", value=base.model if provider == base.provider else DEFAULT_MODELS[provider])
    api_key = st.text_input("API key", value="", type="password", help="Leave empty to use LLM_API_KEY from .env")
    max_steps = st.slider("Max agent steps", 8, 30, 20)
    st.caption("The key is used only for this session and is never written to disk.")
    st.divider()
    saved = sorted((ROOT / "outputs").glob("audit_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if saved:
        st.header("Saved audits")
        pick = st.selectbox("Open an approved audit", ["-"] + [p.name for p in saved])
        if pick != "-" and st.button("Open"):
            data = json.loads((ROOT / "outputs" / pick).read_text(encoding="utf-8"))
            log = Path(data.get("logs", {}).get("jsonl", ""))
            events = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
            st.session_state["result"] = data
            st.session_state["tracer"] = SimpleNamespace(events=events, md_path=data["logs"]["markdown"])
            st.session_state["exported"] = {k: str(ROOT / "outputs" / pick.replace(".json", ext))
                                            for k, ext in (("docx", ".docx"), ("markdown", ".md"), ("csv", ".csv"), ("json", ".json"))}
            st.session_state["loaded"] = data.get("approved_by")
        st.divider()
    st.markdown("**How it works**\n\n1. Agent plans the audit\n2. Extracts a checklist from the policy\n"
                "3. Searches the submission for evidence\n4. Runs format + consistency tools\n"
                "5. Scores and prioritises fixes\n6. **You** review and approve")

st.title("📋 Academic Policy Compliance Agent")
st.caption("An LLM agent that audits your report against the assignment instructions and rubric before you submit. Advisory only - not an official grade.")

# ------------------------------------------------------------------ inputs
c1, c2 = st.columns(2)
with c1:
    st.subheader("1 · Policy / instructions")
    pol_mode = st.radio("Policy source", ["Sample: IA2 instructions", "Upload"], horizontal=True, label_visibility="collapsed")
    policy_path = None
    if pol_mode == "Upload":
        up = st.file_uploader("Instructions / rubric", type=["pdf", "docx", "md", "txt"], key="pol")
        if up:
            policy_path = save_upload(up)
    else:
        policy_path = str(SAMPLES / "policies" / "IA2_instructions.md")
with c2:
    st.subheader("2 · Submission")
    samples = sorted(p.name for p in (SAMPLES / "submissions").glob("*.*"))
    sub_mode = st.radio("Submission source", ["Sample report", "Upload"], horizontal=True, label_visibility="collapsed")
    submission_path = None
    if sub_mode == "Upload":
        up = st.file_uploader("Report / SRS / notebook", type=["pdf", "docx", "md", "txt", "ipynb"], key="sub")
        if up:
            submission_path = save_upload(up)
    else:
        choice = st.selectbox("Sample", samples)
        submission_path = str(SAMPLES / "submissions" / choice)

goal = st.text_area("3 · Goal for the agent", value=DEFAULT_GOAL, height=90)
run = st.button("▶ Run audit", type="primary", disabled=not (policy_path and submission_path))

# ------------------------------------------------------------------ run
if run:
    settings = load_settings(provider=provider, model=model, api_key=api_key or None, max_steps=max_steps)
    st.session_state.pop("exported", None)
    st.session_state.pop("loaded", None)
    box = st.status("Agent working…", expanded=True)

    def show(ev):
        icon = EVENT_ICON.get(ev["type"], "•")
        step = f"**{ev['step']}** · " if ev.get("step") is not None else ""
        label = LABELS.get(ev["type"], ev["type"])
        if ev["type"] == "observation":
            box.markdown(f"{step}{icon} `{label}` from `{ev.get('tool')}`")
            box.code(Tracer.render(ev, 700), language="json")
        elif ev["type"] == "plan":
            box.markdown(f"{step}{icon} `{label}`\n" + "\n".join(f"{i}. {p}" for i, p in enumerate(ev["content"], 1)))
        else:
            box.markdown(f"{step}{icon} `{label}` {Tracer.render(ev, 500)}")

    try:
        result, tracer = run_audit(policy_path, submission_path, settings, goal=goal, echo=False, on_event=show)
        st.session_state["result"] = result
        st.session_state["tracer"] = tracer
        st.session_state["settings"] = settings
        box.update(label=f"Audit finished in {result['steps']} steps", state="complete", expanded=False)
    except LLMError as e:
        box.update(label="LLM error", state="error")
        st.error(str(e))

# ------------------------------------------------------------------ results
res = st.session_state.get("result")
if res:
    sc = res.get("score") or {}
    st.divider()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Compliance score", f"{sc.get('score_percent', 0)}%")
    if sc.get("rubric_estimate"):
        m2.metric("Rubric estimate", f"{sc['estimated_total']} / {sc['rubric_total']:g}")
    counts = sc.get("status_counts", {})
    m3.metric("Open items", len(res.get("actions", [])))
    m4.metric("Agent steps / LLM calls", f"{res['steps']} / {res['llm_usage'].get('llm_calls')}")
    if res.get("policy_from_memory"):
        st.info("🧠 Checklist was recalled from policy memory (this policy was parsed in an earlier run).")

    tabs = st.tabs(["Summary", "Checklist & review", "Correction plan", "Format & consistency", "Version comparison", "Agent trace", "Classical vs LLM"])

    with tabs[0]:
        st.markdown(res["final_answer"])
        if sc.get("rubric_estimate"):
            df = pd.DataFrame([{"Component": k, "Max": v["max"], "Estimated": v["estimated"] or 0} for k, v in sc["rubric_estimate"].items()])
            st.bar_chart(df.set_index("Component")[["Estimated", "Max"]], stack=False)
        st.write("Status counts:", " · ".join(f"{STATUS_COLOR.get(k, '')} {k}: {v}" for k, v in counts.items()))

    with tabs[1]:
        st.caption("Human-in-the-loop: change any verdict you disagree with, then approve. Nothing is saved before approval.")
        rows = checklist_rows(res)
        df = pd.DataFrame(rows)[["id", "requirement", "priority", "status", "page", "evidence", "reason", "confidence"]]
        edited = st.data_editor(
            df, hide_index=True, use_container_width=True, disabled=["id", "requirement", "priority", "page", "evidence", "reason", "confidence"],
            column_config={"status": st.column_config.SelectboxColumn("status", options=list(STATUS_VALUES), required=True)},
            key="editor",
        )
        overrides = {r["id"]: r["status"] for _, r in edited.iterrows() if r["status"] != res["assessments"].get(r["id"], {}).get("status")}
        if overrides:
            st.warning(f"{len(overrides)} verdict(s) changed by you: {overrides}")
        a1, a2 = st.columns([2, 1])
        if st.session_state.get("loaded"):
            st.info(f"Saved audit - already approved by {st.session_state['loaded']}.")
        reviewer = a1.text_input("Reviewer name", value="student")
        if not st.session_state.get("loaded") and a2.button("✅ Approve & export report", type="primary"):
            paths = approve_and_export(res, st.session_state["settings"], reviewer, overrides, st.session_state["tracer"])
            st.session_state["exported"] = paths
            st.success("Audit approved, saved to audit memory and exported.")
        if st.session_state.get("exported"):
            p = st.session_state["exported"]
            d1, d2, d3, d4 = st.columns(4)
            d1.download_button("Report (.docx)", Path(p["docx"]).read_bytes(), Path(p["docx"]).name)
            d2.download_button("Report (.md)", Path(p["markdown"]).read_bytes(), Path(p["markdown"]).name)
            d3.download_button("Checklist (.csv)", Path(p["csv"]).read_bytes(), Path(p["csv"]).name)
            d4.download_button("Full audit (.json)", Path(p["json"]).read_bytes(), Path(p["json"]).name)

    with tabs[2]:
        if not res["actions"]:
            st.success("No open items.")
        for a in res["actions"]:
            st.markdown(f"**{a['rank']}. {STATUS_COLOR.get(a['status'], '')} [{a['priority']}] {a['id']}** - {a['requirement']}  \n→ {a['action']}")

    with tabs[3]:
        f = res.get("format")
        if f:
            st.markdown(f"**Format checks:** {f['passed']} / {f['total']} passed")
            st.dataframe(pd.DataFrame(f["checks"]), hide_index=True, use_container_width=True)
        c = res.get("consistency")
        if c:
            st.markdown(f"**Consistency findings:** {c['count']} · tools seen in logs: {c['tools_seen_in_logs'] or 'none'}")
            for x in c["findings"]:
                st.markdown(f"- **{x['severity']}** `{x['type']}` (p{x['page'] or '?'}): {x['message']}")

    with tabs[4]:
        cmp_ = res.get("comparison")
        if cmp_ and cmp_.get("found"):
            st.markdown(f"Previous audit **{cmp_['previous_audit']}** of `{cmp_['previous_file']}`: "
                        f"**{cmp_['previous_score']}% → {cmp_['current_score']}%**")
            for key in ("fixed", "improved", "regressed", "still_open"):
                if cmp_.get(key):
                    st.markdown(f"**{key.replace('_', ' ').title()}**")
                    st.table(pd.DataFrame(cmp_[key]))
        else:
            st.info("No earlier approved audit of this submission. Approve this audit, then audit the next version to see what was fixed.")

    with tabs[5]:
        tr = st.session_state.get("tracer")
        if tr:
            st.download_button("Download interaction log (.md)", Path(tr.md_path).read_bytes(), Path(tr.md_path).name)
            st.markdown(f"Tool usage: {res['tool_usage']} · tokens in/out: {res['llm_usage'].get('prompt_tokens')}/{res['llm_usage'].get('completion_tokens')}")
            for ev in tr.events:
                with st.expander(f"{EVENT_ICON.get(ev['type'], '')} {ev.get('step') or ''} {LABELS.get(ev['type'])} {str(ev.get('tool') or (ev['content'] if ev['type'] == 'tool_call' else ''))}"):
                    st.code(Tracer.render(ev, 5000), language="json" if ev["type"] in ("observation", "tool_call", "plan") else None)

    with tabs[6]:
        st.caption("Same submission, checked by a classical keyword rule-based agent (no LLM, no memory, single pass).")
        sub_file = res["submission"].get("file")
        sub_path = submission_path if submission_path and Path(submission_path).name == sub_file else None
        if not sub_path and (SAMPLES / "submissions" / str(sub_file)).exists():
            sub_path = str(SAMPLES / "submissions" / sub_file)
        if sub_path:
            c = classical_check(sub_path)
            col1, col2 = st.columns(2)
            col1.metric("Classical rule-based", f"{c['score_percent']}%", help="keyword present = PASS")
            col2.metric("LLM agent", f"{sc.get('score_percent')}%")
            st.dataframe(pd.DataFrame(c["results"]), hide_index=True, use_container_width=True)
            st.markdown("""
| | Classical rule-based | LLM agent |
|---|---|---|
| Rules | hand-coded keywords for one policy | extracted from any policy text |
| Evidence | keyword present anywhere | quoted snippet + page, checked for content |
| Output | PASS / FAIL | 5 statuses, confidence, fix, priority |
| Memory | none | policy + previous-audit memory |
| Steps | single pass | multi-step ReAct with tools |
""")
