"""QMD Integration for Weebot - Local Knowledge Base & RAG

This module provides integration with QMD (Query Markup Documents) for:
- Local embeddings using llama-cpp-python
- QMD MCP client for document search
- RAG context retrieval
- Query expansion with local LLM

Based on QMD architecture from: E:/Documents/Vibe-Coding/weebot/Useful Github Projects/qmd-main
"""
from weebot.qmd_integration.embeddings import LocalEmbeddings, get_local_embeddings
from weebot.qmd_integration.mcp_client import QMDMCPClient, get_qmd_client
from weebot.qmd_integration.rag_engine import RAGEngine, get_rag_engine
from weebot.qmd_integration.query_expander import QueryExpander, get_query_expander

__all__ = [
    "LocalEmbeddings",
    "get_local_embeddings",
    "QMDMCPClient", 
    "get_qmd_client",
    "RAGEngine",
    "get_rag_engine",
    "QueryExpander",
    "get_query_expander",
]