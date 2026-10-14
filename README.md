# Academic Policy Compliance Agent

An **LLM-based agent** that reads academic instructions, project guidelines and evaluation
rubrics, then audits a student's report / SRS / notebook against them **before submission**.

It extracts the requirements, builds a structured checklist, searches the submission for
evidence (with page numbers), runs format and consistency checks, classifies every
requirement, estimates rubric coverage and produces a prioritised correction plan — while
logging every thought, tool call and observation. A human reviews and approves the audit
before anything is saved or exported.

> IA II – Activity 1: *Agentic AI System using Modern LLM-based Tools* (Artificial Intelligence).
> Advisory tool only — it is not an official grading system.

## Features

- **ReAct agent loop** – the LLM plans, picks tools, observes results and re-plans.
- **12 tools** – document reader (PDF / DOCX / MD / TXT / IPYNB), checklist store, BM25 evidence
  search, format checker, consistency / contradiction checker, assessment recorder,
  weighted scorer, calculator, version comparison.
- **Evidence-first verdicts** – Satisfied / Partially Satisfied / Not Satisfied / Not Verifiable /
  Not Applicable, each with a quote, page, confidence and a concrete fix.
- **Contradiction detection** – e.g. *"report claims three tools but the log only shows one"*,
  *"refers to Figure 2 but has no figures"*, template placeholders, empty sections.
- **Rubric-aware score** – `Σ(weight × status value) / Σ weight`, plus estimated marks per rubric component.
- **Memory** – short-term context, working memory, policy memory (checklists reused across runs)
  and audit memory (compare v1 vs v2 of a report).
- **Guardrails** – the agent cannot finish until every requirement has a verdict and the checks have run.
- **Human-in-the-loop** – review/override verdicts, then approve to export DOCX / Markdown / CSV / JSON.
- **Saved audits** – reopen any approved audit (with its trace) from the sidebar without calling the LLM.
- **Observable** – live trace in the UI, plus `logs/<run>.jsonl` and `logs/<run>.md` for every run.
- **Classical baseline** – a rule-based keyword checker for the Part C comparison.

## Architecture

See [docs/architecture.md](docs/architecture.md) for the architecture and tool-flow diagrams.

```
apca/
  agent.py            ReAct loop, guardrails, context compression
  prompts.py          system prompt + goal templates
  tools.py            tool registry + shared workspace
  documents.py        PDF / DOCX / Markdown / notebook reader
  search.py           BM25 evidence search
  format_checker.py   page count, file type, sections, figures
  consistency.py      claims vs logs, dangling references, placeholders
  scoring.py          weighted score, rubric estimate, action ranking
  memory.py           policy + audit memory (JSON / CSV)
  trace.py            event logger (console, JSONL, Markdown)
  report.py           DOCX / Markdown / JSON / CSV export
  pipeline.py         run -> human review -> approve -> export
  classical_agent.py  rule-based baseline
  llm.py              OpenAI-compatible client (OpenRouter, Gemini, Groq, Ollama)
  cli.py              command line interface
app.py                Streamlit UI
samples/              IA2 policy + demo reports (v1 incomplete, v2 revised)
scripts/              classical vs LLM comparison
tests/                unit + offline end-to-end tests
```

## Setup

```bash
pip install -r requirements.txt
```

Create a `.env` file in the project folder (it is git-ignored):

```
LLM_PROVIDER=gemini
LLM_API_KEY=your-key-here
# optional: LLM_MODEL=gemini-3.6-flash
```

Any OpenAI-compatible endpoint works. Set `LLM_PROVIDER` to one of:

| Provider | Key from | Default model |
|---|---|---|
| `openrouter` | openrouter.ai (free models) | `meta-llama/llama-3.3-70b-instruct:free` |
| `gemini` | aistudio.google.com | `gemini-3.6-flash` |
| `groq` | console.groq.com | `llama-3.3-70b-versatile` |
| `ollama` | local, no key | `qwen2.5:7b` |

## Run

Web UI (recommended for the demo):

```bash
streamlit run app.py
```

Command line:

```bash
python -m apca.cli audit --policy samples/policies/IA2_instructions.md --submission samples/submissions/travel_agent_report_v1.docx
```

Demo flow: audit `travel_agent_report_v1.docx` → approve → audit `travel_agent_report_v2.docx`
→ the *Version comparison* tab shows which gaps were fixed.

Classical vs LLM comparison:

```bash
python scripts/compare_agents.py
```

Tests (offline, no API key needed):

```bash
pytest -q
```

## Example trace

Real run on `samples/submissions/travel_agent_report_v1.docx` (shortened):

```
[Goal] Audit the submission against the policy. Extract every requirement and rubric component, identify missi
step  1 [Plan] 1. Read the policy document (IA2_instructions.md) to extract requirements, rubric, and formatti
step  1 [Thought] I need to start by reading the policy document to understand the requirements and rubric for
step  1 [Tool Call] read_document({"role": "policy"})
step  1 [Observation] IA2_instructions.md: 1 pages, 11 headings, 0 images
step  2 [Tool Call] get_document_text({"role": "policy"})
step  2 [Observation] read 2820 chars of policy
step  3 [Tool Call] read_document({"role": "submission"})
step  3 [Observation] travel_agent_report_v1.docx: 2 pages, 12 headings, 0 images
step  4 [Tool Call] save_checklist({"requirements": [{"id": "REQ-01", "description": "Part A: E...)
step  4 [Memory] save_checklist: hit
step  4 [Observation] saved 14 requirements
step  5 [Tool Call] get_document_text({"role": "submission"})
step  5 [Observation] read 1397 chars of submission
step  6 [Tool Call] find_evidence({"requirement_ids": "all"})
step  6 [Observation] evidence for 14 requirements
step  7 [Tool Call] check_format({})
step  7 [Observation] 8/14 format checks passed
step  8 [Thought] Now I will run the consistency check.
step  8 [Tool Call] check_consistency({"claimed_tools": ["web_search", "calculator", "weather_api"...)
step  8 [Observation] 7 findings: Report claims "three tools" but logs/code only show calls to 1 tool(s): ['we
step  9 [Thought] Now I will record assessments for all 14 requirements.
step  9 [Tool Call] record_assessments({"assessments": [{"id": "REQ-01", "status": "Satisfied", "ev...)
step  9 [Observation] recorded 14, remaining 0
step 10 [Thought] Now I will calculate the compliance score.
step 10 [Tool Call] calculate_compliance_score({})
step 10 [Observation] score 43.6%, counts {'Satisfied': 3, 'Partially Satisfied': 6, 'Not Satisfied': 5}
step 11 [Tool Call] compare_with_previous_audit({})
step 11 [Memory] compare_with_previous_audit: miss
step 11 [Observation] No earlier approved audit of this submission in memory.
step 12 [Error] Unparseable reply (Invalid control character at: line 1 column 150 (char 149)): {"thought": "I
step 13 [Final Answer] Executive Summary & Audit Report: Compliance Score: 43.6% (Estimated Rubric: 7.1 / 20 M
```

The revised report (v2) was then audited: the checklist was recalled from policy memory and the
version comparison showed 43.6% -> 92.3%, 9 requirements fixed and 2 still partially satisfied.

## Team

| Member | Responsibility |
|---|---|
| Student 1 | Document ingestion, policy extraction, checklist memory |
| Student 2 | Agent loop, prompts, evidence retrieval, classification |
| Student 3 | Format/consistency tools, scoring, reports, UI, testing |
