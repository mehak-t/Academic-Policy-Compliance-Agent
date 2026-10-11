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
# optional: LLM_MODEL=gemini-2.5-flash
```

Any OpenAI-compatible endpoint works. Set `LLM_PROVIDER` to one of:

| Provider | Key from | Default model |
|---|---|---|
| `openrouter` | openrouter.ai (free models) | `meta-llama/llama-3.3-70b-instruct:free` |
| `gemini` | aistudio.google.com | `gemini-2.5-flash` |
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

```
step  1 [Plan] ["Check policy memory", "Extract checklist", "Read submission", ...]
step  1 [Tool Call] recall_policy_memory({"role": "policy"})
step  1 [Observation] {"found": false, ...}
step  4 [Tool Call] save_checklist({"requirements": [...16 items...], "rubric": {...}})
step  6 [Tool Call] find_evidence({"requirement_ids": "all"})
step  7 [Thought] R07 claims three tools but the log only shows web_search -> Partially Satisfied
step 10 [Tool Call] check_consistency({"claimed_tools": ["web_search", "calculator", "weather_api"]})
step 10 [Observation] claim_contradiction: Report claims "three tools" but logs only show 1 tool
step 12 [Final Answer] Compliance 41%. 5 high-priority fixes ...
```

## Team

| Member | Responsibility |
|---|---|
| Student 1 | Document ingestion, policy extraction, checklist memory |
| Student 2 | Agent loop, prompts, evidence retrieval, classification |
| Student 3 | Format/consistency tools, scoring, reports, UI, testing |
