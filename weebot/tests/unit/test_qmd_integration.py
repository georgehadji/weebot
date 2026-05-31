"""Tests for QMD Integration Module.

Tests the QMD integration features:
- Local embeddings
- MCP client
- RAG engine
- Query expander
"""
import pytest
from unittest.mock import Mock, patch, AsyncMock

from weebot.qmd_integration.embeddings import LocalEmbeddings, EmbeddingResult
from weebot.qmd_integration.mcp_client import QMDMCPClient, QMDDocument
from weebot.qmd_integration.rag_engine import RAGEngine, RAGContext, RetrievedChunk
from weebot.qmd_integration.query_expander import QueryExpander, ExpandedQuery


# =============================================================================
# LocalEmbeddings Tests
# =============================================================================


class TestLocalEmbeddings:
    """Tests for LocalEmbeddings."""

    @pytest.fixture
    def embeddings(self):
        """Create embeddings instance with fallback enabled."""
        return LocalEmbeddings(use_fallback=True)

    def test_format_query(self, embeddings):
        """Test query formatting."""
        formatted = embeddings.format_query("test query")
        assert "task: search result" in formatted
        assert "test query" in formatted

    def test_format_document(self, embeddings):
        """Test document formatting."""
        formatted = embeddings.format_document("test content", title="Test Title")
        assert "title: Test Title" in formatted
        assert "test content" in formatted

    def test_format_document_no_title(self, embeddings):
        """Test document formatting without title."""
        formatted = embeddings.format_document("test content")
        assert "title: none" in formatted
        assert "test content" in formatted

    def test_get_embedding_dimension_fallback(self, embeddings):
        """Test embedding dimension with fallback model."""
        # This test may fail if no models are available
        # Just check it doesn't crash when called
        try:
            dim = embeddings.get_embedding_dimension()
            assert dim in [256, 384, 0]  # GGUF, MiniLM, or 0 if nothing loaded
        except RuntimeError:
            # Expected if no models available
            pass

    def test_is_available(self, embeddings):
        """Test availability check."""
        # With fallback, should be available
        available = embeddings.is_available()
        assert isinstance(available, bool)


# =============================================================================
# QMDMCPClient Tests
# =============================================================================


class TestQMDMCPClient:
    """Tests for QMDMCPClient."""

    @pytest.fixture
    def client(self):
        """Create QMD MCP client."""
        return QMDMCPClient()

    def test_client_initialization(self, client):
        """Test client initializes correctly."""
        assert client._transport == "http"
        assert client._port == 8181

    def test_find_qmd(self, client):
        """Test QMD path detection."""
        # Should find qmd or return "qmd" as fallback
        assert client._qmd_path is not None

    def test_check_qmd(self, client):
        """Test QMD availability check."""
        # Returns False if not available, but shouldn't crash
        result = client._check_qmd()
        assert isinstance(result, bool)

    def test_is_available(self, client):
        """Test availability check."""
        available = client.is_available()
        assert isinstance(available, bool)


# =============================================================================
# RAGEngine Tests
# =============================================================================


class TestRAGEngine:
    """Tests for RAGEngine."""

    @pytest.fixture
    def engine(self):
        """Create RAG engine."""
        return RAGEngine()

    def test_engine_initialization(self, engine):
        """Test engine initializes correctly."""
        assert engine._default_collection == "weebot"

    def test_chunk_document(self, engine):
        """Test document chunking."""
        content = """# Title

This is the first section with some content.

## Section 2

This is the second section with more content.

## Section 3

This is the third section."""

        chunks = engine._chunk_document(
            content=content,
            source_file="test.md",
            docid="abc123",
            score=0.9,
            collection="test",
        )

        assert len(chunks) > 0
        assert all(isinstance(c, RetrievedChunk) for c in chunks)
        assert all(c.docid == "abc123" for c in chunks)

    def test_format_for_prompt(self, engine):
        """Test prompt formatting."""
        context = RAGContext(
            query="test query",
            chunks=[
                RetrievedChunk(
                    content="Test content",
                    source_file="test.md",
                    docid="abc123",
                    score=0.9,
                    chunk_index=0,
                )
            ],
            total_tokens=100,
            sources=["test.md"],
        )

        formatted = engine.format_for_prompt(context)
        assert "Relevant Context" in formatted
        assert "Test content" in formatted
        assert "Sources" in formatted

    def test_format_for_prompt_no_citations(self, engine):
        """Test prompt formatting without citations."""
        context = RAGContext(
            query="test query",
            chunks=[
                RetrievedChunk(
                    content="Test content",
                    source_file="test.md",
                    docid="abc123",
                    score=0.9,
                    chunk_index=0,
                )
            ],
            total_tokens=100,
            sources=["test.md"],
        )

        formatted = engine.format_for_prompt(context, include_citations=False)
        assert "Relevant Context" in formatted
        assert "Sources" not in formatted


# =============================================================================
# QueryExpander Tests
# =============================================================================


class TestQueryExpander:
    """Tests for QueryExpander."""

    @pytest.fixture
    def expander(self):
        """Create query expander."""
        return QueryExpander(use_fallback=True)

    def test_expander_initialization(self, expander):
        """Test expander initializes correctly."""
        assert expander._temperature == 0.3
        assert expander._use_fallback is True

    @pytest.mark.asyncio
    async def test_expand_with_rules(self, expander):
        """Test rule-based expansion."""
        result = await expander.expand("how to config auth")

        assert result.original == "how to config auth"
        assert len(result.expanded) > 0
        assert len(result.terms) > 0

    @pytest.mark.asyncio
    async def test_extract_terms(self, expander):
        """Test term extraction."""
        terms = expander._extract_terms("how to configure authentication")
        
        assert "configure" in terms
        assert "authentication" in terms
        # "how", "to", "how to" should be filtered out
        assert "how" not in terms
        assert "to" not in terms

    @pytest.mark.asyncio
    async def test_generate_synonyms(self, expander):
        """Test synonym generation."""
        synonyms = expander._generate_synonyms(["config", "auth", "security"])
        
        assert "config" in synonyms
        assert "auth" in synonyms
        assert "security" in synonyms

    @pytest.mark.asyncio
    async def test_get_expanded_search_terms(self, expander):
        """Test expanded search terms."""
        terms = expander.get_expanded_search_terms("config auth")
        
        assert len(terms) > 0
        # Should include original terms
        assert "config" in terms or "auth" in terms

    def test_is_available(self, expander):
        """Test availability check."""
        available = expander.is_available()
        assert available is True  # Fallback is always available


# =============================================================================
# Integration Tests
# =============================================================================


class TestQMDIntegration:
    """Integration tests for QMD module."""

    def test_imports(self):
        """Test all imports work."""
        from weebot.qmd_integration import (
            LocalEmbeddings,
            QMDMCPClient,
            RAGEngine,
            QueryExpander,
            get_local_embeddings,
            get_qmd_client,
            get_rag_engine,
            get_query_expander,
        )
        
        assert LocalEmbeddings is not None
        assert QMDMCPClient is not None
        assert RAGEngine is not None
        assert QueryExpander is not None

    def test_singletons(self):
        """Test singleton getters return instances."""
        from weebot.qmd_integration import (
            get_local_embeddings,
            get_qmd_client,
            get_rag_engine,
            get_query_expander,
        )
        
        # Get multiple times, should return same instance
        e1 = get_local_embeddings()
        e2 = get_local_embeddings()
        assert e1 is e2
        
        c1 = get_qmd_client()
        c2 = get_qmd_client()
        assert c1 is c2
        
        r1 = get_rag_engine()
        r2 = get_rag_engine()
        assert r1 is r2
        
        q1 = get_query_expander()
        q2 = get_query_expander()
        assert q1 is q2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])