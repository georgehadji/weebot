# QMD Integration Documentation

## Overview

The QMD integration module gives Weebot local embeddings, inspired by the QMD
(Query Markup Documents) project. Embeddings come from a GGUF model through
llama-cpp-python, with sentence-transformers as the fallback; no cloud API is
needed. The skill retriever, the MCP tool retriever and the knowledge graph use it.

The QMD MCP client, RAG engine and query expander that this module once held had
no caller and were deleted in wave 6 G5.

## Installation

```bash
# Install optional dependencies
pip install llama-cpp-python  # For local GGUF embeddings
pip install sentence-transformers  # Fallback embeddings
```

Download the GGUF embedding model to `~/.cache/weebot/models/`:

```bash
wget -O ~/.cache/weebot/models/embeddinggemma-2b-q4_k_m.gguf <model_url>
```

## Module Structure

```
weebot/qmd_integration/
├── __init__.py           # Module exports
└── embeddings.py         # Local embeddings (llama-cpp-python)
```

## Component

### LocalEmbeddings

Generate embeddings locally using GGUF models.

```python
from weebot.qmd_integration import get_local_embeddings

embeddings = get_local_embeddings()

# Generate query embedding
result = await embeddings.embed_query("How to configure weebot?")
print(f"Dimensions: {result.dimensions}")
print(f"Model: {result.model}")

# Generate document embeddings
results = await embeddings.embed_documents(
    documents=["Doc 1", "Doc 2"],
    titles=["Title 1", "Title 2"]
)

# Batch embedding
results = await embeddings.embed_batch(
    texts=["Query 1", "Query 2"],
    is_queries=True
)
```

**Features:**
- GGUF model support (llama-cpp-python)
- Fallback to sentence-transformers
- Nomic-style formatting (task prefixes)
- Batch processing
- Thread-safe singleton

