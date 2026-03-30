"""
observability/tracer.py
========================
Langfuse-based observability for AgentOps Hub.

Architecture:
  - Primary:  Langfuse SDK (cloud or self-hosted)
  - Fallback: Local JSON file (traces/traces.jsonl) if Langfuse unreachable

Every instrumented call produces:
  trace → spans → (latency, token_cost, eval_score, agent_name, status)

Usage:
  tracer = AgentTracer()

  # Context manager per user request
  with tracer.trace("user message") as ctx:
      with ctx.span("orchestrator", agent="ORCHESTRATOR"):
          ...
      with ctx.span("it_help", agent="IT_HELP"):
          ...
"""

import os
import json
import time
import uuid
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any

from rich import print as rprint


# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "local-dev")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "local-dev")
LANGFUSE_HOST       = os.getenv("LANGFUSE_HOST", "http://localhost:3000")

LOCAL_TRACE_DIR  = Path("traces")
LOCAL_TRACE_FILE = LOCAL_TRACE_DIR / "traces.jsonl"


# ─────────────────────────────────────────────
# SPAN CONTEXT  (nested span tracking)
# ─────────────────────────────────────────────

class SpanContext:
    """Tracks a single span (LLM call / retrieval / tool execution)."""

    def __init__(self, name: str, trace_id: str, metadata: dict, lf_span=None, local_log: list = None):
        self.name       = name
        self.trace_id   = trace_id
        self.span_id    = str(uuid.uuid4())[:8]
        self.metadata   = metadata
        self.lf_span    = lf_span          # Langfuse span object (or None)
        self.local_log  = local_log        # reference to trace's local event list
        self.start_time = time.perf_counter()
        self.start_iso  = datetime.now(timezone.utc).isoformat()
        self.status     = "ok"
        self.output     = None
        self.error      = None

    def record_output(self, output: Any, tokens: Optional[int] = None, score: Optional[float] = None):
        self.output = str(output)[:500]   # cap at 500 chars
        if tokens:
            self.metadata["tokens"] = tokens
        if score is not None:
            self.metadata["eval_score"] = round(score, 4)

    def record_error(self, err: Exception):
        self.status = "error"
        self.error  = str(err)

    def _end(self):
        elapsed_ms = round((time.perf_counter() - self.start_time) * 1000, 1)
        self.metadata["latency_ms"] = elapsed_ms

        if self.lf_span:
            try:
                self.lf_span.end(
                    output=self.output,
                    metadata=self.metadata,
                    level="ERROR" if self.status == "error" else "DEFAULT",
                )
            except Exception:
                pass  # Langfuse offline — silent

        if self.local_log is not None:
            self.local_log.append({
                "span_id":    self.span_id,
                "name":       self.name,
                "start":      self.start_iso,
                "latency_ms": elapsed_ms,
                "status":     self.status,
                "output":     self.output,
                "error":      self.error,
                "metadata":   self.metadata,
            })


# ─────────────────────────────────────────────
# TRACE CONTEXT  (one per user request)
# ─────────────────────────────────────────────

class TraceContext:
    """Wraps a full user request trace. Holds child spans."""

    def __init__(self, user_message: str, trace_id: str, lf_trace=None):
        self.user_message = user_message
        self.trace_id     = trace_id
        self.lf_trace     = lf_trace
        self.spans: list  = []
        self.start_time   = time.perf_counter()
        self.start_iso    = datetime.now(timezone.utc).isoformat()

    @contextmanager
    def span(self, name: str, agent: str = "", **extra_meta):
        """
        Context manager for a single span.

        Usage:
            with trace_ctx.span("retrieval", agent="IT_HELP", query="VPN error") as s:
                results = rag.retrieve(query)
                s.record_output(results, tokens=120)
        """
        metadata = {"agent": agent, **extra_meta}
        lf_span  = None

        if self.lf_trace:
            try:
                lf_span = self.lf_trace.span(name=name, metadata=metadata)
            except Exception:
                pass

        sc = SpanContext(name, self.trace_id, metadata, lf_span=lf_span, local_log=self.spans)
        try:
            yield sc
        except Exception as e:
            sc.record_error(e)
            raise
        finally:
            sc._end()

    def _total_latency_ms(self) -> float:
        return round((time.perf_counter() - self.start_time) * 1000, 1)

    def _summary(self) -> dict:
        total_tokens = sum(s["metadata"].get("tokens", 0) for s in self.spans)
        avg_score    = None
        scores       = [s["metadata"]["eval_score"] for s in self.spans if "eval_score" in s["metadata"]]
        if scores:
            avg_score = round(sum(scores) / len(scores), 4)

        return {
            "trace_id":      self.trace_id,
            "user_message":  self.user_message[:200],
            "start":         self.start_iso,
            "total_ms":      self._total_latency_ms(),
            "total_tokens":  total_tokens,
            "avg_eval_score": avg_score,
            "span_count":    len(self.spans),
            "spans":         self.spans,
        }


# ─────────────────────────────────────────────
# MAIN TRACER
# ─────────────────────────────────────────────

class AgentTracer:
    """
    Top-level tracer. One instance per process.

    Initialization tries Langfuse; falls back to local JSON silently.
    Call tracer.trace(user_message) to get a TraceContext.
    """

    def __init__(self):
        self._lf       = None
        self._mode     = "local"
        self._init_langfuse()

        LOCAL_TRACE_DIR.mkdir(exist_ok=True)
        rprint(f"[cyan]🔭 Tracer: mode={self._mode}  log={LOCAL_TRACE_FILE}[/cyan]")

    # ── private ─────────────────────────────

    def _init_langfuse(self):
        """Try to connect to Langfuse. If it fails, stay in local mode."""
        if LANGFUSE_PUBLIC_KEY == "local-dev":
            rprint("[yellow]  LANGFUSE_PUBLIC_KEY not set — running in local trace mode[/yellow]")
            return

        try:
            from langfuse import Langfuse
            self._lf   = Langfuse(
                public_key=LANGFUSE_PUBLIC_KEY,
                secret_key=LANGFUSE_SECRET_KEY,
                host=LANGFUSE_HOST,
            )
            self._mode = "langfuse"
            rprint(f"[green]  Langfuse connected → {LANGFUSE_HOST}[/green]")
        except Exception as e:
            rprint(f"[yellow]  Langfuse unavailable ({e}) — local mode[/yellow]")

    def _new_lf_trace(self, user_message: str, trace_id: str):
        if self._lf is None:
            return None
        try:
            return self._lf.trace(
                id=trace_id,
                name="agent_request",
                input=user_message,
                metadata={"source": "agentops-hub"},
            )
        except Exception:
            return None

    def _write_local(self, summary: dict):
        """Append trace summary to JSONL file."""
        try:
            with open(LOCAL_TRACE_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(summary) + "\n")
        except Exception as e:
            rprint(f"[red]  Trace write failed: {e}[/red]")

    # ── public ──────────────────────────────

    @contextmanager
    def trace(self, user_message: str):
        """
        Main context manager. Wraps a full user request.

        Usage:
            with tracer.trace(user_message) as ctx:
                with ctx.span("orchestrator", agent="ORCHESTRATOR") as s:
                    result = orchestrator.route(state)
                    s.record_output(result)
        """
        trace_id = str(uuid.uuid4())[:12]
        lf_trace = self._new_lf_trace(user_message, trace_id)
        ctx      = TraceContext(user_message, trace_id, lf_trace=lf_trace)

        try:
            yield ctx
        except Exception as e:
            rprint(f"[red]  Trace {trace_id} errored: {e}[/red]")
            raise
        finally:
            summary = ctx._summary()
            self._write_local(summary)

            # End Langfuse trace
            if lf_trace:
                try:
                    lf_trace.update(
                        output=summary.get("spans", [{}])[-1].get("output", ""),
                        metadata={
                            "total_ms":     summary["total_ms"],
                            "total_tokens": summary["total_tokens"],
                        },
                    )
                    self._lf.flush()
                except Exception:
                    pass

            rprint(
                f"[dim]  trace={trace_id} | "
                f"{summary['span_count']} spans | "
                f"{summary['total_ms']}ms | "
                f"tokens={summary['total_tokens']}[/dim]"
            )

    # ── analytics helpers ───────────────────

    def load_traces(self, last_n: int = 50) -> list[dict]:
        """Load last N traces from local JSONL for dashboard/analysis."""
        if not LOCAL_TRACE_FILE.exists():
            return []
        lines = LOCAL_TRACE_FILE.read_text(encoding="utf-8").strip().splitlines()
        return [json.loads(l) for l in lines[-last_n:]]

    def summary_stats(self, last_n: int = 50) -> dict:
        """Aggregate stats across last N traces."""
        traces = self.load_traces(last_n)
        if not traces:
            return {"error": "No traces found"}

        latencies = [t["total_ms"] for t in traces]
        tokens    = [t["total_tokens"] for t in traces]
        scores    = [t["avg_eval_score"] for t in traces if t.get("avg_eval_score") is not None]

        return {
            "trace_count":      len(traces),
            "avg_latency_ms":   round(sum(latencies) / len(latencies), 1),
            "p95_latency_ms":   round(sorted(latencies)[int(len(latencies) * 0.95)], 1),
            "total_tokens":     sum(tokens),
            "avg_tokens":       round(sum(tokens) / len(tokens), 1),
            "avg_eval_score":   round(sum(scores) / len(scores), 4) if scores else None,
        }


# ─────────────────────────────────────────────
# SINGLETON  (import once, use everywhere)
# ─────────────────────────────────────────────

tracer = AgentTracer()