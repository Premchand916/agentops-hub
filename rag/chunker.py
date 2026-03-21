"""
AgentOps Hub — Document Chunker
=================================

WHAT THIS DOES:
Takes a full document and splits it into smaller "chunks" that can be
embedded and searched individually.

WHY CHUNKING IS CRITICAL:

Imagine you're searching a 50-page IT manual for "how to reset VPN cache."
Without chunking: The entire 50 pages get embedded as ONE vector.
  → The vector represents the "average meaning" of everything.
  → Search for "VPN cache" might not match because the vector is diluted.

With chunking: The manual is split into 100 focused chunks of ~500 chars each.
  → The chunk about VPN cache gets its OWN vector.
  → Search for "VPN cache" matches that specific chunk perfectly.

THE CHUNKING DILEMMA (this comes up in interviews):
  - Chunks too SMALL → lose context ("Step 3" means nothing without Steps 1-2)
  - Chunks too LARGE → dilute meaning (a 5000-char chunk about many topics matches poorly)
  - The sweet spot is 500-1000 characters with 100-200 overlap

WHY OVERLAP?
  Without overlap, a sentence at the boundary gets CUT IN HALF:
    Chunk 1: "...To reset VPN cache, go to Settings"
    Chunk 2: "> Advanced > Clear Cache in the VPN client."
  → Neither chunk has the full instruction!

  With 200-char overlap:
    Chunk 1: "...To reset VPN cache, go to Settings > Advanced > Clear Cache"
    Chunk 2: "go to Settings > Advanced > Clear Cache in the VPN client."
  → Both chunks have the complete instruction.

INTERVIEW TIP:
Q: "How do you choose chunk size for RAG?"
A: "It depends on the content type. For technical docs with step-by-step
   instructions, I use 800-1000 chars with 200 overlap to preserve procedure
   context. For Q&A or FAQ content, smaller chunks (400-600) work better
   because each Q&A is self-contained. I always validate by testing retrieval
   quality — chunk size is a hyperparameter you tune, not guess."
"""

from dataclasses import dataclass, field
from rag.document_loader import Document
from config.settings import get_settings
from rich import print as rprint


@dataclass
class Chunk:
    """
    A single chunk of text from a larger document.
    
    WHY A SEPARATE CLASS (not reusing Document)?
    Because a Chunk knows things a Document doesn't:
    - chunk_id: unique identifier for retrieval
    - chunk_index: position in the original document (for ordering)
    - parent_source: which document it came from
    
    This matters when you display results:
    "Found in IT Troubleshooting Runbook (chunk 3 of 12)"
    """
    content: str
    metadata: dict = field(default_factory=dict)
    chunk_id: str = ""
    chunk_index: int = 0


class RecursiveChunker:
    """
    Splits documents using a recursive strategy.
    
    HOW RECURSIVE CHUNKING WORKS:
    
    It tries to split on the largest semantic boundaries first:
    1. First, try splitting on "\\n\\n" (paragraph breaks) — best quality
    2. If chunks are still too big, split on "\\n" (line breaks)
    3. If still too big, split on ". " (sentence boundaries)
    4. Last resort: split on " " (word boundaries)
    
    WHY RECURSIVE IS BETTER THAN FIXED-SIZE:
    
    Fixed-size (bad): Cut every 1000 characters regardless of content.
      → "Step 5: Clear VPN ca" | "che: Go to Settings > ..."
      
    Recursive (good): Cut at paragraph/sentence boundaries.
      → "Step 5: Clear VPN cache: Go to Settings > Advanced > Clear Cache"
      
    The recursive approach RESPECTS the structure of the text.
    
    REAL-WORLD PARALLEL:
    If someone asked you to summarize a book chapter by chapter,
    you wouldn't cut pages in half. You'd naturally split at chapter
    boundaries, then sections, then paragraphs. That's recursive chunking.
    """
    
    def __init__(
        self,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
        separators: list[str] | None = None,
    ):
        """
        Initialize the chunker.
        
        Args:
            chunk_size: Maximum characters per chunk (default from settings)
            chunk_overlap: Characters of overlap between chunks (default from settings)
            separators: Priority-ordered list of split characters
        """
        settings = get_settings()
        
        self.chunk_size = chunk_size or settings.rag_chunk_size
        self.chunk_overlap = chunk_overlap or settings.rag_chunk_overlap
        
        # Separators in order of preference (try the best first)
        self.separators = separators or [
            "\n\n",    # Paragraph breaks (best — preserves topic boundaries)
            "\n",      # Line breaks (good — preserves list items, steps)
            ". ",      # Sentences (decent — keeps complete thoughts)
            ", ",      # Clauses (acceptable)
            " ",       # Words (last resort)
        ]
    
    def chunk_document(self, document: Document) -> list[Chunk]:
        """
        Split a single document into chunks.
        
        Args:
            document: A Document object from the loader
            
        Returns:
            List of Chunk objects with metadata from the parent document
        """
        text = document.content
        
        # Skip empty or very short documents
        if not text or len(text.strip()) < 50:
            return []
        
        # Split the text recursively
        raw_chunks = self._recursive_split(text, self.separators)
        
        # Convert to Chunk objects with metadata
        chunks = []
        source_name = document.metadata.get("file_name", "unknown")
        
        for i, chunk_text in enumerate(raw_chunks):
            chunk = Chunk(
                content=chunk_text.strip(),
                chunk_id=f"{source_name}::chunk_{i}",
                chunk_index=i,
                metadata={
                    **document.metadata,   # Copy all parent metadata
                    "chunk_index": i,
                    "total_chunks": len(raw_chunks),
                    "chunk_size": len(chunk_text),
                }
            )
            chunks.append(chunk)
        
        return chunks
    
    def chunk_documents(self, documents: list[Document]) -> list[Chunk]:
        """
        Split multiple documents into chunks.
        
        WHY A SEPARATE METHOD:
        In production, you process thousands of documents. This method
        handles the batch with progress reporting and error handling.
        """
        all_chunks = []
        
        for doc in documents:
            try:
                chunks = self.chunk_document(doc)
                all_chunks.extend(chunks)
            except Exception as e:
                source = doc.metadata.get("file_name", "unknown")
                rprint(f"  [red]❌ Chunking failed for {source}: {e}[/red]")
        
        rprint(f"[cyan]✂️  Created {len(all_chunks)} chunks from {len(documents)} documents[/cyan]")
        return all_chunks
    
    def _recursive_split(self, text: str, separators: list[str]) -> list[str]:
        """
        The core recursive splitting algorithm.
        
        HOW IT WORKS (step by step):
        
        1. Take the first separator (e.g., "\\n\\n")
        2. Split the text on that separator
        3. Walk through the pieces, combining them until chunk_size is reached
        4. If any combined piece is STILL too big, recurse with the NEXT separator
        5. This naturally produces chunks that respect document structure
        
        EXAMPLE with chunk_size=500:
        Text: "Paragraph A (200 chars)\\n\\nParagraph B (400 chars)\\n\\nParagraph C (300 chars)"
        
        Step 1: Split on "\\n\\n" → ["Paragraph A", "Paragraph B", "Paragraph C"]
        Step 2: Combine A+B = 600 chars → too big!
        Step 3: Output A (200), start new chunk with B (400), add C → B+C = 700 → too big!
        Step 4: Output B (400), output C (300)
        Result: [A, B, C] — three clean chunks respecting paragraph boundaries
        """
        final_chunks = []
        
        # Base case: no separators left, just split by character limit
        if not separators:
            return self._split_by_size(text)
        
        separator = separators[0]
        remaining_separators = separators[1:]
        
        # Split on current separator
        pieces = text.split(separator)
        
        current_chunk = ""
        
        for piece in pieces:
            # Would adding this piece exceed chunk_size?
            test_chunk = (
                current_chunk + separator + piece 
                if current_chunk 
                else piece
            )
            
            if len(test_chunk) <= self.chunk_size:
                # Still fits — keep accumulating
                current_chunk = test_chunk
            else:
                # Doesn't fit — save current chunk and start new one
                if current_chunk:
                    final_chunks.append(current_chunk)
                
                # Is this single piece too big on its own?
                if len(piece) > self.chunk_size:
                    # Recurse with finer separators
                    sub_chunks = self._recursive_split(piece, remaining_separators)
                    final_chunks.extend(sub_chunks)
                    current_chunk = ""
                else:
                    current_chunk = piece
        
        # Don't forget the last chunk
        if current_chunk:
            final_chunks.append(current_chunk)
        
        # Add overlap between chunks
        if self.chunk_overlap > 0:
            final_chunks = self._add_overlap(final_chunks)
        
        return [c for c in final_chunks if c.strip()]
    
    def _split_by_size(self, text: str) -> list[str]:
        """Fallback: split by character count when no separators work."""
        chunks = []
        for i in range(0, len(text), self.chunk_size - self.chunk_overlap):
            chunk = text[i:i + self.chunk_size]
            if chunk.strip():
                chunks.append(chunk)
        return chunks
    
    def _add_overlap(self, chunks: list[str]) -> list[str]:
        """
        Add overlap between consecutive chunks.
        
        Takes the last N characters from chunk[i-1] and prepends to chunk[i].
        This ensures information at chunk boundaries isn't lost.
        """
        if len(chunks) <= 1:
            return chunks
        
        overlapped = [chunks[0]]  # First chunk has no predecessor
        
        for i in range(1, len(chunks)):
            prev_chunk = chunks[i - 1]
            # Take the last chunk_overlap characters from previous chunk
            overlap_text = prev_chunk[-self.chunk_overlap:]
            # Prepend to current chunk
            overlapped.append(overlap_text + chunks[i])
        
        return overlapped


# ============================================================
# Self-test
# ============================================================
if __name__ == "__main__":
    from rag.document_loader import load_directory
    
    rprint("\n[bold]✂️  Testing Document Chunker[/bold]\n")
    
    # Load sample documents
    docs = load_directory("rag/documents")
    
    if docs:
        # Chunk them
        chunker = RecursiveChunker()
        chunks = chunker.chunk_documents(docs)
        
        # Show sample
        rprint(f"\n[bold]📋 Sample chunks:[/bold]")
        for chunk in chunks[:3]:
            rprint(f"\n  [yellow]--- {chunk.chunk_id} ---[/yellow]")
            rprint(f"  Size: {len(chunk.content)} chars")
            rprint(f"  Preview: {chunk.content[:150]}...")