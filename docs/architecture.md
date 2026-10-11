# Architecture

## System architecture

```mermaid
flowchart LR
    U([Student]) -->|goal + policy + submission| ORCH

    subgraph AGENT["LLM Compliance Agent (ReAct loop)"]
        ORCH["Orchestrator LLM<br/>(OpenRouter / Gemini / Groq)"]
        PLAN["Planner<br/>plan + re-plan"]
        STM["Short-term memory<br/>scratchpad + workspace"]
        ORCH <--> PLAN
        ORCH <--> STM
    end

    subgraph TOOLS["Tools (Python)"]
        T1["read_document /<br/>get_document_text"]
        T2["save_checklist<br/>(policy parser output)"]
        T3["find_evidence /<br/>search_submission (BM25)"]
        T4["check_format"]
        T5["check_consistency"]
        T6["record_assessments"]
        T7["calculate_compliance_score /<br/>calculator"]
        T8["compare_with_previous_audit"]
    end

    subgraph LTM["Long-term memory (JSON / CSV)"]
        M1[("policy_memory.json")]
        M2[("audit_memory.json<br/>audit_history.csv")]
    end

    ORCH -->|tool call| TOOLS
    TOOLS -->|observation| ORCH
    T2 <--> M1
    T8 <--> M2
    ORCH -->|draft audit| HUM{{"Human review<br/>override + approve"}}
    HUM -->|approved| REP["Report generator<br/>DOCX / MD / JSON / CSV"]
    HUM --> M2
    ORCH -. every event .-> LOG[["Trace logger<br/>logs/*.jsonl + *.md"]]
    REP --> U
```

## Tool flow (one audit)

```mermaid
flowchart TD
    G[Goal] --> P[Thought + plan]
    P --> R{recall_policy_memory}
    R -- hit --> S[read_document submission]
    R -- miss --> RD[read_document + get_document_text policy] --> SC[save_checklist] --> S
    S --> FE[find_evidence all]
    FE --> W{weak / missing evidence?}
    W -- yes --> SS[search_submission] --> RA
    W -- no --> RA[record_assessments]
    RA --> CF[check_format] --> CC[check_consistency] --> CS[calculate_compliance_score]
    CS --> CP[compare_with_previous_audit]
    CP --> FA[final_answer]
    FA --> GR{guardrail: all items assessed,<br/>checks run, score fresh?}
    GR -- no --> RA
    GR -- yes --> H[Human approval] --> E[Export report + save audit memory]
```

## ReAct message protocol

Every LLM turn is one JSON object:

```json
{"thought": "Evidence for R07 is weak, the log only shows web_search.",
 "action": "search_submission",
 "action_input": {"query": "calculator tool call"}}
```

The first turn also carries `"plan": [...]`. The loop ends with
`{"thought": "...", "final_answer": "..."}` - which is rejected by a guardrail
until every requirement has a verdict and the format / consistency / scoring
tools have run.

## Memory

| Type | Where | What |
|---|---|---|
| Short-term (context) | chat messages | thoughts, actions, observations; older observations are compressed to save tokens |
| Working memory | `Workspace` object | loaded documents, checklist, evidence, verdicts, scores |
| Policy memory | `memory/policy_memory.json` | checklist + rubric + format rules per policy file hash |
| Audit memory | `memory/audit_memory.json`, `audit_history.csv` | approved audits, used for version comparison |
