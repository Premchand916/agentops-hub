"""
AgentOps Hub - Interactive CLI (Multi-Agent Version)

This CLI now runs fully local with Ollama for chat generation and embeddings.
"""

import os
import sys
import json
from urllib import error, request

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJECT_ROOT)
sys.path.insert(0, PROJECT_ROOT)

import logging
logging.getLogger("httpx").setLevel(logging.WARNING)

from rich import print as rprint
from rich.panel import Panel
from rich.prompt import Prompt

from agents.graph import AgentHub
from config.settings import get_settings


def print_banner():
    """Print the application banner."""
    rprint(Panel.fit(
        "[bold cyan]AgentOps Hub - Local Ollama Assistant[/bold cyan]\n\n"
        "Ask questions about IT support, company policies, or procedures.\n"
        "The system routes to the right specialist agent and stays fully local.\n"
        "Run `agentops-hub doctor` if you want to verify the Ollama setup first.\n\n"
        "Commands:\n"
        "  [bold]quit[/bold] / [bold]exit[/bold]  - Stop the application\n"
        "  [bold]stats[/bold]       - Show knowledge base info",
        title="Welcome",
        border_style="cyan",
    ))


def _validate_ollama_runtime(settings) -> dict:
    """Verify that Ollama is reachable and the configured models exist."""
    _require_setting(settings.ollama_base_url, "OLLAMA_BASE_URL")
    _require_setting(settings.ollama_chat_model, "OLLAMA_CHAT_MODEL")
    _require_setting(settings.ollama_embedding_model, "OLLAMA_EMBEDDING_MODEL")

    base_url = settings.ollama_base_url.rstrip("/")
    endpoint = f"{base_url}/api/tags"

    try:
        with request.urlopen(endpoint, timeout=settings.ollama_timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        raise RuntimeError(
            f"Ollama returned HTTP {exc.code} from {endpoint}. "
            "Check that the local server is healthy."
        ) from exc
    except error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise RuntimeError(
            f"Could not reach Ollama at {base_url}: {reason}. "
            "Start Ollama locally before launching the app."
        ) from exc
    except TimeoutError as exc:
        raise RuntimeError(
            f"Ollama did not respond within {settings.ollama_timeout_seconds} seconds."
        ) from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Ollama returned an unreadable response from {endpoint}."
        ) from exc

    available_models = []
    for item in payload.get("models", []):
        name = item.get("name") or item.get("model")
        if name:
            available_models.append(name)

    missing_models = []
    for kind, model_name in (
        ("chat", settings.ollama_chat_model),
        ("embedding", settings.ollama_embedding_model),
    ):
        if not _model_available(model_name, available_models):
            missing_models.append((kind, model_name))

    if missing_models:
        missing_text = ", ".join(
            f"{kind} model '{model_name}'" for kind, model_name in missing_models
        )
        available_text = ", ".join(available_models) if available_models else "none"
        raise RuntimeError(
            f"Ollama is running, but the configured {missing_text} is not installed. "
            f"Available models: {available_text}."
        )

    return {
        "base_url": base_url,
        "chat_model": settings.ollama_chat_model,
        "embedding_model": settings.ollama_embedding_model,
        "available_models": available_models,
    }


def _model_available(configured_model: str, available_models: list[str]) -> bool:
    configured_aliases = _model_aliases(configured_model)
    available_aliases = set()
    for model_name in available_models:
        available_aliases.update(_model_aliases(model_name))
    return any(alias in available_aliases for alias in configured_aliases)


def _model_aliases(model_name: str) -> set[str]:
    stripped = model_name.strip()
    if not stripped:
        return set()

    if ":" in stripped:
        base_name, tag = stripped.rsplit(":", 1)
        if tag == "latest":
            return {stripped, base_name}
        return {stripped}

    return {stripped, f"{stripped}:latest"}


def _require_setting(value: str, env_var: str) -> None:
    if not value or not value.strip():
        raise RuntimeError(f"Missing required setting: {env_var}")


def _build_ollama_hint(settings) -> str:
    """Return a startup hint for the local Ollama setup."""
    return (
        "Make sure Ollama is running locally and the required models exist. "
        f"Current chat model: {settings.ollama_chat_model}. "
        f"Current embedding model: {settings.ollama_embedding_model}. "
        "Use `ollama serve` if the local server is not already running, then use "
        "`ollama list` to inspect local models. If needed, run "
        f"`ollama pull {settings.ollama_chat_model}` and "
        f"`ollama pull {settings.ollama_embedding_model}`. "
        "You can also run `agentops-hub doctor` for a quick Ollama health check."
    )


def _probe_chat_model(settings) -> None:
    """Run a tiny chat request to catch runtime issues like OOM early."""
    body = json.dumps({
        "model": settings.ollama_chat_model,
        "messages": [
            {"role": "user", "content": "Reply with the single word: ready."}
        ],
        "stream": False,
        "options": {
            "num_ctx": 2048,
            "num_predict": min(settings.ollama_num_predict, 8),
        },
    }).encode("utf-8")

    request_obj = request.Request(
        url=f"{settings.ollama_base_url.rstrip('/')}/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(request_obj, timeout=settings.ollama_timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Ollama chat probe failed with HTTP {exc.code}: {details}"
        ) from exc
    except error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise RuntimeError(f"Ollama chat probe failed: {reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError(
            f"Ollama chat probe timed out after {settings.ollama_timeout_seconds} seconds."
        ) from exc

    message = payload.get("message", {}).get("content", "").strip().lower()
    if not message:
        raise RuntimeError("Ollama chat probe returned an empty response.")


def _run_doctor(settings) -> int:
    """Validate the local Ollama runtime and print a short report."""
    try:
        runtime = _validate_ollama_runtime(settings)
        _probe_chat_model(settings)
    except RuntimeError as exc:
        rprint(f"[red]Ollama check failed: {exc}[/red]")
        rprint(f"[yellow]{_build_ollama_hint(settings)}[/yellow]")
        return 1

    available_models = ", ".join(runtime["available_models"]) or "none"
    rprint(Panel.fit(
        f"[green]Ollama is reachable[/green]\n\n"
        f"Base URL: {runtime['base_url']}\n"
        f"Chat Model: {runtime['chat_model']}\n"
        f"Embedding Model: {runtime['embedding_model']}\n"
        f"Available Models: {available_models}",
        title="Ollama Doctor",
        border_style="green",
    ))
    return 0


def main():
    """Main CLI loop with multi-agent routing."""
    settings = get_settings()
    if len(sys.argv) > 1 and sys.argv[1].lower() == "doctor":
        sys.exit(_run_doctor(settings))

    print_banner()

    try:
        runtime = _validate_ollama_runtime(settings)
    except RuntimeError as e:
        rprint(f"[red]Ollama validation failed: {e}[/red]")
        rprint(f"[yellow]{_build_ollama_hint(settings)}[/yellow]")
        sys.exit(1)

    rprint(
        f"[dim]Using local Ollama chat model {runtime['chat_model']} "
        f"and embeddings {runtime['embedding_model']} at "
        f"{runtime['base_url']}.[/dim]"
    )

    rprint("\n[bold]Initializing multi-agent system...[/bold]\n")

    try:
        hub = AgentHub()
    except Exception as e:
        rprint(f"[red]Failed to initialize: {e}[/red]")
        rprint(f"[yellow]{_build_ollama_hint(settings)}[/yellow]")
        sys.exit(1)

    documents_path = os.path.join(PROJECT_ROOT, "rag", "Documents")

    try:
        stats = hub.ingest(documents_path)
        if stats["status"] != "success":
            rprint("[red]Ingestion failed.[/red]")
            sys.exit(1)
    except Exception as e:
        rprint(f"[red]Ingestion error: {e}[/red]")
        rprint(f"[yellow]{_build_ollama_hint(settings)}[/yellow]")
        sys.exit(1)

    rprint("\n[bold green]Ready! Ask me anything.\n[/bold green]")

    while True:
        try:
            question = Prompt.ask("\n[bold]You[/bold]")

            if question.lower() in ("quit", "exit", "q"):
                rprint("[cyan]Goodbye![/cyan]")
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

            result = hub.chat(question)

            rprint("\n[bold green]Answer:[/bold green]")
            rprint(result["answer"])

            agent_name = result.get("handled_by", "UNKNOWN")
            confidence = result.get("routing", {}).get("confidence", 0)

            agent_colors = {
                "IT_HELP": "green",
                "KNOWLEDGE": "blue",
                "TRIAGE": "yellow",
                "WORKFLOW": "magenta",
            }
            color = agent_colors.get(agent_name, "white")

            rprint(
                f"\n[{color}]Handled by: {agent_name} "
                f"(routing confidence: {confidence:.0%})[/{color}]"
            )

            sources = result.get("sources", [])
            if sources:
                rprint("[dim]Sources:[/dim]")
                for s in sources:
                    score = s.get("rerank_score", 0)
                    if score > 0:
                        rprint(
                            f"[dim]  - {s.get('file', 'unknown')} "
                            f"(relevance: {score:.3f})[/dim]"
                        )

        except KeyboardInterrupt:
            rprint("\n[cyan]Goodbye![/cyan]")
            break
        except Exception as e:
            rprint(f"[red]Error: {e}[/red]")
            rprint("[yellow]Try rephrasing your question.[/yellow]")


if __name__ == "__main__":
    main()


