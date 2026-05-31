"""Local Embeddings using llama-cpp-python

Provides local embedding generation using GGUF models, similar to QMD's
embeddinggemma implementation. This reduces API costs and improves privacy.

Features:
- Local GGUF model loading
- Query and document formatting (nomic-style)
- Batch embedding generation
- Fallback to sentence-transformers if llama-cpp unavailable
"""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

_log = logging.getLogger(__name__)


@dataclass
class EmbeddingResult:
    """Result from embedding generation."""
    embedding: List[float]
    model: str
    dimensions: int


class LocalEmbeddings:
    """
    Local embedding generation using GGUF models.
    
    Similar to QMD's approach using node-llama-cpp, but for Python.
    Uses llama-cpp-python with GGUF models for local embeddings.

    Usage:
        embeddings = LocalEmbeddings()
        
        # Generate embedding for a query
        result = await embeddings.embed_query("How to configure weebot?")
        
        # Generate embeddings for documents
        results = await embeddings.embed_documents([
            "Document about configuration",
            "Document about security"
        ])
    """

    # Default model configuration
    DEFAULT_MODEL_PATH = os.path.expanduser("~/.cache/weebot/models")
    DEFAULT_MODEL_NAME = "embeddinggemma-2b-q4_k_m.gguf"
    
    # Nomic-style formatting (from QMD)
    QUERY_PREFIX = "task: search result | query: "
    DOC_PREFIX = "title: {title} | text: {text}"

    def __init__(
        self,
        model_path: Optional[str] = None,
        model_name: Optional[str] = None,
        n_ctx: int = 512,
        n_threads: Optional[int] = None,
        use_fallback: bool = True,
    ):
        """
        Initialize local embeddings.
        
        Args:
            model_path: Path to GGUF model directory
            model_name: Name of the GGUF model file
            n_ctx: Context size for the model
            n_threads: Number of threads (defaults to CPU count)
            use_fallback: Use sentence-transformers if llama-cpp fails
        """
        self._model_path = model_path or self.DEFAULT_MODEL_PATH
        self._model_name = model_name or self.DEFAULT_MODEL_NAME
        self._n_ctx = n_ctx
        self._n_threads = n_threads or max(1, os.cpu_count() - 1)
        self._use_fallback = use_fallback
        
        self._model = None
        self._context = None
        self._lock = threading.Lock()
        self._fallback_model = None
        
        # Check what's available
        self._llama_available = self._check_llama_cpp()
        self._sentence_transformers_available = self._check_sentence_transformers()

    def _check_llama_cpp(self) -> bool:
        """Check if llama-cpp-python is available."""
        try:
            from llama_cpp import Llama
            return True
        except ImportError:
            _log.warning("llama-cpp-python not available, will use fallback")
            return False

    def _check_sentence_transformers(self) -> bool:
        """Check if sentence-transformers is available."""
        try:
            from sentence_transformers import SentenceTransformer
            return True
        except ImportError:
            return False

    def _load_model(self) -> None:
        """Load the embedding model."""
        if self._model is not None:
            return
            
        # Try llama-cpp first
        if self._llama_available:
            try:
                from llama_cpp import Llama
                
                full_path = os.path.join(self._model_path, self._model_name)
                
                if not os.path.exists(full_path):
                    _log.warning(f"Model not found at {full_path}, trying fallback")
                    raise FileNotFoundError(f"Model not found: {full_path}")
                
                _log.info(f"Loading GGUF model from {full_path}")
                
                self._model = Llama(
                    model_path=full_path,
                    embedding=True,
                    n_ctx=self._n_ctx,
                    n_threads=self._n_threads,
                )
                _log.info("GGUF model loaded successfully")
                return
            except Exception as e:
                _log.warning(f"Failed to load GGUF model: {e}")
        
        # Fallback to sentence-transformers
        if self._use_fallback and self._sentence_transformers_available:
            try:
                from sentence_transformers import SentenceTransformer
                
                _log.info("Loading sentence-transformers model as fallback")
                # Use a lightweight embedding model
                self._fallback_model = SentenceTransformer('all-MiniLM-L6-v2')
                _log.info("Sentence-transformers model loaded")
                return
            except Exception as e:
                _log.error(f"Failed to load fallback model: {e}")
        
        raise RuntimeError("No embedding model available")

    def _ensure_model_loaded(self) -> None:
        """Ensure model is loaded (thread-safe)."""
        with self._lock:
            if self._model is None and self._fallback_model is None:
                self._load_model()

    def format_query(self, query: str) -> str:
        """
        Format query for embedding.
        Uses nomic-style task prefix (from QMD).
        """
        return f"{self.QUERY_PREFIX}{query}"

    def format_document(self, text: str, title: Optional[str] = None) -> str:
        """
        Format document for embedding.
        Uses nomic-style format with title and text (from QMD).
        """
        return self.DOC_PREFIX.format(title=title or "none", text=text)

    async def embed_query(self, query: str) -> EmbeddingResult:
        """
        Generate embedding for a query.
        
        Args:
            query: The query string to embed
            
        Returns:
            EmbeddingResult with embedding vector
        """
        self._ensure_model_loaded()
        
        formatted = self.format_query(query)
        
        if self._model is not None:
            # Use llama-cpp
            embedding = self._model.embed(formatted)
            return EmbeddingResult(
                embedding=embedding,
                model=self._model_name,
                dimensions=len(embedding)
            )
        elif self._fallback_model is not None:
            # Use sentence-transformers
            embedding = self._fallback_model.encode(formatted).tolist()
            return EmbeddingResult(
                embedding=embedding,
                model="all-MiniLM-L6-v2",
                dimensions=len(embedding)
            )
        
        raise RuntimeError("No model loaded")

    async def embed_documents(
        self,
        documents: List[str],
        titles: Optional[List[str]] = None,
    ) -> List[EmbeddingResult]:
        """
        Generate embeddings for multiple documents.
        
        Args:
            documents: List of document texts
            titles: Optional list of titles for each document
            
        Returns:
            List of EmbeddingResults
        """
        self._ensure_model_loaded()
        
        results = []
        titles = titles or [None] * len(documents)
        
        for doc, title in zip(documents, titles):
            formatted = self.format_document(doc, title)
            
            if self._model is not None:
                embedding = self._model.embed(formatted)
                results.append(EmbeddingResult(
                    embedding=embedding,
                    model=self._model_name,
                    dimensions=len(embedding)
                ))
            elif self._fallback_model is not None:
                embedding = self._fallback_model.encode(formatted).tolist()
                results.append(EmbeddingResult(
                    embedding=embedding,
                    model="all-MiniLM-L6-v2",
                    dimensions=len(embedding)
                ))
        
        return results

    async def embed_batch(
        self,
        texts: List[str],
        is_queries: bool = False,
    ) -> List[EmbeddingResult]:
        """
        Generate embeddings for a batch of texts.
        
        Args:
            texts: List of texts to embed
            is_queries: If True, format as queries; otherwise as documents
            
        Returns:
            List of EmbeddingResults
        """
        self._ensure_model_loaded()
        
        results = []
        
        for text in texts:
            formatted = self.format_query(text) if is_queries else self.format_document(text)
            
            if self._model is not None:
                embedding = self._model.embed(formatted)
                results.append(EmbeddingResult(
                    embedding=embedding,
                    model=self._model_name,
                    dimensions=len(embedding)
                ))
            elif self._fallback_model is not None:
                embedding = self._fallback_model.encode(formatted).tolist()
                results.append(EmbeddingResult(
                    embedding=embedding,
                    model="all-MiniLM-L6-v2",
                    dimensions=len(embedding)
                ))
        
        return results

    def get_embedding_dimension(self) -> int:
        """Get the embedding dimension for the current model."""
        self._ensure_model_loaded()
        
        if self._model is not None:
            # GGUF embeddinggemma-2b typically has 256 dimensions
            return 256
        elif self._fallback_model is not None:
            # all-MiniLM-L6-v2 has 384 dimensions
            return 384
        
        return 0

    def is_available(self) -> bool:
        """Check if embedding generation is available."""
        try:
            self._ensure_model_loaded()
            return self._model is not None or self._fallback_model is not None
        except Exception:
            return False

    def get_model_info(self) -> Dict[str, Any]:
        """Get information about the loaded model."""
        self._ensure_model_loaded()
        
        info = {
            "llama_cpp_loaded": self._model is not None,
            "fallback_loaded": self._fallback_model is not None,
            "model_name": self._model_name if self._model else "sentence-transformers",
            "dimensions": self.get_embedding_dimension(),
        }
        
        return info

    def unload(self) -> None:
        """Unload the model to free memory."""
        with self._lock:
            self._model = None
            self._context = None
            self._fallback_model = None
            _log.info("Embedding model unloaded")


# Singleton instance
_embeddings: Optional[LocalEmbeddings] = None
_embeddings_lock = threading.Lock()


def get_local_embeddings(**kwargs) -> LocalEmbeddings:
    """Get singleton LocalEmbeddings instance."""
    global _embeddings
    
    with _embeddings_lock:
        if _embeddings is None:
            _embeddings = LocalEmbeddings(**kwargs)
        return _embeddings