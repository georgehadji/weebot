"""Query Expander - Local LLM Query Expansion

Uses local GGUF models for query expansion, similar to QMD's approach
using Qwen3 for expanding user queries into better search queries.

Features:
- Local LLM inference for query expansion
- Synonym generation
- Related term extraction
- Fallback to rule-based expansion if LLM unavailable
"""
from __future__ import annotations

import logging
import os
import re
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

from weebot.config.constants import MAX_TOKENS_BRIEF

_log = logging.getLogger(__name__)


@dataclass
class ExpandedQuery:
    """An expanded query with original and expanded terms."""
    original: str
    expanded: str
    terms: List[str]
    synonyms: Dict[str, List[str]]
    confidence: float


class QueryExpander:
    """
    Query expansion using local LLM.
    
    Similar to QMD's approach using Qwen3 for query expansion.
    Expands user queries with related terms to improve search results.

    Usage:
        expander = QueryExpander()
        
        # Expand a query
        result = await expander.expand("how to config auth")
        
        print(result.expanded)
        # "how to configure authentication security settings login"
        
        print(result.synonyms)
        # {"config": ["configure", "setup", "settings"], "auth": ["authentication", "login"]}
    """

    # Default model configuration
    DEFAULT_MODEL_PATH = os.path.expanduser("~/.cache/weebot/models")
    DEFAULT_MODEL_NAME = "qwen3-8b-q4_k_m.gguf"
    
    # System prompt for query expansion
    SYSTEM_PROMPT = """You are a query expansion assistant. Your task is to expand user queries to improve search results.

For the given query, you must:
1. Identify key concepts and terms
2. Add relevant synonyms and related terms
3. Expand abbreviations
4. Add domain-specific terminology

Respond ONLY with the expanded query, no explanations."""

    def __init__(
        self,
        model_path: Optional[str] = None,
        model_name: Optional[str] = None,
        n_ctx: int = 2048,
        n_threads: Optional[int] = None,
        temperature: float = 0.3,
        use_fallback: bool = True,
    ):
        """
        Initialize query expander.
        
        Args:
            model_path: Path to GGUF model directory
            model_name: Name of the GGUF model file
            n_ctx: Context size for the model
            n_threads: Number of threads
            temperature: Generation temperature
            use_fallback: Use rule-based expansion if LLM fails
        """
        self._model_path = model_path or self.DEFAULT_MODEL_PATH
        self._model_name = model_name or self.DEFAULT_MODEL_NAME
        self._n_ctx = n_ctx
        self._n_threads = n_threads or max(1, os.cpu_count() - 1)
        self._temperature = temperature
        self._use_fallback = use_fallback
        
        self._model = None
        self._lock = threading.Lock()
        
        # Check availability
        self._llama_available = self._check_llama_cpp()

    def _check_llama_cpp(self) -> bool:
        """Check if llama-cpp-python is available."""
        try:
            from llama_cpp import Llama
            return True
        except ImportError:
            _log.warning("llama-cpp-python not available for query expansion")
            return False

    def _load_model(self) -> None:
        """Load the LLM model."""
        if self._model is not None:
            return
            
        if not self._llama_available:
            return
            
        try:
            from llama_cpp import Llama
            
            full_path = os.path.join(self._model_path, self._model_name)
            
            if not os.path.exists(full_path):
                _log.warning(f"Query expansion model not found at {full_path}")
                return
            
            _log.info(f"Loading query expansion model from {full_path}")
            
            self._model = Llama(
                model_path=full_path,
                n_ctx=self._n_ctx,
                n_threads=self._n_threads,
                verbose=False,
            )
            _log.info("Query expansion model loaded")
            
        except Exception as e:
            _log.warning(f"Failed to load query expansion model: {e}")

    def _ensure_model_loaded(self) -> None:
        """Ensure model is loaded (thread-safe)."""
        with self._lock:
            if self._model is None:
                self._load_model()

    async def expand(self, query: str) -> ExpandedQuery:
        """
        Expand a query using local LLM.
        
        Args:
            query: The original user query
            
        Returns:
            ExpandedQuery with expanded terms
        """
        # Try LLM expansion first
        if self._model is not None:
            try:
                return await self._expand_with_llm(query)
            except Exception as e:
                _log.warning(f"LLM expansion failed: {e}")
        
        # Fallback to rule-based expansion
        if self._use_fallback:
            return self._expand_with_rules(query)
        
        # Return original if nothing else works
        return ExpandedQuery(
            original=query,
            expanded=query,
            terms=self._extract_terms(query),
            synonyms={},
            confidence=0.5,
        )

    async def _expand_with_llm(self, query: str) -> ExpandedQuery:
        """Expand query using local LLM."""
        self._ensure_model_loaded()
        
        if self._model is None:
            raise RuntimeError("Model not loaded")
        
        # Build prompt
        prompt = f"{self.SYSTEM_PROMPT}\n\nQuery: {query}\n\nExpanded:"
        
        # Generate
        result = self._model(
            prompt,
            max_tokens=MAX_TOKENS_BRIEF,
            temperature=self._temperature,
            stop=["\n", "Query:", "Result:"],
        )
        
        expanded = result["choices"][0]["text"].strip()
        
        # Extract terms
        terms = self._extract_terms(expanded)
        
        # Generate synonyms (basic)
        synonyms = self._generate_synonyms(terms)
        
        return ExpandedQuery(
            original=query,
            expanded=expanded,
            terms=terms,
            synonyms=synonyms,
            confidence=0.8,
        )

    def _expand_with_rules(self, query: str) -> ExpandedQuery:
        """
        Expand query using rule-based approach.
        
        Provides basic expansion without LLM.
        """
        terms = self._extract_terms(query)
        
        # Generate synonyms
        synonyms = self._generate_synonyms(terms)
        
        # Build expanded query
        expanded_terms = set(terms)
        for term_syns in synonyms.values():
            expanded_terms.update(term_syns)
        
        expanded = " ".join(sorted(expanded_terms))
        
        return ExpandedQuery(
            original=query,
            expanded=expanded,
            terms=terms,
            synonyms=synonyms,
            confidence=0.6,
        )

    def _extract_terms(self, query: str) -> List[str]:
        """Extract key terms from query."""
        # Lowercase and split
        words = query.lower().split()
        
        # Remove common stop words
        stop_words = {
            "the", "a", "an", "is", "are", "was", "were",
            "to", "of", "in", "for", "on", "at", "by",
            "how", "what", "why", "when", "where", "who",
            "can", "could", "should", "would", "may", "might",
            "do", "does", "did", "have", "has", "had",
            "i", "you", "we", "they", "it", "this", "that",
        }
        
        terms = [w for w in words if w not in stop_words and len(w) > 2]
        
        return list(dict.fromkeys(terms))  # Remove duplicates, preserve order

    def _generate_synonyms(self, terms: List[str]) -> Dict[str, List[str]]:
        """Generate synonyms for terms."""
        # Common synonyms dictionary
        synonym_map = {
            "config": ["configure", "setup", "settings", "settings"],
            "auth": ["authentication", "login", "security", "access"],
            "security": ["secure", "protection", "safety"],
            "agent": ["agents", "assistant", "bot"],
            "template": ["templates", "workflow", "workflows"],
            "tool": ["tools", "function", "functions"],
            "search": ["find", "query", "lookup"],
            "run": ["execute", "start", "launch"],
            "install": ["setup", "deploy"],
            "api": ["interface", "endpoint"],
            "prompt": ["prompts", "instruction", "instructions"],
            "memory": ["context", "history"],
            "llm": ["model", "language model"],
            "embedding": ["vector", "embeddings"],
            "rag": ["retrieval", "context"],
            "mcp": ["server", "protocol"],
            "browser": ["web", "automation"],
            "bash": ["shell", "terminal", "command"],
            "python": ["code", "script"],
        }
        
        synonyms = {}
        
        for term in terms:
            term_lower = term.lower()
            
            # Check direct matches
            if term_lower in synonym_map:
                synonyms[term] = synonym_map[term_lower]
            else:
                # Check partial matches
                for key, syns in synonym_map.items():
                    if key in term_lower or term_lower in key:
                        synonyms[term] = syns
                        break
        
        return synonyms

    async def expand_multiple(
        self,
        queries: List[str],
    ) -> List[ExpandedQuery]:
        """
        Expand multiple queries.
        
        Args:
            queries: List of queries to expand
            
        Returns:
            List of ExpandedQuery results
        """
        results = []
        
        for query in queries:
            result = await self.expand(query)
            results.append(result)
        
        return results

    def get_expanded_search_terms(self, query: str) -> List[str]:
        """
        Get a list of search terms for BM25 search.
        
        Combines original terms with synonyms.
        """
        # Run expansion
        expanded = self._expand_with_rules(query)
        
        # Build term list
        terms = list(expanded.terms)
        
        # Add synonyms
        for syns in expanded.synonyms.values():
            terms.extend(syns)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_terms = []
        for term in terms:
            if term not in seen:
                seen.add(term)
                unique_terms.append(term)
        
        return unique_terms

    def is_available(self) -> bool:
        """Check if query expansion is available."""
        try:
            self._ensure_model_loaded()
            return self._model is not None or self._use_fallback
        except Exception:
            return False

    def get_model_info(self) -> Dict[str, Any]:
        """Get information about the loaded model."""
        self._ensure_model_loaded()
        
        return {
            "llm_loaded": self._model is not None,
            "model_name": self._model_name,
            "fallback_enabled": self._use_fallback,
        }

    def unload(self) -> None:
        """Unload the model to free memory."""
        with self._lock:
            self._model = None
            _log.info("Query expansion model unloaded")


# Singleton instance
_expander: Optional[QueryExpander] = None
_expander_lock = threading.Lock()


def get_query_expander(**kwargs) -> QueryExpander:
    """Get singleton QueryExpander instance."""
    global _expander
    
    with _expander_lock:
        if _expander is None:
            _expander = QueryExpander(**kwargs)
        return _expander