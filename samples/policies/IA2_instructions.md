# IA II - Activity 1 (20 Marks): Agentic AI System using Modern LLM-based Tools

Activity Type: Group Activity (3 students from the same lab batch). Demo will be taken in lab duration.

## Learning Objectives

- Understand Agentic AI beyond classical agents
- Learn how LLMs act as reasoning agents
- Use tool-using, planning, and memory-based agents
- Compare classical AI agents vs modern agentic systems

## Activity Description

Students will build a small Agentic AI system using modern AI tools where an LLM acts as an autonomous agent that understands a goal, plans steps, uses tools (search, calculator, documents) and produces an output. The focus is on tool usage, reasoning, and orchestration rather than model training.

## AI Tools

Students must use at least ONE agent framework (or an equivalent): AutoGen, CrewAI, ReAct-style agents, BrowserUse, OpenRouter (free API), LangChain.

Tools that can be integrated with the agent: web search APIs, Google OAuth 2.0 (Google Calendar), calculator tools, file/document readers, simple databases (CSV/JSON), Python tools.

## Student Tasks

### Part A - Agent Design (Modern View)

Students must explain:

- Goal of the agent
- Agent role
- Tools used
- Memory type (short-term / context)
- Planning strategy (ReAct / step-by-step)

### Part B - Implementation (Modern AI Tools)

Minimum requirements:

- One LLM-based agent (explain the LLM used and justify why it was chosen)
- At least two tools (list of tools, justification of choice, features)
- Multi-step reasoning, shown with an architecture diagram and a tool flow diagram
- Observable agent behavior (logs / traces)

Example: User Goal -> Agent Reasoning -> Tool Call -> Observation -> Next Action -> Final Answer

### Part C - Analysis & Comparison

Students must compare the classical agent (syllabus) with the modern agent (this activity):

| Classical Agent (Syllabus) | Modern Agent (This Activity) |
|---|---|
| Rule-based | LLM-driven |
| Static logic | Dynamic planning |
| No memory | Contextual memory |
| Single-step | Multi-step reasoning |

## Report Format

The report must follow the department template with these sections: title page (topic, roll numbers and names), Introduction / Abstract of problem statement, AI framework(s) used, Tools integrated with agent, Part A - Agent Design, Part B - Implementation, Discussion and takeaway, Conclusion, References.

## Deliverables

- PDF report (5-10 pages)
- Architecture diagram / Tool flow diagram
- Code repository / notebook + demo of working agent
- Agent interaction logs
- Prompts and output screenshots

## Evaluation Rubrics (20 Marks)

| Component | Marks |
|---|---|
| Use of modern tools & frameworks | 5 |
| Agent reasoning & tool orchestration | 5 |
| Architecture & design clarity | 5 |
| Analysis & reflection | 5 |
