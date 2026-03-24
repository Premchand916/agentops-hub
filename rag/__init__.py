"""
AgentOps Hub  RAG Package

The complete Retrieval-Augmented Generation pipeline.

Usage:
    from rag import RAGChain
    
    rag = RAGChain()
    rag.ingest("rag/documents")
    result = rag.query("How do I reset my VPN?")
    print(result["answer"])
"""

from rag.rag_chain import RAGChain
from rag.document_loader import Document, load_document, load_directory
from rag.chunker import Chunk, RecursiveChunker
from rag.vector_store import VectorStore
from rag.bm25_index import BM25Index
from rag.retriever import HybridRetriever
from rag.reranker import Reranker

__all__ = [
    "RAGChain",
    "Document",
    "Chunk",
    "RecursiveChunker",
    "VectorStore",
    "BM25Index",
    "HybridRetriever",
    "Reranker",
    "load_document",
    "load_directory",
]
