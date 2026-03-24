"""
AgentOps Hub  Reranker
=========================

WHAT THIS DOES:
Takes the top-k retrieved chunks (from hybrid search) and RE-SCORES them
using a more accurate (but slower) model to find the truly best matches.

WHY RERANKING IS NECESSARY:

Think of it like a job hiring process:
1. RETRIEVAL (resume screening)  Quick scan, pull 20 candidates  fast but rough
2. RERANKING (phone interview)   Carefully evaluate top 20, pick best 5  slower but accurate

Without reranking: The LLM gets 20 chunks, many of which are mediocre.
With reranking:    The LLM gets the 5 BEST chunks. Much better answers.

HOW RERANKING DIFFERS FROM RETRIEVAL:

Retrieval (bi-encoder): 
  - Embeds query and documents SEPARATELY
  - Fast: can search millions of documents in milliseconds
  - Less accurate: because query and document never "see" each other

Reranking (cross-encoder):
  - Takes query AND document TOGETHER as input
  - Slow: processes each candidate individually
  - More accurate: because it can see the relationship between query and document

That's why we use retrieval first (fast, broad) then reranking (slow, precise).
You can't rerank millions of documents  too slow. But reranking 20? Easy.

WHY FLASHRANK (not Cohere Rerank or sentence-transformers)?
- FlashRank: No PyTorch needed (~2GB saved), runs on CPU, free, good quality
- Cohere Rerank: Best quality, but requires API key + costs money
- sentence-transformers cross-encoder: Great quality, but needs PyTorch installed
For development and learning, FlashRank is perfect. In production, you'd likely
switch to Cohere Rerank for better quality.

INTERVIEW TIP:
Q: "Why not just use the reranker for everything instead of vector search?"
A: "Rerankers are cross-encoders  they process query-document pairs together.
   For 1 million documents, that's 1 million forward passes through a neural
   network. That would take minutes or hours. Vector search takes milliseconds
   because it pre-computes document embeddings. So we use vector search to
   narrow down to 20 candidates, then reranking to pick the best 5."
"""

from flashrank import Ranker, RerankRequest
from config.settings import get_settings
from rich import print as rprint


class Reranker:
    """
    Reranks retrieved chunks using FlashRank cross-encoder.
    
    USAGE:
        reranker = Reranker()
        reranked = reranker.rerank(query, retrieved_chunks)
        # reranked is sorted by relevance  best first
    """
    
    def __init__(self, model_name: str = "ms-marco-MiniLM-L-12-v2"):
        """
        Initialize the reranker.
        
        MODEL CHOICE: ms-marco-MiniLM-L-12-v2
        - Trained on MS MARCO (a large retrieval benchmark)
        - 12 layers, good balance of speed and quality
        - ~50MB model size (downloads automatically on first use)
        
        The first call will download the model. Subsequent calls use cache.
        """
        rprint(f"[dim] Loading reranker model: {model_name}[/dim]")
        self.ranker = Ranker(model_name=model_name, cache_dir="model_cache")
        self.settings = get_settings()
    
    def rerank(
        self,
        query: str,
        results: list[dict],
        top_k: int | None = None,
    ) -> list[dict]:
        """
        Rerank retrieved results for better precision.
        
        Args:
            query: The original search question
            results: List of dicts from the retriever (must have 'content' key)
            top_k: Number of results to keep after reranking (from settings if not specified)
            
        Returns:
            Reranked list of dicts, sorted by rerank score (best first)
            Only top_k results are returned.
        """
        top_k = top_k or self.settings.rag_rerank_top_k
        
        if not results:
            return []
        
        # Prepare data for FlashRank
        # FlashRank expects a list of dicts with "id" and "text" keys
        passages = []
        for i, result in enumerate(results):
            passages.append({
                "id": i,
                "text": result["content"],
            })
        
        # Create rerank request
        rerank_request = RerankRequest(
            query=query,
            passages=passages,
        )
        
        # Rerank
        reranked = self.ranker.rerank(rerank_request)
        
        # Map back to our result format and add rerank scores
        reranked_results = []
        for item in reranked[:top_k]:
            original_idx = item["id"]
            original_result = results[original_idx].copy()
            original_result["rerank_score"] = item["score"]
            reranked_results.append(original_result)
        
        rprint(f"[dim]   Reranked {len(results)}  kept top {len(reranked_results)}[/dim]")
        
        return reranked_results


# ============================================================
# Self-test
# ============================================================
if __name__ == "__main__":
    rprint("\n[bold] Testing Reranker[/bold]\n")
    
    reranker = Reranker()
    
    # Simulate retrieved results
    query = "How do I reset my VPN connection?"
    fake_results = [
        {"content": "To reset VPN, go to Settings > Advanced > Clear Cache", "source": "runbook"},
        {"content": "The company picnic is scheduled for next Friday", "source": "announcements"},
        {"content": "VPN error E-4012 means connection timed out. Restart the client.", "source": "runbook"},
        {"content": "Our office is located at 123 Main Street", "source": "about"},
    ]
    
    reranked = reranker.rerank(query, fake_results, top_k=2)
    
    rprint(f"\nQuery: '{query}'\n")
    for i, r in enumerate(reranked, 1):
        rprint(f"  [yellow]#{i}[/yellow] (score: {r['rerank_score']:.4f})")
        rprint(f"  Content: {r['content']}")
        rprint()

