"""
AgentOps Hub — Hybrid Retriever
==================================

WHAT THIS DOES:
Combines results from BOTH vector search (dense) and BM25 (sparse)
into a single, better-ranked list using Reciprocal Rank Fusion (RRF).

WHY NOT JUST PICK THE BEST ONE?

Think of it like a doctor getting a SECOND OPINION:
- Doctor A (vector search) says: "These 5 medical records are relevant"
- Doctor B (BM25) says: "These 5 medical records are relevant"
- Some records appear in BOTH lists → very likely relevant (boost them!)
- Some appear in only one → might be relevant (keep them, lower rank)

This is EXACTLY what Reciprocal Rank Fusion does.

HOW RRF WORKS:

For each result, calculate: score = 1 / (rank + k)
where k = 60 (constant to prevent rank 1 from dominating)

Example:
  Vector search returns: [Doc A (rank 1), Doc B (rank 2), Doc C (rank 3)]
  BM25 returns:          [Doc B (rank 1), Doc D (rank 2), Doc A (rank 3)]

  RRF scores:
  Doc A: 1/(1+60) + 1/(3+60) = 0.0164 + 0.0159 = 0.0323  ← appears in BOTH!
  Doc B: 1/(2+60) + 1/(1+60) = 0.0161 + 0.0164 = 0.0325  ← appears in BOTH!
  Doc C: 1/(3+60) + 0          = 0.0159                     ← only in vector
  Doc D: 0          + 1/(2+60) = 0.0161                     ← only in BM25

  Final ranking: [Doc B, Doc A, Doc D, Doc C]
  → Documents appearing in BOTH lists naturally rise to the top!

INTERVIEW TIP:
Q: "How do you combine results from different retrieval methods?"
A: "I use Reciprocal Rank Fusion (RRF). It's a simple, effective method
   that doesn't require training or tuning. Each retriever contributes
   a score based on 1/(rank + k), and we sum scores for documents that
   appear in multiple result sets. Documents found by BOTH retrievers
   naturally get higher combined scores. The constant k=60 is the
   standard value that prevents rank 1 from having outsized influence."
"""

from rag.vector_store import VectorStore
from rag.bm25_index import BM25Index
from config.settings import get_settings
from rich import print as rprint


class HybridRetriever:
    """
    Combines dense (vector) and sparse (BM25) retrieval
    using Reciprocal Rank Fusion.
    """
    
    def __init__(self, vector_store: VectorStore, bm25_index: BM25Index):
        """
        Initialize with both retrieval systems.
        
        Both should already be populated with the same documents.
        """
        self.vector_store = vector_store
        self.bm25_index = bm25_index
        self.settings = get_settings()
    
    def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        rrf_k: int = 60,
    ) -> list[dict]:
        """
        Retrieve relevant chunks using hybrid search.
        
        Args:
            query: The search question
            top_k: Number of results to return (from settings if not specified)
            rrf_k: RRF constant (60 is the standard value from the original paper)
            
        Returns:
            List of dicts with 'content', 'rrf_score', 'source', etc.
            Sorted by RRF score (highest first)
        """
        top_k = top_k or self.settings.rag_retrieval_top_k
        
        # --- Step 1: Get results from BOTH retrievers ---
        # We fetch more than top_k from each because RRF works better
        # with a larger candidate pool
        fetch_k = min(top_k * 2, 50)  # Fetch up to 2x what we need
        
        rprint(f"[dim]  🔍 Dense search (top {fetch_k})...[/dim]")
        dense_results = self.vector_store.search(query, top_k=fetch_k)
        
        rprint(f"[dim]  📝 BM25 search (top {fetch_k})...[/dim]")
        sparse_results = self.bm25_index.search(query, top_k=fetch_k)
        
        # --- Step 2: Apply Reciprocal Rank Fusion ---
        fused_results = self._reciprocal_rank_fusion(
            dense_results, sparse_results, k=rrf_k
        )
        
        # --- Step 3: Return top_k results ---
        final = fused_results[:top_k]
        
        rprint(f"[dim]  🔀 Hybrid results: {len(final)} chunks "
               f"(from {len(dense_results)} dense + {len(sparse_results)} sparse)[/dim]")
        
        return final
    
    def _reciprocal_rank_fusion(
        self,
        dense_results: list[dict],
        sparse_results: list[dict],
        k: int = 60,
    ) -> list[dict]:
        """
        Merge two ranked lists using RRF.
        
        ALGORITHM:
        1. For each result in dense list: rrf_score += 1/(rank + k)
        2. For each result in sparse list: rrf_score += 1/(rank + k)
        3. Sort by combined rrf_score
        
        We use chunk_id as the key to identify the same chunk across lists.
        """
        # Dictionary to accumulate scores: chunk_id → {data + score}
        score_map: dict[str, dict] = {}
        
        # Process dense (vector) results
        for rank, result in enumerate(dense_results, start=1):
            chunk_id = result["chunk_id"]
            rrf_score = 1.0 / (rank + k)
            
            if chunk_id in score_map:
                score_map[chunk_id]["rrf_score"] += rrf_score
                score_map[chunk_id]["found_in"].append("dense")
            else:
                score_map[chunk_id] = {
                    "content": result["content"],
                    "source": result["source"],
                    "chunk_id": chunk_id,
                    "metadata": result["metadata"],
                    "rrf_score": rrf_score,
                    "dense_score": result.get("score", 0),
                    "found_in": ["dense"],
                }
        
        # Process sparse (BM25) results
        for rank, result in enumerate(sparse_results, start=1):
            chunk_id = result["chunk_id"]
            rrf_score = 1.0 / (rank + k)
            
            if chunk_id in score_map:
                score_map[chunk_id]["rrf_score"] += rrf_score
                score_map[chunk_id]["found_in"].append("sparse")
                score_map[chunk_id]["bm25_score"] = result.get("score", 0)
            else:
                score_map[chunk_id] = {
                    "content": result["content"],
                    "source": result["source"],
                    "chunk_id": chunk_id,
                    "metadata": result["metadata"],
                    "rrf_score": rrf_score,
                    "bm25_score": result.get("score", 0),
                    "found_in": ["sparse"],
                }
        
        # Sort by RRF score (highest first)
        sorted_results = sorted(
            score_map.values(),
            key=lambda x: x["rrf_score"],
            reverse=True,
        )
        
        return sorted_results


# ============================================================
# Self-test
# ============================================================
if __name__ == "__main__":
    rprint("\n[bold]🔀 Testing Hybrid Retriever[/bold]\n")
    
    from rag.document_loader import load_directory
    from rag.chunker import RecursiveChunker
    
    docs = load_directory("rag/documents")
    chunker = RecursiveChunker()
    chunks = chunker.chunk_documents(docs)
    
    # Build both indexes
    vs = VectorStore()
    vs.add_chunks(chunks)
    
    bm25 = BM25Index()
    bm25.build_index(chunks)
    
    # Hybrid search
    retriever = HybridRetriever(vs, bm25)
    query = "VPN error E-4012 connection timed out"
    
    rprint(f"\n[bold]🔍 Hybrid search: '{query}'[/bold]\n")
    results = retriever.retrieve(query, top_k=5)
    
    for i, r in enumerate(results, 1):
        found_in = " + ".join(r["found_in"])
        rprint(f"  [yellow]#{i}[/yellow] (RRF: {r['rrf_score']:.4f}) [{found_in}]")
        rprint(f"  Source: {r['source']}")
        rprint(f"  Content: {r['content'][:120]}...")
        rprint()
