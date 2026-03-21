"""
AgentOps Hub — Interactive CLI
=================================

This is the "front door" of our application.
Run it and ask questions about company docs.

HOW TO RUN:
    python app/cli.py

WHAT HAPPENS:
1. Loads and indexes all documents (one-time)
2. Starts an interactive loop
3. You type questions, it returns RAG-grounded answers with sources

WHY A CLI FIRST (not a web UI)?
In professional AI engineering, you ALWAYS start with a CLI.
Reasons:
1. Fastest to build — no HTML, no CSS, no JavaScript
2. Easiest to debug — you see everything in the terminal
3. Easy to automate — pipe queries from a file for batch testing
4. The UI is separate from the brain — we'll add Slack/web UI later
   without changing ANY of the RAG or agent code

This is the separation of concerns principle in action.
The CLI is just one "skin" over the same engine.
"""

import sys
import os

# Add project root to Python path so imports work
# WHY: When you run "python app/cli.py", Python looks for modules
# starting from the "app/" directory. But our modules are in the
# project root. This line tells Python to also look in the root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rich import print as rprint
from rich.panel import Panel
from rich.prompt import Prompt
from rag.rag_chain import RAGChain


def print_banner():
    """Print the application banner."""
    rprint(Panel.fit(
        "[bold cyan]🏥 AgentOps Hub — Knowledge Assistant[/bold cyan]\n\n"
        "Ask questions about company IT, policies, and procedures.\n"
        "Type [bold]'quit'[/bold] or [bold]'exit'[/bold] to stop.\n"
        "Type [bold]'stats'[/bold] to see knowledge base info.",
        title="Welcome",
        border_style="cyan",
    ))


def main():
    """Main CLI loop."""
    print_banner()
    
    # --- Initialize and ingest ---
    rprint("\n[bold]🔧 Initializing RAG pipeline...[/bold]\n")
    
    try:
        rag = RAGChain()
    except Exception as e:
        rprint(f"[red]❌ Failed to initialize: {e}[/red]")
        rprint("[yellow]Check that your .env file has a valid GOOGLE_API_KEY[/yellow]")
        sys.exit(1)
    
    # Ingest documents
    documents_path = "rag/documents"
    rprint(f"[bold]📥 Loading knowledge base from: {documents_path}[/bold]\n")
    
    try:
        stats = rag.ingest(documents_path)
        if stats["status"] != "success":
            rprint("[red]❌ Ingestion failed. Check your documents folder.[/red]")
            sys.exit(1)
    except Exception as e:
        rprint(f"[red]❌ Ingestion error: {e}[/red]")
        sys.exit(1)
    
    # --- Interactive loop ---
    rprint("[bold green]✅ Ready! Ask me anything about the knowledge base.\n[/bold green]")
    
    while True:
        try:
            # Get user input
            question = Prompt.ask("\n[bold]You[/bold]")
            
            # Handle special commands
            if question.lower() in ("quit", "exit", "q"):
                rprint("[cyan]👋 Goodbye![/cyan]")
                break
            
            if question.lower() == "stats":
                info = rag.vector_store.get_collection_info()
                rprint(Panel.fit(
                    f"Collection: {info.get('name', 'N/A')}\n"
                    f"Vectors: {info.get('vectors_count', 'N/A')}\n"
                    f"Points: {info.get('points_count', 'N/A')}",
                    title="Knowledge Base Stats",
                ))
                continue
            
            if not question.strip():
                continue
            
            # Query the RAG system
            result = rag.query(question)
            
        except KeyboardInterrupt:
            rprint("\n[cyan]👋 Goodbye![/cyan]")
            break
        except Exception as e:
            rprint(f"[red]❌ Error: {e}[/red]")
            rprint("[yellow]Try rephrasing your question.[/yellow]")


if __name__ == "__main__":
    main()