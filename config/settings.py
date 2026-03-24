"""
AgentOps Hub - Centralized configuration for a fully local Ollama setup.

All LLM traffic stays on the local machine. The app uses:
- Ollama for chat generation
- Ollama for embeddings
- Qdrant for vector storage
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for the entire AgentOps Hub."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # =====================
    # Ollama
    # =====================
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        description="Base URL for the local Ollama server.",
    )
    ollama_chat_model: str = Field(
        default="llama3.2:3b",
        description="Ollama chat model used by the agents.",
    )
    ollama_embedding_model: str = Field(
        default="nomic-embed-text",
        description="Ollama embedding model used by the RAG pipeline.",
    )
    ollama_timeout_seconds: int = Field(
        default=120,
        description="Timeout for Ollama chat requests in seconds.",
    )
    ollama_num_predict: int = Field(
        default=96,
        description="Maximum number of tokens to generate per Ollama response.",
    )

    # =====================
    # Vector Database
    # =====================
    qdrant_host: str = Field(
        default="localhost",
        description="Qdrant server host",
    )
    qdrant_port: int = Field(
        default=6333,
        description="Qdrant server port",
    )
    qdrant_in_memory: bool = Field(
        default=True,
        description="Use in-memory Qdrant for local development.",
    )
    qdrant_collection: str = Field(
        default="agentops_knowledge",
        description="Name of the vector collection",
    )

    # =====================
    # RAG Configuration
    # =====================
    rag_retrieval_top_k: int = Field(
        default=20,
        description="Number of chunks to retrieve before reranking",
    )
    rag_rerank_top_k: int = Field(
        default=5,
        description="Number of chunks to keep after reranking",
    )
    rag_chunk_size: int = Field(
        default=1000,
        description="Document chunk size in characters",
    )
    rag_chunk_overlap: int = Field(
        default=200,
        description="Overlap between consecutive chunks",
    )

    # =====================
    # Application
    # =====================
    log_level: str = Field(
        default="INFO",
        description="Logging level: DEBUG, INFO, WARNING, ERROR",
    )
    environment: str = Field(
        default="development",
        description="Runtime environment: development, staging, production",
    )


def get_settings() -> Settings:
    """Get the application settings."""
    return Settings()


if __name__ == "__main__":
    from rich import print as rprint
    from rich.panel import Panel

    try:
        settings = get_settings()
        rprint(Panel.fit(
            f"[green]Configuration loaded successfully![/green]\n\n"
            f"  Environment:       {settings.environment}\n"
            f"  Ollama URL:        {settings.ollama_base_url}\n"
            f"  Chat Model:        {settings.ollama_chat_model}\n"
            f"  Embedding Model:   {settings.ollama_embedding_model}\n"
            f"  Timeout:           {settings.ollama_timeout_seconds}s\n"
            f"  Max Tokens:        {settings.ollama_num_predict}\n"
            f"  Qdrant:            {'In-Memory' if settings.qdrant_in_memory else f'{settings.qdrant_host}:{settings.qdrant_port}'}\n"
            f"  Collection:        {settings.qdrant_collection}\n"
            f"  Chunk Size:        {settings.rag_chunk_size} chars\n"
            f"  Retrieval K:       {settings.rag_retrieval_top_k} -> Rerank K: {settings.rag_rerank_top_k}\n"
            f"  Log Level:         {settings.log_level}",
            title="AgentOps Hub - Settings",
        ))
    except Exception as e:
        rprint(f"[red]Configuration error: {e}[/red]")
        rprint("[yellow]Make sure your .env file contains the Ollama settings.[/yellow]")



