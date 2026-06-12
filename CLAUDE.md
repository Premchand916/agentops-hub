# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install (from agentops-hub/)
pip install -r requirements.txt
pip install -e .
pip install pytest   # not in requirements.txt, needed for test suite

# Pull required Ollama models (must be running before starting the app)
ollama pull llama3.2:3b
ollama pull nomic-embed-text

# Run the CLI app
python app/cli.py

# Run quick smoke tests (fast, no Ollama needed)
python test_step1.py   # validates BackendServices + tool schemas
python test_step2.py   # validates ToolRegistry execution

# Run the full evaluation suite (CI quality gate, requires Ollama)
python evals/run_evals.py

# Run unit tests (fast, no Ollama needed)
python -m pytest tests/
python -m pytest tests/test_regressions.py::BM25RegressionTests::test_hyphenated_error_codes_are_preserved

# Docker
cd docker && docker compose up --build
docker exec -it agentops-app python app/cli.py
```

## Architecture

The system is a multi-agent AI assistant that routes employee requests (IT support, knowledge lookup, workflow actions) to specialist agents using a LangGraph `StateGraph`.

**Request flow:**
```
User input → AgentHub.chat() → LangGraph StateGraph → OrchestratorAgent.route()
  → conditional edge → specialist agent → END
```

**Key entry points:**
- `agents/graph.py` — `AgentHub` class and `build_agent_graph()`. The only public API callers need: `hub.ingest(path)` then `hub.chat(message)`.
- `app/cli.py` — CLI entry point that calls `AgentHub`.

**Agent routing (`agents/orchestrator.py`):**
The orchestrator first tries keyword-based fast routing (deterministic, no LLM call). If no keyword match, it calls the LLM for JSON output. Routing confidence < 0.7 forces fallback to `TRIAGE`. After 3 failed attempts, the state machine forces `TRIAGE`.

**Shared state (`agents/state.py`):**
All agents communicate through `AgentState` (a `TypedDict`). Key fields: `messages`, `target_agent`, `routing_confidence`, `final_answer`, `sources`, `handled_by`. The `messages` field uses `operator.add` annotation so all agents append rather than replace.

**RAG pipeline (`rag/`):**
`RAGChain.ingest()` runs a 4-step pipeline: load docs → chunk → embed into Qdrant → build BM25 index. `RAGChain.query()` does hybrid retrieval (BM25 + dense vector via `HybridRetriever`), then reranks with FlashRank (`ms-marco-MiniLM-L-12-v2`), then generates a grounded answer. Documents live in `rag/documents/`.

**Tool system (`tools/`):**
`ToolRegistry` is an MCP-inspired pattern decoupling tool discovery from execution. Tools are registered with a `ToolDefinition` (Pydantic schema) and a handler function from `BackendServices`. Agents call `registry.execute_tool_safe()` which never raises — errors come back as a dict with `success: False`. Available tools: `create_ticket`, `search_tickets`, `get_system_status`, `send_notification`.

**Observability (`observability/tracer.py`):**
Singleton `tracer` (imported as `from observability.tracer import tracer`) wraps every `AgentHub.chat()` call. Primary backend is Langfuse (set `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` in `.env`). Falls back silently to local `traces/traces.jsonl` when Langfuse is unreachable. `AgentHub.stats()` reads from the local JSONL.

**Config (`config/`):**
`Settings` (pydantic-settings) reads from `.env`. Override any setting via env vars. `get_llm()` and `get_embeddings()` in `llm_factory.py` are the only places that instantiate LLM clients — all agents import from there.

**Evaluation (`evals/`):**
`run_evals.py` runs 30 YAML-defined tests from `evals/test_cases/eval_suite.yaml` against a live `AgentHub`. Three categories: routing accuracy (>90% threshold), RAG keyword quality (>80%), tool calling (>95%). Exit code 1 if overall pass rate < 80%. This is the CI gate.

**Guardrails (`evals/guardrails.py`):**
PII detection, topic scope enforcement, and hallucination checks run as a separate evaluation category.

## Environment Variables

The `.env` file configures everything. Key variables:

```
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_CHAT_MODEL=llama3.2:3b
OLLAMA_EMBEDDING_MODEL=nomic-embed-text

# Optional: Langfuse observability (omit to use local JSONL fallback)
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_SECRET_KEY=...
LANGFUSE_HOST=https://cloud.langfuse.com

QDRANT_IN_MEMORY=true   # set false + configure host/port for persistent Qdrant
```

## Known Issues

- `tools/schemas.py:196` — Pydantic v2 deprecation warning (`class Config` instead of `model_config = ConfigDict(...)`). Functional but flagged by pytest.

## CI/CD

- **PR gate** (`.github/workflows/eval.yml`): runs `python evals/run_evals.py`, blocks merge if pass rate < 80%.
- **Merge** (`.github/workflows/docker.yml`): builds and pushes Docker image to `ghcr.io/Premchand916/agentops-hub:latest`.

## Planned Extension: A2A v1.0 Protocol Layer

The next phase adds an [A2A (Agent-to-Agent) v1.0](https://github.com/a2aproject/A2A) protocol layer on top of the existing system — a standardized cross-organization communication protocol. The existing codebase is untouched; A2A is purely additive.

**New folder:** `app/a2a/` — built session by session:

| Session | Module | What it adds |
|---------|--------|--------------|
| 1 | `agent_card.py` | Agent Card discovery (`/.well-known/agent.json`) |
| 2 | `jsonrpc.py`, `tasks.py` | JSON-RPC 2.0 router; `AgentHub.chat()` is the integration point |
| 3 | `state_machine.py` | A2A task lifecycle (submitted → working → completed/failed/canceled) |
| 4 | `streaming.py` | SSE streaming via `graph.astream()` |
| 5 | `webhooks.py` | HMAC-signed push notifications |
| 6 | `signing.py` | Signed Agent Cards (JWS/RS256 + JWKS endpoint) |
| 8 | `policy.py` | HITL governance; extends `observability/tracer.py` |
| 9 | `tests/a2a_compliance/` | 25-test protocol-compliance suite added to CI |

**Additional deps needed before Session 1:**
```bash
pip install sse-starlette python-jose[cryptography] httpx tenacity sseclient-py
```

**Integration points in existing code:**
- `agents/graph.py` → `AgentHub.chat()` becomes the JSON-RPC handler target
- `agents/state.py` → `AgentState` concept is extended by the A2A task state machine
- `tools/backends.py` → notification service maps to A2A webhook dispatcher
- `observability/tracer.py` → extended with A2A trace spans for HITL
