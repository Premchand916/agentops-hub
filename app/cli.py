"""
AgentOps Hub — Interactive CLI (Multi-Agent Version)
======================================================

WHAT CHANGED FROM SESSION 1:
Before: User → RAG → Answer
Now:    User → Orchestrator → Specialist Agent → RAG → Answer

The user experience is the same (type question, get answer),
but behind the scenes, an orchestrator decides which specialist
handles the request. The CLI now also shows WHICH agent handled
the query — important for debugging and building trust.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("google_genai.models").setLevel(logging.WARNING)

from rich import print as rprint
from rich.panel import Panel
from rich.prompt import Prompt
from agents.graph import AgentHub


def print_banner():
    """Print the application banner."""
    rprint(Panel.fit(
        "[bold cyan]🏥 AgentOps Hub — Multi-Agent Operations Assistant[/bold cyan]\n\n"
        "Ask questions about IT support, company policies, or procedures.\n"
        "The system automatically routes to the right specialist agent.\n\n"
        "Commands:\n"
        "  [bold]quit[/bold] / [bold]exit[/bold]  — Stop the application\n"
        "  [bold]stats[/bold]       — Show knowledge base info",
        title="Welcome",
        border_style="cyan",
    ))


def main():
    """Main CLI loop with multi-agent routing."""
    print_banner()
    
    # --- Initialize ---
    rprint("\n[bold]🔧 Initializing multi-agent system...[/bold]\n")
    
    try:
        hub = AgentHub()
    except Exception as e:
        rprint(f"[red]❌ Failed to initialize: {e}[/red]")
        rprint("[yellow]Check that your .env file has a valid GOOGLE_API_KEY[/yellow]")
        sys.exit(1)
    
    # Ingest documents
    documents_path = "rag/documents"
    
    try:
        stats = hub.ingest(documents_path)
        if stats["status"] != "success":
            rprint("[red]❌ Ingestion failed.[/red]")
            sys.exit(1)
    except Exception as e:
        rprint(f"[red]❌ Ingestion error: {e}[/red]")
        sys.exit(1)
    
    # --- Interactive loop ---
    rprint("\n[bold green]✅ Ready! Ask me anything.\n[/bold green]")
    
    while True:
        try:
            question = Prompt.ask("\n[bold]You[/bold]")
            
            # Handle commands
            if question.lower() in ("quit", "exit", "q"):
                rprint("[cyan]👋 Goodbye![/cyan]")
                break
            
            if question.lower() == "stats":
                info = hub.rag_chain.vector_store.get_collection_info()
                rprint(Panel.fit(
                    f"Collection: {info.get('name', 'N/A')}\n"
                    f"Vectors: {info.get('vectors_count', 'N/A')}\n"
                    f"Points: {info.get('points_count', 'N/A')}",
                    title="Knowledge Base Stats",
                ))
                continue
            
            if not question.strip():
                continue
            
            # --- Route through multi-agent system ---
            result = hub.chat(question)
            
            # Display answer
            rprint(f"\n[bold green]💬 Answer:[/bold green]")
            rprint(result["answer"])
            
            # Show which agent handled it
            agent_name = result.get("handled_by", "UNKNOWN")
            confidence = result.get("routing", {}).get("confidence", 0)
            
            agent_colors = {
                "IT_HELP": "green",
                "KNOWLEDGE": "blue",
                "TRIAGE": "yellow",
                "WORKFLOW": "magenta",
            }
            color = agent_colors.get(agent_name, "white")
            
            rprint(f"\n[{color}]🏷️  Handled by: {agent_name} "
                   f"(routing confidence: {confidence:.0%})[/{color}]")
            
            # Show sources if available
            sources = result.get("sources", [])
            if sources:
                rprint(f"[dim]📚 Sources:[/dim]")
                for s in sources:
                    score = s.get("rerank_score", 0)
                    if score > 0:
                        rprint(f"[dim]  • {s.get('file', 'unknown')} "
                               f"(relevance: {score:.3f})[/dim]")
            
        except KeyboardInterrupt:
            rprint("\n[cyan]👋 Goodbye![/cyan]")
            break
        except Exception as e:
            rprint(f"[red]❌ Error: {e}[/red]")
            rprint("[yellow]Try rephrasing your question.[/yellow]")


if __name__ == "__main__":
    main()