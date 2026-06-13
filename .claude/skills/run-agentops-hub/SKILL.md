---
name: run-agentops-hub
description: Build, run, and drive agentops-hub. Use when asked to start agentops-hub, run its agents, test it, smoke-test the multi-agent system, verify routing, check RAG answers, or confirm tool calling works.
---

AgentOps Hub is a Python multi-agent assistant driven programmatically via
`AgentHub.chat()`. The primary agent path is
`.claude/skills/run-agentops-hub/smoke.py` — a Python driver that boots the
full system, ingests documents, and sends representative queries to each
specialist agent. The interactive CLI (`app/cli.py`) is the human path.

All paths below are relative to `agentops-hub/`.

## Prerequisites

- Python 3.11+ (tested on 3.14)
- [Ollama](https://ollama.com) running with both models pulled
- Docker Desktop must **not** occupy port 11434 on IPv6 — see Gotchas

```bash
ollama pull llama3.2:3b
ollama pull nomic-embed-text
```

Verify Ollama is reachable:

```bash
curl -s http://127.0.0.1:11434/api/tags | python3 -c "import sys,json; print([m['name'] for m in json.load(sys.stdin)['models']])"
# → ['nomic-embed-text:latest', 'llama3.2:3b', ...]
```

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -e .
pip install pytest
```

## Run (agent path)

```bash
source venv/bin/activate
python .claude/skills/run-agentops-hub/smoke.py          # 7 checks, ~25s
python .claude/skills/run-agentops-hub/smoke.py --quick  # 4 routing-only checks, ~26s
```

Expected output (all checks):

```
  [PASS] Ingest succeeded  docs=3  chunks=17  vectors=17
  [PASS] IT routing        agent=IT_HELP/IT_HELP   conf=88%  t=7.0s
  [PASS] KNOWLEDGE rout    agent=KNOWLEDGE/KNOWLEDGE conf=92%  t=4.3s
  [PASS] WORKFLOW rout     agent=WORKFLOW/WORKFLOW  conf=98%  t=0.0s
  [PASS] TRIAGE rout       agent=TRIAGE/TRIAGE     conf=50%  t=6.6s
  [PASS] RAG answer        agent=IT_HELP/IT_HELP   conf=88%  t=3.6s
  [PASS] RAG source        agent=KNOWLEDGE/KNOWLEDGE conf=92%  t=2.7s
  [PASS] Tool exec         agent=WORKFLOW/WORKFLOW  conf=98%  t=0.0s
7/7 checks passed (25.4s total)
```

The driver calls `AgentHub.chat(query)` directly — no subprocess, no port.
Results are a dict with `handled_by`, `answer`, `sources`, and `routing`.

To call a single query programmatically:

```python
import os, sys
os.chdir("/path/to/agentops-hub")   # required — code uses relative paths
sys.path.insert(0, os.getcwd())
from agents.graph import AgentHub
hub = AgentHub()
hub.ingest("rag/Documents")
result = hub.chat("My VPN shows error E-4012")
print(result["handled_by"], result["answer"])
```

## Run (human path)

```bash
source venv/bin/activate
python app/cli.py
# → interactive prompt; type queries, "quit" to exit
```

Note: `app/cli.py` uses `rag/Documents` (capital D). The eval runner uses
`rag/documents` (lowercase). macOS is case-insensitive so both work.

## Test

```bash
source venv/bin/activate
python -m pytest tests/ -v
# → 5 passed in ~0.5s (no Ollama needed)

python evals/run_evals.py
# → 30 tests across routing / RAG quality / tool calling, ~5–10 min
```

## Gotchas

- **Docker Desktop steals IPv6 port 11434** — on macOS with Docker Desktop
  running, `localhost:11434` resolves to `::1` and Docker intercepts it before
  Ollama. The fix is already in `.env` (`OLLAMA_BASE_URL=http://127.0.0.1:11434`).
  If you ever reset `.env`, use `127.0.0.1`, never `localhost`.

- **FlashRank model downloads on first run** — `ms-marco-MiniLM-L-12-v2`
  (~22 MB) is downloaded to `~/.cache/flashrank/` on the very first boot.
  Expect a 5–10s delay before the first ingestion completes.

- **os.chdir() is required before importing agents** — multiple modules
  (`agents/orchestrator.py`, `rag/rag_chain.py`) open files with relative
  paths (`config/prompts/system_prompts.yaml`, `rag/Documents`). Always
  `os.chdir(PROJECT_ROOT)` before any import from this project.

- **Qdrant is in-memory** — vectors reset on every process start. `ingest()`
  must be called before `chat()` in every session.

- **LLM output is non-deterministic** — routing via keyword match is stable
  (confidence 0.88–0.98); LLM-fallback routing is lower confidence (~0.5)
  and may vary. The TRIAGE check passes because the orchestrator
  correctly falls back to TRIAGE for ambiguous queries (confidence < 0.7
  threshold).

## Troubleshooting

- **`ollama._types.ResponseError: model not found`** — run
  `curl -s http://127.0.0.1:11434/api/tags` and confirm models appear. If
  the list is empty but `ollama list` shows models, Docker is intercepting
  on IPv6. Fix: ensure `.env` has `OLLAMA_BASE_URL=http://127.0.0.1:11434`.

- **`FileNotFoundError: Directory not found: .../rag/Documents`** — the
  script was not started from the project root, or `os.chdir()` didn't
  run. Confirm `PROJECT_ROOT` printed at startup matches `agentops-hub/`.

- **`No module named 'agents'`** — venv not activated, or `pip install -e .`
  wasn't run. Run both, then retry.
