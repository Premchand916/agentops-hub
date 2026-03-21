"""
AgentOps Hub — BM25 Sparse Retrieval Index
=============================================

WHAT THIS DOES:
Provides keyword-based search (BM25) to complement vector search.

WHY WE NEED BOTH (THE KEY INSIGHT):

Dense search (vectors) is great at understanding MEANING:
  Query: "I can't log in" → finds "authentication issues", "credential problems"

But dense search is BAD at exact matches:
  Query: "error code E-4012" → might miss the exact code because E-4012
  doesn't have strong semantic meaning in embedding space

BM25 (sparse search) is great at exact KEYWORD matches:
  Query: "error code E-4012" → finds every document containing "E-4012"

But BM25 is BAD at understanding meaning:
  Query: "I can't log in" → won't find "authentication issues" (different words!)

COMBINING THEM = HYBRID SEARCH:
  Dense catches: meaning, paraphrases, related concepts
  BM25 catches: exact codes, names, numbers, technical terms
  Together: best of both worlds

REAL-WORLD EXAMPLE:
A user asks: "How do I fix VPN error E-4012?"
  - Dense search finds: chunks about VPN troubleshooting (good!)
  - BM25 finds: the specific chunk with "E-4012" (also good!)
  - Combined: both the error code AND the general VPN help

This is why EVERY production RAG system uses hybrid search.
LinkedIn lists it as a top skill for AI Engineers in 2026.

INTERVIEW TIP:
Q: "What is BM25 and how does it work?"
A: "BM25 (Best Matching 25) is a probabilistic ranking function. It scores
   documents based on term frequency (TF) — how often the query terms
   appear in the document — and inverse document frequency (IDF) — how
   rare those terms are across all documents. A term that appears often
   in one doc but rarely elsewhere gets a high score. It also normalizes
   for document length so longer docs aren't unfairly penalized."

Q: "When would BM25 beat neural embeddings?"
A: "Three cases: (1) Exact match queries like error codes or ticket numbers,
   (2) When the knowledge base has domain-specific jargon the embedding model
   wasn't trained on, (3) When the query contains rare proper nouns. That's
   why hybrid search is standard — you get the best of both."
"""

import re
from rank_bm25 import BM25Okapi
from rag.chunker import Chunk
from rich import print as rprint


class BM25Index:
    """
    BM25 keyword-based search index.
    
    HOW BM25 WORKS (simplified):
    
    1. TOKENIZE: Split each document into words
       "How to reset VPN" → ["how", "to", "reset", "vpn"]
    
    2. BUILD INDEX: Count word frequencies across all documents
       "vpn" appears in 5 out of 100 documents → high IDF (rare = valuable)
       "the" appears in 95 out of 100 documents → low IDF (common = not useful)
    
    3. SEARCH: Score each document based on query term overlap
       Query: "reset vpn"
       Doc A has "reset" 3x and "vpn" 2x → high score
       Doc B has "vpn" 1x but no "reset" → lower score
    """
    
    def __init__(self):
        self.chunks: list[Chunk] = []
        self.index: BM25Okapi | None = None
        self.tokenized_corpus: list[list[str]] = []
    
    def build_index(self, chunks: list[Chunk]):
        """
        Build the BM25 index from chunks.
        
        This is called ONCE during ingestion, not during every search.
        Building is O(n) where n = total tokens across all documents.
        Searching is much faster.
        """
        self.chunks = chunks
        
        # Tokenize each chunk
        # WHY CUSTOM TOKENIZATION (not just .split())?
        # We lowercase and remove punctuation for better matching.
        # "VPN" should match "vpn". "E-4012" should match "e-4012".
        self.tokenized_corpus = [
            self._tokenize(chunk.content) for chunk in chunks
        ]
        
        # Build the BM25 index
        self.index = BM25Okapi(self.tokenized_corpus)
        
        rprint(f"[green]✅ BM25 index built: {len(chunks)} documents, "
               f"{sum(len(t) for t in self.tokenized_corpus)} total tokens[/green]")
    
    def search(self, query: str, top_k: int = 20) -> list[dict]:
        """
        Search the BM25 index.
        
        Args:
            query: Search query
            top_k: Number of results to return
            
        Returns:
            List of dicts with 'content', 'score', and metadata
        """
        if self.index is None:
            rprint("[red]❌ BM25 index not built. Call build_index() first.[/red]")
            return []
        
        # Tokenize the query the same way we tokenized documents
        query_tokens = self._tokenize(query)
        
        # Get BM25 scores for all documents
        scores = self.index.get_scores(query_tokens)
        
        # Get top_k results (sorted by score, highest first)
        # argsort returns indices that would sort the array
        # [::-1] reverses it (highest first), [:top_k] takes top results
        import numpy as np
        top_indices = np.argsort(scores)[::-1][:top_k]
        
        results = []
        for idx in top_indices:
            score = float(scores[idx])
            if score > 0:  # Only include documents with non-zero relevance
                chunk = self.chunks[idx]
                results.append({
                    "content": chunk.content,
                    "score": score,
                    "source": chunk.metadata.get("file_name", "unknown"),
                    "chunk_id": chunk.chunk_id,
                    "metadata": chunk.metadata,
                })
        
        return results
    
    def _tokenize(self, text: str) -> list[str]:
        """
        Simple tokenization: lowercase, split on non-alphanumeric.
        
        WHY THIS SPECIFIC APPROACH:
        - Lowercase: "VPN" matches "vpn"
        - Keep alphanumeric: preserves error codes like "E4012"
        - Remove short tokens: skip "a", "is", "to" (noise)
        
        In production, you might use a proper tokenizer (spaCy, NLTK)
        with stopword removal. But for 90% of cases, this works great.
        """
        # Lowercase and split on non-alphanumeric characters
        tokens = re.findall(r'\b\w+\b', text.lower())
        # Remove very short tokens (likely not meaningful)
        return [t for t in tokens if len(t) > 1]


# ============================================================
# Self-test
# ============================================================
if __name__ == "__main__":
    rprint("\n[bold]📝 Testing BM25 Index[/bold]\n")
    
    from rag.document_loader import load_directory
    from rag.chunker import RecursiveChunker
    
    docs = load_directory("rag/documents")
    chunker = RecursiveChunker()
    chunks = chunker.chunk_documents(docs)
    
    bm25 = BM25Index()
    bm25.build_index(chunks)
    
    # Test: exact match query (BM25 shines here)
    query = "error code E-4012"
    rprint(f"\n[bold]🔍 BM25 Search: '{query}'[/bold]\n")
    
    results = bm25.search(query, top_k=3)
    for i, result in enumerate(results, 1):
        rprint(f"  [yellow]Result {i}[/yellow] (score: {result['score']:.4f})")
        rprint(f"  Source: {result['source']}")
        rprint(f"  Content: {result['content'][:150]}...")
        rprint()
