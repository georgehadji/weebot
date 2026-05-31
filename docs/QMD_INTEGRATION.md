# QMD Integration Documentation

## Overview

The QMD integration module provides Weebot with local knowledge base and RAG (Retrieval-Augmented Generation) capabilities, inspired by the QMD (Query Markup Documents) project.

This integration enables:
- **Local Embeddings** - Generate embeddings using GGUF models (no cloud API needed)
- **QMD MCP Client** - Connect to QMD's MCP server for document search
- **RAG Engine** - Retrieve relevant context for agent queries
- **Query Expansion** - Improve search with local LLM

## Installation

### Prerequisites

```bash
# Install optional dependencies
pip install llama-cpp-python  # For local GGUF embeddings
pip install sentence-transformers  # Fallback embeddings

# Install QMD (optional, for full functionality)
# See: https://github.com/...
```

### Model Setup

Download GGUF models to `~/.cache/weebot/models/`:

```bash
# Embedding model (for embeddings)
wget -O ~/.cache/weebot/models/embeddinggemma-2b-q4_k_m.gguf <model_url>

# LLM model (for query expansion)
wget -O ~/.cache/weebot/models/qwen3-8b-q4_k_m.gguf <model_url>
```

## Module Structure

```
weebot/qmd_integration/
├── __init__.py           # Module exports
├── embeddings.py          # Local embeddings (llama-cpp-python)
├── mcp_client.py         # QMD MCP client
├── rag_engine.py         # RAG context retrieval
└── query_expander.py     # Query expansion
```

## Components

### 1. LocalEmbeddings

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

### 2. QMDMCPClient

Connect to QMD MCP server for document search.

```python
from weebot.qmd_integration import get_qmd_client

client = get_qmd_client(transport="http", port=8181)

# Search with query expansion (recommended)
results = await client.search(
    query="how to configure authentication",
    collection="notes",
    n=10
)

# BM25 full-text search
results = await client.search_bm25("security settings")

# Vector similarity search
results = await client.vsearch("template usage")

# Get document by ID
doc = await client.get_document("#abc123")

# Get multiple documents
docs = await client.multi_get("abc123, def456")

# List collections
collections = await client.list_collections()
```

**Features:**
- HTTP and stdio transport
- Query expansion + reranking
- BM25 full-text search
- Vector similarity search
- Document retrieval by ID
- Collection management

### 3. RAGEngine

Retrieve relevant context for agent queries.

```python
from weebot.qmd_integration import get_rag_engine

rag = get_rag_engine()

# Retrieve context
context = await rag.retrieve(
    query="How do I configure authentication?",
    max_tokens=2000,
    collection="weebot_docs"
)

# Use in prompt
prompt = f"""Context:
{context.context_text}

Question: {query}

Answer:"""

# Get citations
for citation in context.citations:
    print(citation)

# Search and format in one call
formatted = await rag.search_and_format(
    query="template engine usage",
    max_tokens=1500
)
```

**Features:**
- Hybrid search (BM25 + vector)
- Smart chunking (900 tokens, 15% overlap)
- Markdown heading-aware splitting
- Context formatting for prompts
- Citation support

### 4. QueryExpander

Expand queries using local LLM.

```python
from weebot.qmd_integration import get_query_expander

expander = get_query_expander()

# Expand query
result = await expander.expand("how to config auth")

print(f"Original: {result.original}")
print(f"Expanded: {result.expanded}")
print(f"Terms: {result.terms}")
print(f"Synonyms: {result.synonyms}")

# Get search terms for BM25
terms = expander.get_expanded_search_terms("config auth")
```

**Features:**
- Local LLM expansion (Qwen3)
- Rule-based fallback
- Synonym generation
- Abbreviation expansion

## Usage Examples

### Complete RAG Flow

```python
from weebot.qmd_integration import (
    get_rag_engine,
    get_query_expander,
)

# Initialize
rag = get_rag_engine()
expander = get_query_expander()

# Expand query
expanded = await expander.expand(user_query)

# Retrieve context
context = await rag.retrieve(
    query=expanded.expanded,
    max_tokens=2000,
    collection="weebot_docs"
)

# Build prompt
prompt = f"""You are a Weebot assistant. Use the following context to answer the question.

## Context
{context.context_text}

## Sources
{chr(10).join(context.citations)}

## Question
{user_query}

## Answer
"""
```

### Agent Integration

```python
from weebot.qmd_integration import get_rag_engine

class RAGEnabledAgent:
    def __init__(self):
        self.rag = get_rag_engine()
    
    async def process_query(self, query: str) -> str:
        # Get relevant context
        context = await self.rag.retrieve(
            query=query,
            max_tokens=1500
        )
        
        if not context.chunks:
            return "I don't have relevant context for that."
        
        # Build prompt with context
        prompt = f"""Context from documentation:
{context.context_text}

Question: {query}

Answer based on the context above:"""
        
        # Call LLM (using existing weebot AI router)
        response = await self.ai_router.complete(prompt)
        
        return response
```

## Testing

Run QMD integration tests:

```bash
pytest weebot/tests/unit/test_qmd_integration.py -v
```

All 21 tests should pass.

## Configuration

### LocalEmbeddings

```python
embeddings = get_local_embeddings(
    model_path="~/.cache/weebot/models",
    model_name="embeddinggemma-2b-q4_k_m.gguf",
    n_ctx=512,
    n_threads=4,
    use_fallback=True
)
```

### QMDMCPClient

```python
client = get_qmd_client(
    qmd_path="~/.local/bin/qmd",
    transport="http",
    port=8181,
    host="localhost",
    timeout=30.0
)
```

### RAGEngine

```python
rag = get_rag_engine(
    default_collection="weebot_docs",
    embeddings=embeddings,
    mcp_client=client
)
```

### QueryExpander

```python
expander = get_query_expander(
    model_path="~/.cache/weebot/models",
    model_name="qwen3-8b-q4_k_m.gguf",
    n_ctx=2048,
    temperature=0.3,
    use_fallback=True
)
```

## Cost Savings

| Feature | Cloud Cost | Local Cost |
|---------|-----------|------------|
| Embeddings (1M chars) | ~$0.10 | $0.00 |
| Query Expansion | ~$0.01 | $0.00 |
| Document Search | ~$0.00 | $0.00 |

**Estimated savings: ~80% on embedding costs**

## QMD Setup (Optional)

For full QMD integration, install and configure QMD:

```bash
# Install QMD
bun install -g qmd

# Add collections
qmd collection add ~/Documents/notes --name notes --mask '**/*.md'
qmd collection add ~/weebot/docs --name weebot_docs

# Add context
qmd context add / "Weebot is an AI agent framework..."

# Start MCP server
qmd mcp --http --port 8181
```

See [QMD Documentation](https://github.com/...) for more details.