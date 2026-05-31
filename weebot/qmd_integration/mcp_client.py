"""QMD MCP Client - Connect to QMD's MCP Server

Provides a client for interacting with QMD's MCP (Model Context Protocol) server.
This allows weebot to search local document collections using QMD's search capabilities.

Based on QMD's MCP implementation from qmd-main/src/mcp.ts

Features:
- Connect to QMD MCP server (stdio or HTTP)
- Search collections with query expansion
- Vector similarity search
- Full-text BM25 search
- Document retrieval by ID or path
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

_log = logging.getLogger(__name__)


@dataclass
class QMDDocument:
    """A document from QMD search results."""
    docid: str  # e.g., "#abc123"
    file: str
    score: float
    content: Optional[str] = None
    line_number: Optional[int] = None
    collection: Optional[str] = None

    @property
    def doc_id(self) -> str:
        """Get the doc ID without the # prefix."""
        return self.docid.lstrip('#')


@dataclass
class QMDCollection:
    """A QMD collection configuration."""
    name: str
    path: str
    pattern: str
    context: Dict[str, str] = field(default_factory=dict)
    include_by_default: bool = True


@dataclass
class QMDContext:
    """A QMD context definition."""
    path: str
    description: str
    collection: Optional[str] = None


class QMDMCPClient:
    """
    Client for QMD MCP Server.
    
    Connects to QMD's MCP server to search local document collections.
    Supports both stdio and HTTP transport modes.

    Usage:
        client = QMDMCPClient()
        
        # Search with query expansion (recommended)
        results = await client.search("how to configure weebot", collection="notes")
        
        # Vector similarity search
        results = await client.vsearch("security settings")
        
        # Full-text search (BM25)
        results = await client.search_bm25("authentication")
        
        # Get document by ID
        doc = await client.get_document("#abc123")
        
        # List collections
        collections = await client.list_collections()
    """

    # Default QMD paths
    DEFAULT_QMD_PATH = os.path.expanduser("~/.local/bin/qmd")
    DEFAULT_MCP_PORT = 8181

    def __init__(
        self,
        qmd_path: Optional[str] = None,
        transport: str = "http",  # "stdio" or "http"
        port: int = DEFAULT_MCP_PORT,
        host: str = "localhost",
        timeout: float = 30.0,
    ):
        """
        Initialize QMD MCP client.
        
        Args:
            qmd_path: Path to qmd executable (auto-detected if not provided)
            transport: Transport mode ("stdio" or "http")
            port: HTTP port for MCP server
            host: HTTP host for MCP server
            timeout: Request timeout in seconds
        """
        self._qmd_path = qmd_path or self._find_qmd()
        self._transport = transport
        self._port = port
        self._host = host
        self._timeout = timeout
        
        self._process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        
        # Check if QMD is available
        self._qmd_available = self._check_qmd()

    def _find_qmd(self) -> str:
        """Find QMD executable in common locations."""
        possible_paths = [
            os.path.expanduser("~/.local/bin/qmd"),
            os.path.expanduser("~/.bun/bin/qmd"),
            "/usr/local/bin/qmd",
            "/usr/bin/qmd",
            "qmd",  # In PATH
        ]
        
        for path in possible_paths:
            if os.path.exists(path) or self._which(path):
                return path
        
        return "qmd"  # Fallback to PATH

    def _which(self, cmd: str) -> bool:
        """Check if command exists in PATH."""
        try:
            result = subprocess.run(
                ["which", cmd],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _check_qmd(self) -> bool:
        """Check if QMD is available."""
        if not self._qmd_path:
            return False
            
        try:
            result = subprocess.run(
                [self._qmd_path, "status"],
                capture_output=True,
                timeout=10,
            )
            return result.returncode == 0
        except Exception as e:
            _log.warning(f"QMD not available: {e}")
            return False

    async def _start_mcp_stdio(self) -> None:
        """Start QMD MCP server in stdio mode."""
        if self._process is not None:
            return
            
        cmd = [self._qmd_path, "mcp"]
        
        try:
            self._process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            _log.info("QMD MCP server started (stdio)")
        except Exception as e:
            _log.error(f"Failed to start QMD MCP: {e}")
            raise

    async def _call_mcp(self, method: str, params: Optional[Dict] = None) -> Any:
        """Call QMD MCP server method."""
        if self._transport == "http":
            return await self._call_http(method, params)
        else:
            return await self._call_stdio(method, params)

    async def _call_http(self, method: str, params: Optional[Dict] = None) -> Any:
        """Call QMD MCP via HTTP."""
        import aiohttp
        
        url = f"http://{self._host}:{self._port}/mcp"
        
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or {},
        }
        
        try:
            timeout = aiohttp.ClientTimeout(total=self._timeout, connect=10.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload) as resp:
                    result = await resp.json()
                    if "error" in result:
                        raise RuntimeError(f"MCP error: {result['error']}")
                    return result.get("result")
        except aiohttp.ClientConnectorError:
            # Try to start MCP server
            _log.info("Starting QMD MCP server...")
            await self._start_mcp_http()
            # Retry
            timeout = aiohttp.ClientTimeout(total=self._timeout, connect=10.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload) as resp:
                    result = await resp.json()
                    return result.get("result")

    async def _call_stdio(self, method: str, params: Optional[Dict] = None) -> Any:
        """Call QMD MCP via stdio."""
        await self._start_mcp_stdio()
        
        if self._process is None:
            raise RuntimeError("MCP process not started")
        
        request = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or {},
        })
        
        self._process.stdin.write(request + "\n")
        self._process.stdin.flush()
        
        # Read response
        response = self._process.stdout.readline()
        result = json.loads(response)
        
        if "error" in result:
            raise RuntimeError(f"MCP error: {result['error']}")
        
        return result.get("result")

    async def _start_mcp_http(self) -> None:
        """Start QMD MCP server in HTTP mode."""
        cmd = [self._qmd_path, "mcp", "--http", "--port", str(self._port)]
        
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            # Wait for server to start
            await asyncio.sleep(2)
            _log.info(f"QMD MCP server started on port {self._port}")
        except Exception as e:
            _log.error(f"Failed to start QMD MCP HTTP: {e}")
            raise

    # =========================================================================
    # Collection Management
    # =========================================================================

    async def list_collections(self) -> List[QMDCollection]:
        """List all QMD collections."""
        try:
            result = await self._call_mcp("qmd/collection_list")
            
            collections = []
            for name, config in result.get("collections", {}).items():
                collections.append(QMDCollection(
                    name=name,
                    path=config.get("path", ""),
                    pattern=config.get("pattern", "**/*.md"),
                    context=config.get("context", {}),
                    include_by_default=config.get("includeByDefault", True),
                ))
            
            return collections
        except Exception as e:
            _log.warning(f"Failed to list collections: {e}")
            return []

    async def add_collection(
        self,
        path: str,
        name: Optional[str] = None,
        pattern: str = "**/*.md",
    ) -> bool:
        """
        Add a new collection.
        
        Note: Per QMD docs, this should be run manually, not automatically.
        """
        _log.warning("Manual action required: qmd collection add")
        return False

    # =========================================================================
    # Search Methods
    # =========================================================================

    async def search(
        self,
        query: str,
        collection: Optional[str] = None,
        n: int = 10,
        min_score: float = 0.1,
    ) -> List[QMDDocument]:
        """
        Search with query expansion + reranking (recommended).
        
        This is QMD's recommended search method as it uses:
        - Query expansion with local LLM
        - Reciprocal Rank Fusion (RRF)
        - Reranking
        """
        params = {
            "query": query,
            "n": n,
        }
        
        if collection:
            params["collection"] = collection
        
        if min_score > 0:
            params["minScore"] = min_score
        
        try:
            result = await self._call_mcp("qmd/query", params)
            
            documents = []
            for item in result.get("results", []):
                documents.append(QMDDocument(
                    docid=item.get("docid", ""),
                    file=item.get("file", ""),
                    score=item.get("score", 0.0),
                    collection=item.get("collection"),
                ))
            
            return documents
        except Exception as e:
            _log.error(f"Search failed: {e}")
            return []

    async def search_bm25(
        self,
        query: str,
        collection: Optional[str] = None,
        n: int = 10,
    ) -> List[QMDDocument]:
        """
        Full-text keyword search using BM25.
        
        Faster than query search but no reranking.
        """
        params = {
            "query": query,
            "n": n,
        }
        
        if collection:
            params["collection"] = collection
        
        try:
            result = await self._call_mcp("qmd/search", params)
            
            documents = []
            for item in result.get("results", []):
                documents.append(QMDDocument(
                    docid=item.get("docid", ""),
                    file=item.get("file", ""),
                    score=item.get("score", 0.0),
                    collection=item.get("collection"),
                ))
            
            return documents
        except Exception as e:
            _log.error(f"BM25 search failed: {e}")
            return []

    async def vsearch(
        self,
        query: str,
        collection: Optional[str] = None,
        n: int = 10,
    ) -> List[QMDDocument]:
        """
        Vector similarity search.
        
        Uses embeddings for semantic similarity.
        """
        params = {
            "query": query,
            "n": n,
        }
        
        if collection:
            params["collection"] = collection
        
        try:
            result = await self._call_mcp("qmd/vsearch", params)
            
            documents = []
            for item in result.get("results", []):
                documents.append(QMDDocument(
                    docid=item.get("docid", ""),
                    file=item.get("file", ""),
                    score=item.get("score", 0.0),
                    collection=item.get("collection"),
                ))
            
            return documents
        except Exception as e:
            _log.error(f"Vector search failed: {e}")
            return []

    # =========================================================================
    # Document Retrieval
    # =========================================================================

    async def get_document(
        self,
        docid: str,
        full: bool = False,
        line_numbers: bool = False,
    ) -> Optional[QMDDocument]:
        """
        Get document by docid or path.
        
        Args:
            docid: Document ID (with or without # prefix) or file path
            full: Return full content
            line_numbers: Include line numbers
        """
        # Remove # prefix if present
        docid = docid.lstrip('#')
        
        params = {
            "docid": docid,
        }
        
        if full:
            params["full"] = True
        
        if line_numbers:
            params["lineNumbers"] = True
        
        try:
            result = await self._call_mcp("qmd/get", params)
            
            return QMDDocument(
                docid=result.get("docid", ""),
                file=result.get("file", ""),
                score=1.0,
                content=result.get("content"),
                line_number=result.get("line"),
                collection=result.get("collection"),
            )
        except Exception as e:
            _log.error(f"Get document failed: {e}")
            return None

    async def multi_get(
        self,
        docids: Union[str, List[str]],
        max_lines: int = 100,
        max_bytes: int = 10240,
    ) -> List[QMDDocument]:
        """
        Get multiple documents by docids or glob pattern.
        
        Args:
            docids: Comma-separated docids or glob pattern
            max_lines: Maximum lines per file
            max_bytes: Skip files larger than this
        """
        if isinstance(docids, list):
            docids = ", ".join(docids)
        
        params = {
            "pattern": docids,
            "maxLines": max_lines,
            "maxBytes": max_bytes,
        }
        
        try:
            result = await self._call_mcp("qmd/multi_get", params)
            
            documents = []
            for item in result.get("results", []):
                documents.append(QMDDocument(
                    docid=item.get("docid", ""),
                    file=item.get("file", ""),
                    score=1.0,
                    content=item.get("content"),
                    collection=item.get("collection"),
                ))
            
            return documents
        except Exception as e:
            _log.error(f"Multi-get failed: {e}")
            return []

    # =========================================================================
    # Context Management
    # =========================================================================

    async def list_contexts(self) -> List[QMDContext]:
        """List all QMD contexts."""
        try:
            result = await self._call_mcp("qmd/context_list")
            
            contexts = []
            for path, description in result.get("contexts", {}).items():
                # Parse collection from path if qmd:// prefix
                collection = None
                if path.startswith("qmd://"):
                    parts = path[6:].split("/", 1)
                    collection = parts[0] if parts else None
                
                contexts.append(QMDContext(
                    path=path,
                    description=description,
                    collection=collection,
                ))
            
            return contexts
        except Exception as e:
            _log.warning(f"Failed to list contexts: {e}")
            return []

    async def add_context(self, path: str, description: str) -> bool:
        """Add context to a path."""
        _log.warning("Manual action required: qmd context add")
        return False

    # =========================================================================
    # Utility Methods
    # =========================================================================

    async def status(self) -> Dict[str, Any]:
        """Get QMD status."""
        try:
            result = await self._call_mcp("qmd/status")
            return result
        except Exception as e:
            return {"error": str(e)}

    def is_available(self) -> bool:
        """Check if QMD is available."""
        return self._qmd_available

    def close(self) -> None:
        """Close MCP connection."""
        with self._lock:
            if self._process:
                self._process.terminate()
                self._process = None


# Singleton instance
_client: Optional[QMDMCPClient] = None
_client_lock = threading.Lock()


def get_qmd_client(**kwargs) -> QMDMCPClient:
    """Get singleton QMDMCPClient instance."""
    global _client
    
    with _client_lock:
        if _client is None:
            _client = QMDMCPClient(**kwargs)
        return _client