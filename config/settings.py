"""
AgentOps Hub — Centralized Configuration
==========================================

WHY THIS FILE EXISTS:
Instead of writing os.getenv("GOOGLE_API_KEY") in 15 different files,
we define ALL settings in ONE place. Every file imports from here.

REAL-WORLD ANALOGY:
Think of this as the hospital's "policy manual." Every doctor, nurse,
and receptionist follows the same policies. They don't each make up
their own rules. Same here — every agent, every RAG query, every
eval check reads from this one Settings class.

HOW IT WORKS:
1. Reads values from .env file automatically (via pydantic-settings)
2. Validates types (if QDRANT_PORT should be int, it checks that)
3. Provides defaults (so you don't crash if a non-critical env var is missing)

INTERVIEW TIP:
Q: "How do you manage configuration across a multi-service system?"
A: "I use a centralized settings module with pydantic-settings. It reads
   from environment variables, validates types, provides defaults, and
   is the single source of truth. Every component imports from one place.
   This prevents config drift where different parts of the system use
   different values for the same setting."
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from pydantic import Field


class Settings(BaseSettings):
    """
    Central configuration for the entire AgentOps Hub.
    
    All values are read from .env file or environment variables.
    Priority: environment variable > .env file > default value
    
    This means you can override ANY setting without changing code:
      - In development: values come from .env
      - In production: values come from environment variables (set by Docker/K8s)
      - In testing: you can override via environment variables in CI
    """
    
    # Tell pydantic-settings to read from .env file
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        # If an env var exists AND .env has it, env var wins
        extra="ignore"  # Don't crash on extra vars in .env
    )
    
    # =====================
    # LLM Configuration
    # =====================
    google_api_key: str = Field(
        description="Google Gemini API key"
    )
    gemini_model: str = Field(
        default="gemini-3-flash-preview",
        description="Which Gemini model to use. Flash for dev, Pro for production."
    )
    embedding_model: str = Field(
        default="models/gemini-embedding-2-preview",
        description="Google embedding model for RAG vectors",
        client_options={"api_endpoint": "generativelanguage.googleapis.com"},
        transport="rest"
    )
    
    # =====================
    # Vector Database
    # =====================
    qdrant_host: str = Field(
        default="localhost",
        description="Qdrant server host"
    )
    qdrant_port: int = Field(
        default=6333,
        description="Qdrant server port"
    )
    qdrant_in_memory: bool = Field(
        default=True,
        description="Use in-memory Qdrant (no server needed for development)"
    )
    qdrant_collection: str = Field(
        default="agentops_knowledge",
        description="Name of the vector collection"
    )
    
    # =====================
    # RAG Configuration
    # =====================
    rag_retrieval_top_k: int = Field(
        default=20,
        description="Number of chunks to retrieve before reranking"
    )
    rag_rerank_top_k: int = Field(
        default=5,
        description="Number of chunks to keep after reranking"
    )
    rag_chunk_size: int = Field(
        default=1000,
        description="Document chunk size in characters"
    )
    rag_chunk_overlap: int = Field(
        default=200,
        description="Overlap between consecutive chunks"
    )
    
    # =====================
    # Application
    # =====================
    log_level: str = Field(
        default="INFO",
        description="Logging level: DEBUG, INFO, WARNING, ERROR"
    )
    environment: str = Field(
        default="development",
        description="Runtime environment: development, staging, production"
    )


def get_settings() -> Settings:
    """
    Get the application settings (singleton pattern).
    
    WHY A FUNCTION:
    - First call: reads .env, creates Settings, validates everything
    - We can add caching later if needed (lru_cache)
    - Easy to mock in tests: just patch get_settings()
    
    USAGE:
        from config.settings import get_settings
        settings = get_settings()
        print(settings.google_api_key)
    """
    return Settings()


# =====================
# Quick self-test
# =====================
# Run this file directly to verify your .env is configured correctly:
#   python config/settings.py
if __name__ == "__main__":
    from rich import print as rprint
    from rich.panel import Panel
    
    try:
        settings = get_settings()
        rprint(Panel.fit(
            f"[green]✅ Configuration loaded successfully![/green]\n\n"
            f"  Environment:  {settings.environment}\n"
            f"  Model:        {settings.gemini_model}\n"
            f"  Embedding:    {settings.embedding_model}\n"
            f"  Qdrant:       {'In-Memory' if settings.qdrant_in_memory else f'{settings.qdrant_host}:{settings.qdrant_port}'}\n"
            f"  Collection:   {settings.qdrant_collection}\n"
            f"  Chunk Size:   {settings.rag_chunk_size} chars\n"
            f"  Retrieval K:  {settings.rag_retrieval_top_k} → Rerank K: {settings.rag_rerank_top_k}\n"
            f"  Log Level:    {settings.log_level}\n"
            f"  API Key:      {'✅ Set' if settings.google_api_key else '❌ Missing!'}",
            title="AgentOps Hub — Settings",
        ))
    except Exception as e:
        rprint(f"[red]❌ Configuration error: {e}[/red]")
        rprint("[yellow]Make sure you've copied .env.example to .env and filled in your values.[/yellow]")