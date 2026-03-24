"""End-to-end RAG pipeline for local document retrieval."""

import logging
import re
from pathlib import Path

import yaml
from langchain_ollama import ChatOllama
from rich import print as rprint

from config.settings import get_settings
from rag.bm25_index import BM25Index
from rag.chunker import RecursiveChunker
from rag.document_loader import load_directory
from rag.reranker import Reranker
from rag.retriever import HybridRetriever
from rag.vector_store import VectorStore

logging.getLogger("httpx").setLevel(logging.WARNING)


class RAGChain:
    """The complete RAG pipeline from documents to grounded answers."""

    def __init__(self):
        settings = get_settings()
        self.chunker = RecursiveChunker()
        self.vector_store = VectorStore()
        self.bm25_index = BM25Index()
        self.reranker = Reranker()
        self.retriever = HybridRetriever(self.vector_store, self.bm25_index)
        self.llm = ChatOllama(
            base_url=settings.ollama_base_url,
            model=settings.ollama_chat_model,
            temperature=0.0,
            timeout=settings.ollama_timeout_seconds,
            num_predict=max(settings.ollama_num_predict, 192),
            num_ctx=2048,
        )
        self.system_prompt = self._load_prompt("rag_qa")
        self._is_ingested = False

    def ingest(self, documents_path: str) -> dict:
        rprint(f"\n[bold cyan]{'=' * 60}[/bold cyan]")
        rprint("[bold cyan]   INGESTION PIPELINE[/bold cyan]")
        rprint(f"[bold cyan]{'=' * 60}[/bold cyan]\n")

        rprint("[bold]Step 1/4: Loading documents...[/bold]")
        documents = load_directory(documents_path)
        if not documents:
            rprint("[red] No documents found. Check the path.[/red]")
            return {"status": "error", "message": "No documents found"}

        rprint("\n[bold]Step 2/4: Chunking documents...[/bold]")
        chunks = self.chunker.chunk_documents(documents)

        rprint("\n[bold]Step 3/4: Embedding & storing in vector DB...[/bold]")
        vectors_stored = self.vector_store.add_chunks(chunks, replace_existing=True)

        rprint("\n[bold]Step 4/4: Building BM25 keyword index...[/bold]")
        self.bm25_index.build_index(chunks)

        self._is_ingested = True
        stats = {
            "status": "success",
            "documents_loaded": len(documents),
            "chunks_created": len(chunks),
            "vectors_stored": vectors_stored,
        }

        rprint(f"\n[bold green]{'=' * 60}[/bold green]")
        rprint("[bold green]   INGESTION COMPLETE[/bold green]")
        rprint(f"[bold green]   Documents: {stats['documents_loaded']}[/bold green]")
        rprint(f"[bold green]    Chunks: {stats['chunks_created']}[/bold green]")
        rprint(f"[bold green]   Vectors: {stats['vectors_stored']}[/bold green]")
        rprint(f"[bold green]{'=' * 60}[/bold green]\n")

        return stats

    def query(self, question: str, show_sources: bool = True) -> dict:
        if not self._is_ingested:
            return {
                "answer": "Knowledge base not loaded. Run ingest() first.",
                "sources": [],
            }

        rprint(f'\n[bold] Processing: "{question}"[/bold]\n')

        rprint("[dim]Step 1/3: Hybrid retrieval...[/dim]")
        retrieved = self.retriever.retrieve(question)

        rprint("[dim]Step 2/3: Reranking...[/dim]")
        reranked = self.reranker.rerank(question, retrieved)
        if not reranked:
            return {
                "answer": "I couldn't find any relevant information in the knowledge base.",
                "sources": [],
            }

        rprint("[dim]Step 3/3: Building grounded answer...[/dim]")
        answer = self._generate_answer(question, reranked)

        sources = []
        seen_files = set()
        for chunk in reranked:
            file_name = chunk.get("source", "unknown")
            if file_name in seen_files:
                continue
            seen_files.add(file_name)
            sources.append({
                "file": file_name,
                "chunk_id": chunk.get("chunk_id", ""),
                "rerank_score": chunk.get("rerank_score", 0),
            })

        if show_sources:
            rprint("\n[bold green] Answer:[/bold green]")
            rprint(answer)
            rprint("\n[bold yellow] Sources:[/bold yellow]")
            for source in sources:
                rprint(f"   {source['file']} (relevance: {source['rerank_score']:.3f})")

        return {
            "answer": answer,
            "sources": sources,
            "context_used": [chunk["content"][:100] + "..." for chunk in reranked],
            "chunks_retrieved": len(retrieved),
            "chunks_after_rerank": len(reranked),
        }

    def _generate_answer(self, question: str, chunks: list[dict]) -> str:
        """Generate an answer with Ollama, then fall back to extraction if needed."""
        context = self._build_context(chunks)
        prompt = (
            self.system_prompt
            .replace("{context}", context)
            .replace("{question}", question)
        )

        try:
            response = self.llm.invoke(prompt)
            answer = self._coerce_text(response.content).strip()
            if answer:
                return answer
        except Exception as exc:
            rprint(f"[yellow]   Ollama answer generation failed: {exc}[/yellow]")

        return self._compose_answer(question, chunks)

    def _build_context(self, chunks: list[dict], max_chars: int = 4000) -> str:
        """Trim retrieved chunks into a prompt-sized context window."""
        blocks = []
        total_chars = 0

        for chunk in chunks:
            block = (
                f"Source: {chunk.get('source', 'unknown')}\n"
                f"{chunk.get('content', '').strip()}"
            )
            block_size = len(block) + 6
            if blocks and total_chars + block_size > max_chars:
                break
            blocks.append(block)
            total_chars += block_size

        return "\n\n---\n\n".join(blocks)

    def _coerce_text(self, content) -> str:
        """Normalize LangChain/Ollama response payloads into plain text."""
        if isinstance(content, list):
            return " ".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content
            )
        return str(content)

    def _compose_answer(self, question: str, chunks: list[dict]) -> str:
        question_lower = question.lower()
        sources = self._unique_sources(chunks)

        if any(keyword in question_lower for keyword in ("how", "reset", "fix", "install", "configure", "steps")):
            items = self._extract_list_items(chunks)
            if items:
                lines = ["Here are the most relevant steps I found:"]
                for index, item in enumerate(items[:6], start=1):
                    lines.append(f"{index}. {item}")
                lines.append("")
                lines.append(f"Sources: {', '.join(sources[:3])}")
                return "\n".join(lines)

        facts = self._extract_fact_lines(chunks)
        if not facts:
            fallback = chunks[0]["content"].strip()
            facts = [fallback[:400].strip()]

        lines = ["Here is what I found:"]
        for fact in facts[:5]:
            lines.append(f"- {fact}")
        lines.append("")
        lines.append(f"Sources: {', '.join(sources[:3])}")
        return "\n".join(lines)

    def _extract_list_items(self, chunks: list[dict]) -> list[str]:
        items = []
        seen = set()
        pattern = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+(.*)$")

        for chunk in chunks:
            for line in chunk["content"].splitlines():
                match = pattern.match(line.strip())
                if not match:
                    continue
                item = self._clean_text(match.group(1))
                if len(item) < 8 or item in seen:
                    continue
                seen.add(item)
                items.append(item)

        return items

    def _extract_fact_lines(self, chunks: list[dict]) -> list[str]:
        facts = []
        seen = set()

        for chunk in chunks:
            text = chunk["content"]
            for raw_line in text.splitlines():
                line = self._clean_text(raw_line)
                if len(line) < 12:
                    continue
                if line.startswith("#") or line.startswith("["):
                    continue
                if line in seen:
                    continue
                seen.add(line)
                facts.append(line)
                if len(facts) >= 8:
                    return facts

            for sentence in re.split(r"(?<=[.!?])\s+", text):
                cleaned = self._clean_text(sentence)
                if len(cleaned) < 20 or cleaned in seen:
                    continue
                seen.add(cleaned)
                facts.append(cleaned)
                if len(facts) >= 8:
                    return facts

        return facts

    def _unique_sources(self, chunks: list[dict]) -> list[str]:
        sources = []
        for chunk in chunks:
            source = chunk.get("source", "unknown")
            if source not in sources:
                sources.append(source)
        return sources

    def _clean_text(self, text: str) -> str:
        cleaned = text.strip().strip("-*")
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned

    def _load_prompt(self, prompt_name: str) -> str:
        prompts_path = Path("config/prompts/system_prompts.yaml")
        if not prompts_path.exists():
            return "Answer the question based on the context below."

        with open(prompts_path, "r", encoding="utf-8") as file:
            prompts = yaml.safe_load(file)

        prompt_config = prompts.get(prompt_name, {})
        return prompt_config.get("system_prompt", "Answer the question based on the provided context.")


if __name__ == "__main__":
    rprint("\n[bold] Testing Complete RAG Chain[/bold]\n")
    rag = RAGChain()
    rag.ingest("rag/documents")
    for question in [
        "How do I fix VPN error E-4012?",
        "What is the PTO policy?",
        "How do I install Docker on my work laptop?",
    ]:
        rag.query(question)
        rprint("\n" + "-" * 60 + "\n")

