"""RAG Engine - Retrieval-Augmented Generation for Weebot

Combines local embeddings and QMD search to provide relevant context
for agent queries. Implements smart chunking similar to QMD's approach.

Features:
- Hybrid search (BM25 + vector)
- Smart document chunking (900 tokens, 15% overlap)
- Context formatting for LLM prompts
- Citation/referencing support
"""
from __future__ import annotations

import logging
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from weebot.qmd_integration.embeddings import LocalEmbeddings, get_local_embeddings
from weebot.qmd_integration.mcp_client import QMDMCPClient, get_qmd_client, QMDDocument

_log = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    """A retrieved document chunk with metadata."""
    content: str
    source_file: str
    docid: str
    score: float
    chunk_index: int
    collection: Optional[str] = None
    line_number: Optional[int] = None


@dataclass
class RAGContext:
    """Complete RAG context for an agent query."""
    query: str
    chunks: List[RetrievedChunk]
    total_tokens: int
    sources: List[str]
    
    @property
    def context_text(self) -> str:
        """Get formatted context text."""
        return "\n\n---\n\n".join(
            f"Source: {chunk.source_file} (score: {chunk.score:.2f})\n{chunk.content}"
            for chunk in self.chunks
        )
    
    @property
    def citations(self) -> List[str]:
        """Get formatted citations."""
        return [f"[{chunk.docid}] {chunk.source_file}" for chunk in self.chunks]


class RAGEngine:
    """
    Retrieval-Augmented Generation Engine.
    
    Combines QMD search with local embeddings for intelligent context retrieval.
    Similar to QMD's approach but integrated with weebot's agent system.

    Usage:
        rag = RAGEngine()
        
        # Get relevant context for a query
        context = await rag.retrieve(
            query="How do I configure authentication?",
            max_tokens=2000,
        )
        
        # Use in agent prompt
        prompt = f"Context:\n{context.context_text}\n\nQuestion: {query}"
    """

    # Chunking configuration (from QMD)
    CHUNK_TOKENS = 900
    CHUNK_OVERLAP = 0.15  # 15% overlap
    
    # Default collection
    DEFAULT_COLLECTION = "weebot"

    def __init__(
        self,
        embeddings: Optional[LocalEmbeddings] = None,
        mcp_client: Optional[QMDMCPClient] = None,
        default_collection: Optional[str] = None,
    ):
        """
        Initialize RAG engine.
        
        Args:
            embeddings: Local embeddings instance
            mcp_client: QMD MCP client instance
            default_collection: Default collection to search
        """
        self._embeddings = embeddings
        self._mcp_client = mcp_client
        self._default_collection = default_collection or self.DEFAULT_COLLECTION
        
        self._lock = threading.Lock()

    @property
    def embeddings(self) -> LocalEmbeddings:
        """Get embeddings instance (lazy load)."""
        if self._embeddings is None:
            self._embeddings = get_local_embeddings()
        return self._embeddings

    @property
    def mcp_client(self) -> QMDMCPClient:
        """Get MCP client instance (lazy load)."""
        if self._mcp_client is None:
            self._mcp_client = get_qmd_client()
        return self._mcp_client

    async def retrieve(
        self,
        query: str,
        max_tokens: int = 2000,
        collection: Optional[str] = None,
        min_score: float = 0.1,
        use_hybrid: bool = True,
    ) -> RAGContext:
        """
        Retrieve relevant context for a query.
        
        Args:
            query: The user's query
            max_tokens: Maximum tokens in context
            collection: Collection to search (uses default if not provided)
            min_score: Minimum relevance score
            use_hybrid: Use hybrid (BM25 + vector) search
            
        Returns:
            RAGContext with retrieved chunks
        """
        collection = collection or self._default_collection
        
        # Search using QMD
        if use_hybrid:
            # Use QMD's query (with expansion + reranking)
            documents = await self.mcp_client.search(
                query=query,
                collection=collection,
                n=10,
                min_score=min_score,
            )
        else:
            # Use BM25 only
            documents = await self.mcp_client.search_bm25(
                query=query,
                collection=collection,
                n=10,
            )
        
        if not documents:
            return RAGContext(
                query=query,
                chunks=[],
                total_tokens=0,
                sources=[],
            )
        
        # Get full content for top documents
        doc_ids = [doc.docid for doc in documents[:5]]
        full_docs = await self.mcp_client.multi_get(
            docids=doc_ids,
            max_lines=200,
        )
        
        # Chunk documents
        chunks = []
        for doc in full_docs:
            if doc.content:
                doc_chunks = self._chunk_document(
                    doc.content,
                    doc.file,
                    doc.docid,
                    doc.score,
                    doc.collection,
                )
                chunks.extend(doc_chunks)
        
        # Sort by score and limit to max_tokens
        chunks = sorted(chunks, key=lambda x: x.score, reverse=True)
        
        # Estimate tokens (rough: 4 chars per token)
        total_chars = 0
        selected_chunks = []
        
        for chunk in chunks:
            chunk_tokens = len(chunk.content) // 4
            if total_chars + chunk_tokens <= max_tokens * 4:
                selected_chunks.append(chunk)
                total_chars += chunk_tokens
        
        # Build sources list
        sources = list(set(c.source_file for c in selected_chunks))
        
        return RAGContext(
            query=query,
            chunks=selected_chunks,
            total_tokens=total_chars // 4,
            sources=sources,
        )

    async def retrieve_with_vector(
        self,
        query: str,
        max_tokens: int = 2000,
        collection: Optional[str] = None,
    ) -> RAGContext:
        """
        Retrieve using vector similarity search.
        
        Args:
            query: The user's query
            max_tokens: Maximum tokens in context
            collection: Collection to search
            
        Returns:
            RAGContext with retrieved chunks
        """
        collection = collection or self._default_collection
        
        # Get query embedding
        try:
            query_embedding = await self.embeddings.embed_query(query)
        except Exception as e:
            _log.warning(f"Failed to get query embedding: {e}")
            # Fallback to BM25
            return await self.retrieve(query, max_tokens, collection, use_hybrid=False)
        
        # Search using QMD vector search
        documents = await self.mcp_client.vsearch(
            query=query,
            collection=collection,
            n=10,
        )
        
        if not documents:
            return RAGContext(
                query=query,
                chunks=[],
                total_tokens=0,
                sources=[],
            )
        
        # Get full content
        doc_ids = [doc.docid for doc in documents[:5]]
        full_docs = await self.mcp_client.multi_get(
            docids=doc_ids,
            max_lines=200,
        )
        
        # Chunk and build context
        chunks = []
        for doc in full_docs:
            if doc.content:
                doc_chunks = self._chunk_document(
                    doc.content,
                    doc.file,
                    doc.docid,
                    doc.score,
                    doc.collection,
                )
                chunks.extend(doc_chunks)
        
        # Sort by score and limit
        chunks = sorted(chunks, key=lambda x: x.score, reverse=True)
        
        total_chars = 0
        selected_chunks = []
        
        for chunk in chunks:
            chunk_tokens = len(chunk.content) // 4
            if total_chars + chunk_tokens <= max_tokens * 4:
                selected_chunks.append(chunk)
                total_chars += chunk_tokens
        
        sources = list(set(c.source_file for c in selected_chunks))
        
        return RAGContext(
            query=query,
            chunks=selected_chunks,
            total_tokens=total_chars // 4,
            sources=sources,
        )

    def _chunk_document(
        self,
        content: str,
        source_file: str,
        docid: str,
        score: float,
        collection: Optional[str] = None,
    ) -> List[RetrievedChunk]:
        """
        Chunk document using smart chunking (from QMD).
        
        Uses 900 tokens per chunk with 15% overlap,
        preferring markdown headings as boundaries.
        """
        # Estimate tokens (rough: 4 chars per token)
        chunk_size = self.CHUNK_TOKENS * 4
        overlap = int(chunk_size * self.CHUNK_OVERLAP)
        
        chunks = []
        
        # Try to split on markdown headings
        heading_pattern = re.compile(r'^#{1,6}\s+.+$', re.MULTILINE)
        sections = heading_pattern.split(content)
        
        current_chunk = ""
        chunk_index = 0
        
        for section in sections:
            if not section.strip():
                continue
                
            # Check if adding this section would exceed chunk size
            if len(current_chunk) + len(section) > chunk_size and current_chunk:
                # Save current chunk
                chunks.append(RetrievedChunk(
                    content=current_chunk.strip(),
                    source_file=source_file,
                    docid=docid,
                    score=score,
                    chunk_index=chunk_index,
                    collection=collection,
                ))
                
                # Start new chunk with overlap
                overlap_start = max(0, len(current_chunk) - overlap)
                current_chunk = current_chunk[overlap_start:] + "\n\n" + section
                chunk_index += 1
            else:
                current_chunk += "\n\n" + section
        
        # Add final chunk
        if current_chunk.strip():
            chunks.append(RetrievedChunk(
                content=current_chunk.strip(),
                source_file=source_file,
                docid=docid,
                score=score,
                chunk_index=chunk_index,
                collection=collection,
            ))
        
        return chunks

    def format_for_prompt(
        self,
        context: RAGContext,
        include_citations: bool = True,
    ) -> str:
        """
        Format RAG context for inclusion in an agent prompt.
        
        Args:
            context: The RAG context
            include_citations: Include source citations
            
        Returns:
            Formatted string for prompt
        """
        parts = []
        
        if context.chunks:
            parts.append("## Relevant Context")
            parts.append("")
            parts.append(context.context_text)
        
        if include_citations and context.citations:
            parts.append("")
            parts.append("## Sources")
            parts.append("")
            for citation in context.citations:
                parts.append(f"- {citation}")
        
        return "\n".join(parts)

    async def search_and_format(
        self,
        query: str,
        max_tokens: int = 2000,
        collection: Optional[str] = None,
        include_citations: bool = True,
    ) -> str:
        """
        Convenience method: search and format in one call.
        
        Args:
            query: The user's query
            max_tokens: Maximum tokens in context
            collection: Collection to search
            include_citations: Include source citations
            
        Returns:
            Formatted context string for prompt
        """
        context = await self.retrieve(
            query=query,
            max_tokens=max_tokens,
            collection=collection,
        )
        
        return self.format_for_prompt(context, include_citations)


# Singleton instance
_rag_engine: Optional[RAGEngine] = None
_rag_lock = threading.Lock()


def get_rag_engine(**kwargs) -> RAGEngine:
    """Get singleton RAGEngine instance."""
    global _rag_engine
    
    with _rag_lock:
        if _rag_engine is None:
            _rag_engine = RAGEngine(**kwargs)
        return _rag_engine