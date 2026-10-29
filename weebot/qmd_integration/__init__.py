"""QMD integration for Weebot: local embeddings.

Local embeddings use llama-cpp-python, with sentence-transformers as the fallback.
The QMD MCP client, RAG engine and query expander had no caller and were deleted
in wave 6 G5.
"""

from weebot.qmd_integration.embeddings import LocalEmbeddings, get_local_embeddings

__all__ = [
    "LocalEmbeddings",
    "get_local_embeddings",
]
