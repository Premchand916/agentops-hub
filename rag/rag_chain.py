"""
AgentOps Hub — RAG Chain (The Complete Pipeline)
===================================================

WHAT THIS DOES:
Ties together EVERY component into one clean interface:
  Load → Chunk → Embed → Store → Retrieve → Rerank → Generate

This is the "main brain" of our Knowledge Agent. When a user asks
a question, this class handles the entire flow from question to answer.

DESIGN PATTERN — FACADE:
Instead of the CLI or agent dealing with 6 different classes,
they interact with ONE RAGChain class. This is the Facade pattern.

REAL-WORLD ANALOGY:
When you go to a hospital, you talk to the reception desk.
They handle everything behind the scenes — booking, records, scheduling.
You don't walk into the X-ray room yourself.
The RAGChain is the reception desk for knowledge retrieval.

INTERVIEW TIP:
Q: "Walk me through how a RAG system answers a question."
A: "The query first goes through hybrid retrieval — dense vector search
   for semantic similarity and BM25 for keyword matching. Results are
   fused using Reciprocal Rank Fusion. The combined candidates go through
   a cross-encoder reranker to pick the most relevant chunks. These chunks
   become the 'context' injected into the LLM's prompt. The LLM generates
   an answer grounded ONLY in that context, with source citations. The whole
   flow is: embed query → hybrid search → RRF → rerank → generate."
"""

import yaml
import logging
from pathlib import Path
from langchain_google_genai import ChatGoogleGenerativeAI
from config.settings import get_settings
from rag.document_loader import load_directory
from rag.chunker import RecursiveChunker, Chunk
from rag.vector_store import VectorStore
from rag.bm25_index import BM25Index
from rag.retriever import HybridRetriever
from rag.reranker import Reranker
from rich import print as rprint
# Suppress noisy HTTP request logs
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("google_genai.models").setLevel(logging.WARNING)

class RAGChain:
    """
    The complete RAG pipeline — from documents to answers.
    
    Usage:
        rag = RAGChain()
        rag.ingest("rag/documents")    # One-time: load & index documents
        answer = rag.query("How do I reset my VPN?")  # Ask questions
    """
    
    def __init__(self):
        """Initialize all RAG components."""
        self.settings = get_settings()
        
        # --- Components ---
        self.chunker = RecursiveChunker()
        self.vector_store = VectorStore()
        self.bm25_index = BM25Index()
        self.reranker = Reranker()
        
        # Hybrid retriever (combines vector + BM25)
        self.retriever = HybridRetriever(self.vector_store, self.bm25_index)
        
        # --- LLM for answer generation ---
        self.llm = ChatGoogleGenerativeAI(
            model=self.settings.gemini_model,
            google_api_key=self.settings.google_api_key,
            temperature=0.1,  # Low temperature = more factual, less creative
            # WHY 0.1 AND NOT 0?
            # Temperature 0 is "greedy decoding" — always picks the most likely token.
            # 0.1 allows tiny variation, which sometimes produces more natural language
            # while still being very factual. For RAG, you want factual answers.
        )
        
        # --- Load system prompt ---
        self.system_prompt = self._load_prompt("rag_qa")
        
        # Track state
        self._is_ingested = False
    
    def ingest(self, documents_path: str) -> dict:
        """
        Load, chunk, embed, and index all documents.
        
        This is the "setup" step. Run it once (or whenever docs change).
        
        Args:
            documents_path: Path to directory containing documents
            
        Returns:
            Dict with stats about what was ingested
        """
        rprint(f"\n[bold cyan]{'='*60}[/bold cyan]")
        rprint(f"[bold cyan]  📥 INGESTION PIPELINE[/bold cyan]")
        rprint(f"[bold cyan]{'='*60}[/bold cyan]\n")
        
        # Step 1: Load documents
        rprint("[bold]Step 1/4: Loading documents...[/bold]")
        documents = load_directory(documents_path)
        if not documents:
            rprint("[red]❌ No documents found. Check the path.[/red]")
            return {"status": "error", "message": "No documents found"}
        
        # Step 2: Chunk documents
        rprint(f"\n[bold]Step 2/4: Chunking documents...[/bold]")
        chunks = self.chunker.chunk_documents(documents)
        
        # Step 3: Store in vector database (embeds automatically)
        rprint(f"\n[bold]Step 3/4: Embedding & storing in vector DB...[/bold]")
        vectors_stored = self.vector_store.add_chunks(chunks)
        
        # Step 4: Build BM25 index
        rprint(f"\n[bold]Step 4/4: Building BM25 keyword index...[/bold]")
        self.bm25_index.build_index(chunks)
        
        self._is_ingested = True
        
        stats = {
            "status": "success",
            "documents_loaded": len(documents),
            "chunks_created": len(chunks),
            "vectors_stored": vectors_stored,
        }
        
        rprint(f"\n[bold green]{'='*60}[/bold green]")
        rprint(f"[bold green]  ✅ INGESTION COMPLETE[/bold green]")
        rprint(f"[bold green]  📄 Documents: {stats['documents_loaded']}[/bold green]")
        rprint(f"[bold green]  ✂️  Chunks: {stats['chunks_created']}[/bold green]")
        rprint(f"[bold green]  🔢 Vectors: {stats['vectors_stored']}[/bold green]")
        rprint(f"[bold green]{'='*60}[/bold green]\n")
        
        return stats
    
    def query(self, question: str, show_sources: bool = True) -> dict:
        """
        Ask a question and get a RAG-grounded answer.
        
        THE COMPLETE FLOW:
        1. Hybrid retrieve (vector + BM25 + RRF)
        2. Rerank (cross-encoder)
        3. Build prompt (context + question)
        4. Generate answer (Gemini)
        5. Return answer + sources
        
        Args:
            question: The user's question
            show_sources: Whether to print source information
            
        Returns:
            Dict with 'answer', 'sources', and 'context_used'
        """
        if not self._is_ingested:
            return {
                "answer": "Knowledge base not loaded. Run ingest() first.",
                "sources": [],
            }
        
        rprint(f"\n[bold]🔍 Processing: \"{question}\"[/bold]\n")
        
        # Step 1: Hybrid retrieval
        rprint("[dim]Step 1/3: Hybrid retrieval...[/dim]")
        retrieved = self.retriever.retrieve(question)
        
        # Step 2: Reranking
        rprint("[dim]Step 2/3: Reranking...[/dim]")
        reranked = self.reranker.rerank(question, retrieved)
        
        if not reranked:
            return {
                "answer": "I couldn't find any relevant information in the knowledge base.",
                "sources": [],
            }
        
        # Step 3: Build context from top chunks
        context = self._build_context(reranked)
        
        # Step 4: Generate answer using LLM
        rprint("[dim]Step 3/3: Generating answer...[/dim]")
        prompt = self.system_prompt.format(
            context=context,
            question=question,
        )
        
        response = self.llm.invoke(prompt)
        response = self.llm.invoke(prompt)
        # Handle both string and list response formats from Gemini
        if isinstance(response.content, list):
            # Gemini sometimes returns list of content blocks
            answer = "\n".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in response.content
            )
        else:
            answer = response.content
        
        # Collect sources for citation
        sources = []
        for chunk in reranked:
            source_info = {
                "file": chunk.get("source", "unknown"),
                "chunk_id": chunk.get("chunk_id", ""),
                "rerank_score": chunk.get("rerank_score", 0),
            }
            if source_info not in sources:
                sources.append(source_info)
        
        # Display results
        if show_sources:
            rprint(f"\n[bold green]💬 Answer:[/bold green]")
            rprint(f"{answer}")
            rprint(f"\n[bold yellow]📚 Sources:[/bold yellow]")
            for s in sources:
                rprint(f"  • {s['file']} (relevance: {s['rerank_score']:.3f})")
        
        return {
            "answer": answer,
            "sources": sources,
            "context_used": [r["content"][:100] + "..." for r in reranked],
            "chunks_retrieved": len(retrieved),
            "chunks_after_rerank": len(reranked),
        }
    
    def _build_context(self, chunks: list[dict]) -> str:
        """
        Build the context string from reranked chunks.
        
        FORMAT MATTERS:
        We clearly separate each chunk with source attribution.
        This helps the LLM cite sources in its answer.
        
        WHY NUMBERED SOURCES?
        So the LLM can say "According to Source 1..." which makes
        answers more trustworthy and verifiable.
        """
        context_parts = []
        for i, chunk in enumerate(chunks, start=1):
            source = chunk.get("source", "unknown")
            content = chunk["content"]
            context_parts.append(
                f"[Source {i}: {source}]\n{content}"
            )
        
        return "\n\n---\n\n".join(context_parts)
    
    def _load_prompt(self, prompt_name: str) -> str:
        """
        Load a system prompt from the YAML config file.
        
        WHY FROM YAML:
        Remember — prompts are config, not code. We load them at runtime
        so they can be changed without modifying Python files.
        """
        prompts_path = Path("config/prompts/system_prompts.yaml")
        
        if not prompts_path.exists():
            # Fallback prompt if YAML not found
            return (
                "Answer the question based on the context below.\n\n"
                "Context:\n{context}\n\n"
                "Question: {question}"
            )
        
        with open(prompts_path, "r") as f:
            prompts = yaml.safe_load(f)
        
        prompt_config = prompts.get(prompt_name, {})
        return prompt_config.get("system_prompt", "Answer: {context}\n\nQ: {question}")


# ============================================================
# Self-test
# ============================================================
if __name__ == "__main__":
    rprint("\n[bold]🧠 Testing Complete RAG Chain[/bold]\n")
    
    rag = RAGChain()
    rag.ingest("rag/documents")
    
    # Test with different types of questions
    questions = [
        "How do I fix VPN error E-4012?",
        "What is the PTO policy?",
        "How do I install Docker on my work laptop?",
    ]
    
    for q in questions:
        result = rag.query(q)
        rprint(f"\n{'─'*60}\n")
