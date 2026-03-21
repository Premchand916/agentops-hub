"""
AgentOps Hub — Vector Store (Qdrant + Google Embeddings)
=========================================================

WHAT THIS DOES:
1. Takes chunks of text
2. Converts them into "embeddings" (lists of numbers that capture meaning)
3. Stores them in Qdrant (a vector database)
4. Searches for similar chunks when a question is asked

WHAT ARE EMBEDDINGS? (Important concept)

An embedding is a list of numbers (like [0.23, -0.41, 0.87, ...]) that
represents the MEANING of text, not the exact words.

Example:
  "How do I reset my password?"     → [0.23, -0.41, 0.87, ...]
  "I forgot my login credentials"   → [0.21, -0.39, 0.85, ...]  ← very similar!
  "What's the weather in Tokyo?"    → [-0.71, 0.52, -0.13, ...]  ← very different!

The first two are SEMANTICALLY similar (same meaning, different words),
so their embeddings are close together in vector space.

This is why vector search is more powerful than keyword search:
  Keyword search for "reset password" → only finds docs with those exact words
  Vector search for "reset password" → also finds "forgot credentials", "login help"

WHY QDRANT?
1. Runs locally in-memory (no server setup needed for development)
2. Open-source and free
3. Supports hybrid search (dense + sparse vectors) natively
4. Excellent Python SDK
5. Scales to production (used by major companies)

INTERVIEW TIP:
Q: "Explain how vector similarity search works."
A: "Documents are converted to high-dimensional vectors using an embedding model.
   Similar documents have vectors that point in similar directions. We use cosine
   similarity to find the closest vectors to a query. Qdrant uses HNSW (Hierarchical
   Navigable Small World) index for approximate nearest neighbor search, which gives
   us sub-millisecond search on millions of vectors."

Q: "Why not just use PostgreSQL with pgvector?"
A: "For a small knowledge base, pgvector works fine. But Qdrant gives us
   native hybrid search, payload filtering, and better performance at scale.
   For this project, Qdrant's in-memory mode means zero setup — same as pgvector
   in terms of convenience, but with more features."
"""

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
)
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from config.settings import get_settings
from rag.chunker import Chunk
from rich import print as rprint
import uuid


class VectorStore:
    """
    Manages embedding generation and vector storage in Qdrant.
    
    ARCHITECTURE NOTE:
    This class combines two responsibilities:
    1. Embedding generation (text → vectors)
    2. Vector storage (vectors → Qdrant)
    
    In a larger system, you might separate these. For our project,
    keeping them together makes the code clearer and easier to follow.
    """
    
    def __init__(self):
        """
        Initialize the vector store and embedding model.
        
        WHAT HAPPENS HERE:
        1. Load settings (model name, Qdrant config)
        2. Create the embedding model (Google's text-embedding-004)
        3. Connect to Qdrant (in-memory for development)
        4. Create the collection if it doesn't exist
        """
        self.settings = get_settings()
        
        # --- Initialize embedding model ---
        # Google's text-embedding-004 produces 768-dimensional vectors
        # This means each chunk becomes a list of 768 numbers
        self.embeddings = GoogleGenerativeAIEmbeddings(
            model=self.settings.embedding_model,
            google_api_key=self.settings.google_api_key,
        )
        
        # --- Connect to Qdrant ---
        if self.settings.qdrant_in_memory:
            # In-memory: data lives in RAM, disappears when program exits
            # PERFECT for development: no server to install or manage
            self.client = QdrantClient(":memory:")
            rprint("[dim]📦 Qdrant: in-memory mode (data resets on restart)[/dim]")
        else:
            # Production: connect to a real Qdrant server
            self.client = QdrantClient(
                host=self.settings.qdrant_host,
                port=self.settings.qdrant_port,
            )
        
        self.collection_name = self.settings.qdrant_collection
        
        # We'll set this after we know the embedding dimension
        self._collection_created = False
    
    def _ensure_collection(self, vector_size: int):
        """
        Create the Qdrant collection if it doesn't exist.
        
        A "collection" in Qdrant is like a "table" in a database.
        It stores vectors of a specific dimension with a specific distance metric.
        
        DISTANCE METRIC: We use COSINE similarity.
        WHY COSINE? Because embedding models are trained with cosine similarity.
        Using a different metric (like Euclidean) would give worse results.
        
        Think of it this way:
        - Cosine measures the ANGLE between vectors (direction = meaning)
        - Euclidean measures the DISTANCE between vectors (magnitude matters)
        - For text, direction matters more than magnitude → use cosine
        """
        if self._collection_created:
            return
        
        # Check if collection already exists
        collections = self.client.get_collections().collections
        exists = any(c.name == self.collection_name for c in collections)
        
        if not exists:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=vector_size,
                    distance=Distance.COSINE,
                ),
            )
            rprint(f"[green]✅ Created collection: {self.collection_name} "
                   f"(dim={vector_size}, metric=cosine)[/green]")
        
        self._collection_created = True
    
    def add_chunks(self, chunks: list[Chunk]) -> int:
        """
        Embed chunks and store them in Qdrant.
        
        FLOW:
        1. Extract text from chunks
        2. Send text to Google's embedding API → get vectors back
        3. Store vectors + metadata in Qdrant
        
        WHY BATCH EMBEDDING?
        Instead of embedding one chunk at a time (slow, many API calls),
        we embed ALL chunks in one batch (fast, one API call).
        Google allows up to 100 texts per batch.
        
        Returns:
            Number of chunks stored
        """
        if not chunks:
            rprint("[yellow]⚠️  No chunks to store[/yellow]")
            return 0
        
        rprint(f"[cyan]🔢 Generating embeddings for {len(chunks)} chunks...[/cyan]")
        
        # Extract texts for embedding
        texts = [chunk.content for chunk in chunks]
        
        # Generate embeddings in batch
        # This calls Google's API: texts → vectors
        vectors = self.embeddings.embed_documents(texts)
        
        # Ensure collection exists with correct dimensions
        vector_size = len(vectors[0])
        self._ensure_collection(vector_size)
        
        # Prepare points for Qdrant
        points = []
        for i, (chunk, vector) in enumerate(zip(chunks, vectors)):
            point = PointStruct(
                id=str(uuid.uuid4()),  # Unique ID for each point
                vector=vector,
                payload={
                    # Store the text and metadata WITH the vector
                    # This way, when we search, we get back the text directly
                    "content": chunk.content,
                    "chunk_id": chunk.chunk_id,
                    "chunk_index": chunk.chunk_index,
                    **chunk.metadata,
                }
            )
            points.append(point)
        
        # Upload to Qdrant in batches of 100
        batch_size = 100
        for i in range(0, len(points), batch_size):
            batch = points[i:i + batch_size]
            self.client.upsert(
                collection_name=self.collection_name,
                points=batch,
            )
        
        rprint(f"[green]✅ Stored {len(points)} vectors in Qdrant[/green]")
        return len(points)
    
    def search(self, query: str, top_k: int | None = None) -> list[dict]:
        """
        Search for chunks similar to the query.
        
        FLOW:
        1. Embed the query (same model used for documents)
        2. Find the top_k most similar vectors in Qdrant
        3. Return the chunks with their similarity scores
        
        WHY SAME EMBEDDING MODEL?
        The query and documents MUST use the same embedding model.
        Different models produce different vector spaces — comparing
        vectors from different models is like comparing temperatures
        in Fahrenheit and Celsius without converting.
        
        Args:
            query: The search question
            top_k: Number of results to return
            
        Returns:
            List of dicts with 'content', 'score', and metadata
        """
        settings = get_settings()
        top_k = top_k or settings.rag_retrieval_top_k
        
        # Embed the query
        query_vector = self.embeddings.embed_query(query)
        
        # Search Qdrant
        results = self.client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            limit=top_k,
        ).points
        
        # Format results
        formatted = []
        for result in results:
            formatted.append({
                "content": result.payload.get("content", ""),
                "score": result.score,
                "source": result.payload.get("file_name", "unknown"),
                "chunk_id": result.payload.get("chunk_id", ""),
                "metadata": result.payload,
            })
        
        return formatted
    
    def get_collection_info(self) -> dict:
        """Get information about the current collection."""
        try:
            info = self.client.get_collection(self.collection_name)
            return {
                "name": self.collection_name,
                "vectors_count": info.vectors_count,
                "points_count": info.points_count,
            }
        except Exception:
            return {"name": self.collection_name, "status": "not created"}


# ============================================================
# Self-test
# ============================================================
if __name__ == "__main__":
    rprint("\n[bold]🔢 Testing Vector Store[/bold]\n")
    
    from rag.document_loader import load_directory
    from rag.chunker import RecursiveChunker
    
    # Load and chunk documents
    docs = load_directory("rag/documents")
    chunker = RecursiveChunker()
    chunks = chunker.chunk_documents(docs)
    
    # Store in vector database
    store = VectorStore()
    store.add_chunks(chunks)
    
    # Test search
    query = "How do I reset my VPN connection?"
    rprint(f"\n[bold]🔍 Searching: '{query}'[/bold]\n")
    
    results = store.search(query, top_k=3)
    for i, result in enumerate(results, 1):
        rprint(f"  [yellow]Result {i}[/yellow] (score: {result['score']:.4f})")
        rprint(f"  Source: {result['source']}")
        rprint(f"  Content: {result['content'][:150]}...")
        rprint()