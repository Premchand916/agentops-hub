# AgentOps Hub

> **Multi-agent AI operations assistant** — hybrid RAG · LangGraph orchestration · MCP-inspired tool calling · 30-test eval suite · Langfuse observability · Docker · CI/CD

[![Eval Gate](https://github.com/Premchand916/agentops-hub/actions/workflows/eval.yml/badge.svg)](https://github.com/Premchand916/agentops-hub/actions/workflows/eval.yml)
[![Docker Build](https://github.com/Premchand916/agentops-hub/actions/workflows/docker.yml/badge.svg)](https://github.com/Premchand916/agentops-hub/actions/workflows/docker.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## What It Does

AgentOps Hub routes employee requests to the right specialist AI agent — IT support, knowledge retrieval, or workflow automation — grounded in company documents and backed by real tool execution.

```
User: "My VPN shows error E-4012"
  → Orchestrator classifies intent (IT_HELP, 88% confidence)
  → IT Help Agent retrieves from hybrid RAG (BM25 + dense + reranking)
  → Grounded answer with source citations
  → Full trace logged: latency=1.2s, sources=2, confidence=0.88
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    User (CLI)                           │
└────────────────────────┬────────────────────────────────┘
                         │
              ┌──────────▼──────────┐
              │  Orchestrator Agent  │  LangGraph · intent classification
              └──┬───┬────┬────┬────┘
                 │   │    │    │
          ┌──────┘   │    │    └──────┐
          ▼          ▼    ▼           ▼
      IT Help    Knowledge  Triage  Workflow
       Agent      Agent     Agent    Agent
          │          │               │
          └────┬─────┘               └──── ToolRegistry
               │                          (create_ticket,
           RAG Layer                       search_tickets,
      BM25 + Dense + RRF                   get_system_status,
         + FlashRank                       send_notification)
               │
           Qdrant DB

┌─────────────────────────────────────────────────────────┐
│  Observability: Langfuse traces · local JSONL fallback  │
│  Evaluation:    30 test cases · 100% pass rate          │
│  Guardrails:    PII detection · topic scope · hallucin. │
│  Deployment:    Docker · docker-compose · GitHub Actions │
└─────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer           | Technology                                   |
| --------------- | -------------------------------------------- |
| LLM             | Ollama `llama3.2:3b` (swappable via factory) |
| Embeddings      | Ollama `nomic-embed-text` (768-dim)          |
| Agent Framework | LangGraph StateGraph                         |
| Vector DB       | Qdrant (in-memory / persistent)              |
| Sparse Search   | BM25 (rank-bm25)                             |
| Reranking       | FlashRank `ms-marco-MiniLM-L-12-v2`          |
| Tool Schemas    | Pydantic v2                                  |
| Observability   | Langfuse SDK + local JSONL fallback          |
| Evaluation      | Custom YAML suite (30 tests) + guardrails    |
| Deployment      | Docker · docker-compose · GitHub Actions     |

Multi-provider LLM factory supports: **Ollama · Gemini · OpenAI · Claude · Grok**

---

## Quick Start (Local)

### Prerequisites

- Python 3.11+
- [Ollama](https://ollama.com) installed and running

### Setup

```bash
git clone https://github.com/Premchand916/agentops-hub.git
cd agentops-hub

python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS/Linux

pip install -r requirements.txt
pip install -e .

# Pull Ollama models
ollama pull llama3.2:3b
ollama pull nomic-embed-text

# Run
python app/cli.py
```

### Try these queries

```
My VPN shows error E-4012
What is the PTO policy?
Create a ticket for my broken laptop
I need help with something
```

---

## Quick Start (Docker)

```bash
cd docker
docker compose up --build

# In another terminal — interact with the app
docker exec -it agentops-app python app/cli.py
```

---

## Run Evaluations

```bash
python evals/run_evals.py
```

Output:

```
Category        Tests   Passed   Score
─────────────────────────────────────
routing            10       10   100%
rag_quality         8        8   100%
tool_calling        7        7   100%
guardrails          5        5   100%
─────────────────────────────────────
TOTAL              30       30   100%  ✅ PASS
```

---

## Project Structure

```
agentops-hub/
├── config/            # Settings, LLM factory (5 providers)
├── rag/               # Document loader, chunker, vector store, BM25, retriever, reranker
├── agents/            # Orchestrator, IT Help, Knowledge, Triage, Workflow agents
├── tools/             # Pydantic schemas, simulated backends, ToolRegistry
├── evals/             # 30-test YAML suite, guardrails, eval runner
├── observability/     # Langfuse tracer with local JSONL fallback
├── app/               # CLI entry point
├── docker/            # Dockerfile + docker-compose
└── .github/workflows/ # eval gate (PR) + Docker build (merge)
```

---

## CI/CD Pipeline

```
PR opened → eval.yml → 30 tests → block if <80% pass rate
PR merged → docker.yml → build image → push ghcr.io/Premchand916/agentops-hub:latest
```

---

## Key Design Decisions

**Why hybrid RAG?** Pure dense search misses exact keyword matches (error codes, ticket IDs). Pure BM25 misses semantic similarity. RRF fusion + reranking gives the best of both — tested against 8 RAG quality cases.

**Why LangGraph over CrewAI/AutoGen?** Explicit state graph with typed state (TypedDict) makes routing deterministic and debuggable. No magic orchestration — every transition is a function you can test.

**Why MCP-inspired ToolRegistry over direct function calling?** Decouples tool discovery from tool execution. Agents query the registry at runtime — adding a new tool requires zero agent code changes.

**Why local JSONL fallback for Langfuse?** Dev works fully offline. Prod routes to Langfuse cloud by setting env vars. No code change required.

---

## Author

**Prem Chand** — GenAI Engineer | AI Agent Developer | LLM Application Builder

- GitHub: [@Premchand916](https://github.com/Premchand916)
- LinkedIn: [premchand24](https://linkedin.com/in/premchand24)
