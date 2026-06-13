#!/usr/bin/env python3
"""
AgentOps Hub — programmatic smoke driver.

Drives the multi-agent system directly via the AgentHub API.
Runs a representative query for each agent type and prints pass/fail.

Usage (from agentops-hub/):
    source venv/bin/activate
    python .claude/skills/run-agentops-hub/smoke.py [--quick]

    --quick  skip the RAG-heavy queries (routing checks only, ~2x faster)
"""

import os
import sys
import argparse
import time
# Resolve project root regardless of cwd
SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SKILL_DIR, "..", "..", ".."))
os.chdir(PROJECT_ROOT)
sys.path.insert(0, PROJECT_ROOT)

import logging
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

from agents.graph import AgentHub  # noqa: E402


SMOKE_QUERIES = [
    
    # (label, query, expected_agent, skip_if_quick)
    ("IT routing",    "My VPN shows error E-4012",          "IT_HELP",   False),
    ("KNOWLEDGE rout","What is the PTO policy?",            "KNOWLEDGE", False),
    ("WORKFLOW rout", "Create a ticket for my broken laptop","WORKFLOW",  False),
    ("TRIAGE rout",   "I need help with something",         "TRIAGE",    False),
    ("RAG answer",    "How do I reset my Outlook password?", "IT_HELP",   True),
    ("RAG source",    "What are the leave accrual rules?",  "KNOWLEDGE", True),
    ("Tool exec",     "Search tickets for VPN",             "WORKFLOW",  True),
]

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
DIM    = "\033[2m"
RESET  = "\033[0m"
BOLD   = "\033[1m"


def check(label, passed, detail=""):
    mark = f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}"
    line = f"  [{mark}] {label}"
    if detail:
        line += f"  {DIM}{detail}{RESET}"
    print(line)
    return passed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true",
                        help="Routing checks only (skips full RAG queries)")
    args = parser.parse_args()

    print(f"\n{BOLD}AgentOps Hub — Smoke Driver{RESET}")
    print(f"Project root: {PROJECT_ROOT}\n")

    # ── Boot ────────────────────────────────────────────────────────────
    t0 = time.perf_counter()
    print("Booting AgentHub (ingest + graph compile)…")
    hub = AgentHub()
    docs_path = os.path.join(PROJECT_ROOT, "rag", "Documents")
    stats = hub.ingest(docs_path)
    boot_s = time.perf_counter() - t0

    ok = check("Ingest succeeded",
               stats["status"] == "success",
               f"docs={stats.get('documents_loaded',0)}  "
               f"chunks={stats.get('chunks_created',0)}  "
               f"vectors={stats.get('vectors_stored',0)}")
    if not ok:
        print(f"\n{RED}Ingestion failed — aborting.{RESET}")
        sys.exit(1)
    print(f"  {DIM}Boot time: {boot_s:.1f}s{RESET}\n")

    # ── Queries ─────────────────────────────────────────────────────────
    print(f"Running {'routing-only ' if args.quick else ''}smoke queries…\n")
    results = []
    for label, query, expected, skip_if_quick in SMOKE_QUERIES:
        if args.quick and skip_if_quick:
            continue

        t1 = time.perf_counter()
        result = hub.chat(query)
        elapsed = time.perf_counter() - t1

        actual = result.get("handled_by", "UNKNOWN")
        conf   = result.get("routing", {}).get("confidence", 0)
        answer = result.get("answer", "")

        passed = actual == expected
        detail = (f"agent={actual}/{expected}  "
                  f"conf={conf:.0%}  "
                  f"t={elapsed:.1f}s  "
                  f"ans={answer[:60].replace(chr(10),' ')!r}")
        results.append(check(label, passed, detail))

    # ── Summary ─────────────────────────────────────────────────────────
    n_pass = sum(results)
    n_total = len(results)
    total_s = time.perf_counter() - t0
    color = GREEN if n_pass == n_total else RED
    print(f"\n{color}{BOLD}{n_pass}/{n_total} checks passed{RESET}  "
          f"{DIM}({total_s:.1f}s total){RESET}\n")

    if n_pass < n_total:
        print(f"{YELLOW}Tip: run `python evals/run_evals.py` for the full 30-test suite.{RESET}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
