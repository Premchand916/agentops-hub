"""
AgentOps Hub - Ollama model factory.

The app now runs fully local:
- chat models come from the local Ollama server
- embeddings come from the local Ollama server
"""

from langchain_ollama import ChatOllama, OllamaEmbeddings

from config.settings import get_settings


def get_llm(temperature: float = 0.0, **kwargs) -> ChatOllama:
    """Return the configured local Ollama chat model."""
    settings = get_settings()
    _require_setting(settings.ollama_chat_model, "OLLAMA_CHAT_MODEL")

    return ChatOllama(
        base_url=settings.ollama_base_url,
        model=settings.ollama_chat_model,
        temperature=temperature,
        timeout=settings.ollama_timeout_seconds,
        num_predict=settings.ollama_num_predict,
        **kwargs,
    )


def get_embeddings() -> OllamaEmbeddings:
    """Return the configured local Ollama embedding model."""
    settings = get_settings()
    _require_setting(settings.ollama_embedding_model, "OLLAMA_EMBEDDING_MODEL")

    return OllamaEmbeddings(
        base_url=settings.ollama_base_url,
        model=settings.ollama_embedding_model,
    )


def _require_setting(value: str, env_var: str) -> None:
    """Raise a clear error if a required Ollama setting is blank."""
    if not value or not value.strip():
        raise ValueError(f"Missing required setting: {env_var}")
