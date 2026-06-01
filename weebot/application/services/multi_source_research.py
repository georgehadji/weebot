"""
Multi-Source Research System for Weebot

This module provides capabilities for conducting research across multiple sources
and synthesizing information from various inputs.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Protocol
from datetime import datetime
import aiohttp
import logging
from abc import ABC, abstractmethod
from urllib.parse import urlparse, urljoin
import re

if TYPE_CHECKING:
    from weebot.infrastructure.external_service_integration import ServiceRegistry
    from weebot.tools.web_search import WebSearchTool
    from weebot.tools.advanced_browser import AdvancedBrowserTool

from weebot.tools.base import ToolResult


class ResearchSourceType(Enum):
    """Types of research sources."""
    WEB_SEARCH = "web_search"
    ACADEMIC_DATABASE = "academic_database"
    NEWS_API = "news_api"
    SOCIAL_MEDIA = "social_media"
    WIKIPEDIA = "wikipedia"
    DOCUMENT = "document"
    DATABASE = "database"
    CUSTOM_API = "custom_api"


class ResearchQuality(Enum):
    """Quality rating for research sources."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


@dataclass
class ResearchSource:
    """Information about a research source."""
    name: str
    source_type: ResearchSourceType
    url: str
    quality: ResearchQuality
    reliability_score: float  # 0.0 to 1.0
    last_accessed: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ResearchResult:
    """Result of a research operation."""
    query: str
    sources_used: List[ResearchSource]
    results: List[Dict[str, Any]]  # List of result items from various sources
    summary: str
    confidence_score: float  # 0.0 to 1.0
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


class ResearchProvider(ABC):
    """Abstract base class for research providers."""
    
    @abstractmethod
    async def search(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """Search for information using this provider."""
        pass
    
    @abstractmethod
    def get_source_info(self) -> ResearchSource:
        """Get information about this research source."""
        pass


class WebSearchResearchProvider(ResearchProvider):
    """Research provider using web search tools."""
    
    def __init__(self, web_search_tool: WebSearchTool):
        self.web_search_tool = web_search_tool
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    async def search(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """Search using web search tools."""
        try:
            # Use the existing web search tool
            result = await self.web_search_tool.execute(query=query, num_results=max_results)
            
            if result.tool_error:
                self.logger.error(f"Web search tool error: {result.content}")
                return []
            
            # Parse the search results
            search_results = []
            try:
                # The result content might be a string representation of search results
                # We'll need to parse it appropriately
                if isinstance(result.content, str):
                    # Simple parsing of search results - in a real implementation,
                    # this would be more sophisticated
                    lines = result.content.split('\n')
                    for line in lines:
                        if line.strip() and line.startswith(('http', 'www')):
                            # This is a simplified parsing - real implementation would be more robust
                            search_results.append({
                                "title": f"Result from {line[:50]}...",
                                "url": line.strip(),
                                "snippet": "Web search result snippet",
                                "source": "web_search"
                            })
                elif isinstance(result.content, list):
                    # If the content is already a list of results
                    search_results = result.content
                else:
                    # If it's a dict or other format
                    search_results = [result.content] if result.content else []
                    
            except Exception as e:
                self.logger.error(f"Error parsing web search results: {e}")
                return []
            
            return search_results[:max_results]
            
        except Exception as e:
            self.logger.error(f"Error in web search: {e}")
            return []
    
    def get_source_info(self) -> ResearchSource:
        """Get information about this research source."""
        return ResearchSource(
            name="Web Search Provider",
            source_type=ResearchSourceType.WEB_SEARCH,
            url="various",
            quality=ResearchQuality.MEDIUM,
            reliability_score=0.7,
            metadata={"tool_used": "WebSearchTool"}
        )


class WikipediaResearchProvider(ResearchProvider):
    """Research provider using Wikipedia API."""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    async def initialize(self):
        """Initialize the HTTP session with timeout."""
        if not self.session:
            timeout = aiohttp.ClientTimeout(total=30.0, connect=10.0)
            self.session = aiohttp.ClientSession(timeout=timeout)
    
    async def search(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """Search Wikipedia for information."""
        await self.initialize()
        
        try:
            # Format the Wikipedia API URL
            search_url = "https://en.wikipedia.org/api/rest_v1/page/summary/"
            search_url += query.replace(" ", "_")
            
            async with self.session.get(search_url) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    return [{
                        "title": data.get("title", query),
                        "url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
                        "snippet": data.get("extract", ""),
                        "source": "wikipedia",
                        "thumbnail": data.get("thumbnail", {}).get("source") if data.get("thumbnail") else None
                    }]
                elif response.status == 404:
                    # Page not found, try search API
                    search_url = "https://en.wikipedia.org/w/api.php"
                    params = {
                        "action": "query",
                        "format": "json",
                        "list": "search",
                        "srsearch": query,
                        "srlimit": max_results
                    }
                    
                    async with self.session.get(search_url, params=params) as search_response:
                        if search_response.status == 200:
                            search_data = await search_response.json()
                            
                            results = []
                            query_data = search_data.get("query") or {}
                            for item in query_data.get("search", [])[:max_results]:
                                results.append({
                                    "title": item["title"],
                                    "url": f"https://en.wikipedia.org/wiki/{item['title'].replace(' ', '_')}",
                                    "snippet": item["snippet"].replace("<span class=\"searchmatch\">", "").replace("</span>", ""),
                                    "source": "wikipedia"
                                })
                            
                            return results
                        else:
                            self.logger.warning(f"Wikipedia search failed with status {search_response.status}")
                            return []
                else:
                    self.logger.warning(f"Wikipedia request failed with status {response.status}")
                    return []
                    
        except Exception as e:
            self.logger.error(f"Error searching Wikipedia: {e}")
            return []
    
    def get_source_info(self) -> ResearchSource:
        """Get information about this research source."""
        return ResearchSource(
            name="Wikipedia Research Provider",
            source_type=ResearchSourceType.WIKIPEDIA,
            url="https://wikipedia.org",
            quality=ResearchQuality.HIGH,
            reliability_score=0.85,
            metadata={"api_type": "rest_api"}
        )
    
    async def close(self):
        """Close the HTTP session."""
        if self.session:
            await self.session.close()


class DocumentResearchProvider(ResearchProvider):
    """Research provider for document-based research."""
    
    def __init__(self, document_paths: List[str]):
        self.document_paths = document_paths
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    async def search(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """Search within documents."""
        # This is a simplified implementation - in reality, this would involve
        # more sophisticated document parsing and search algorithms
        results = []
        
        for doc_path in self.document_paths:
            try:
                # Simulate document search
                # In a real implementation, this would parse the document and search for relevant content
                results.append({
                    "title": f"Document: {doc_path}",
                    "url": doc_path,
                    "snippet": f"Relevant information about '{query}' found in document",
                    "source": "document",
                    "confidence": 0.8
                })
            except Exception as e:
                self.logger.error(f"Error searching document {doc_path}: {e}")
        
        return results[:max_results]
    
    def get_source_info(self) -> ResearchSource:
        """Get information about this research source."""
        return ResearchSource(
            name="Document Research Provider",
            source_type=ResearchSourceType.DOCUMENT,
            url="local_documents",
            quality=ResearchQuality.HIGH,
            reliability_score=0.9,
            metadata={"document_count": len(self.document_paths)}
        )


class MultiSourceResearchEngine:
    """Engine for conducting research across multiple sources."""
    
    def __init__(
        self,
        web_search_tool: Optional[WebSearchTool] = None,
        browser_tool: Optional[AdvancedBrowserTool] = None,
        service_registry: Optional[ServiceRegistry] = None
    ):
        self.providers: List[ResearchProvider] = []
        self.web_search_tool = web_search_tool
        self.browser_tool = browser_tool
        self.service_registry = service_registry
        self.logger = logging.getLogger(f"{__name__}.MultiSourceResearchEngine")
        
        # Add default providers
        if web_search_tool:
            self.providers.append(WebSearchResearchProvider(web_search_tool))
        
        self.wikipedia_provider = WikipediaResearchProvider()
        self.providers.append(self.wikipedia_provider)
    
    async def add_provider(self, provider: ResearchProvider):
        """Add a research provider to the engine."""
        self.providers.append(provider)
    
    async def remove_provider(self, provider_type: ResearchSourceType):
        """Remove a research provider by type."""
        self.providers = [p for p in self.providers if p.get_source_info().source_type != provider_type]
    
    async def conduct_research(
        self,
        query: str,
        max_sources: int = 5,
        max_results_per_source: int = 5,
        quality_threshold: float = 0.5
    ) -> ResearchResult:
        """Conduct research across multiple sources."""
        all_results = []
        sources_used = []
        
        # Execute searches concurrently across all providers
        search_tasks = []
        for provider in self.providers:
            source_info = provider.get_source_info()
            
            # Only use sources that meet quality threshold
            if source_info.reliability_score >= quality_threshold:
                task = asyncio.create_task(
                    self._search_with_provider(provider, query, max_results_per_source)
                )
                search_tasks.append((provider, task))
        
        # Collect results
        for provider, task in search_tasks:
            try:
                provider_results = await task
                if provider_results:
                    all_results.extend(provider_results)
                    sources_used.append(provider.get_source_info())
            except Exception as e:
                self.logger.error(f"Error with provider {provider.__class__.__name__}: {e}")
                continue
        
        # Sort results by some relevance metric (simplified)
        # In a real implementation, this would use more sophisticated ranking
        sorted_results = sorted(
            all_results,
            key=lambda x: x.get('confidence', x.get('reliability_score', 0.5)),
            reverse=True
        )[:max_sources * max_results_per_source]
        
        # Generate a summary of the research
        summary = await self._generate_summary(query, sorted_results)
        
        # Calculate overall confidence score
        if sorted_results:
            avg_confidence = sum(
                r.get('confidence', r.get('reliability_score', 0.5)) for r in sorted_results
            ) / len(sorted_results)
        else:
            avg_confidence = 0.0
        
        return ResearchResult(
            query=query,
            sources_used=sources_used,
            results=sorted_results,
            summary=summary,
            confidence_score=avg_confidence,
            timestamp=datetime.now()
        )
    
    async def _search_with_provider(
        self,
        provider: ResearchProvider,
        query: str,
        max_results: int
    ) -> List[Dict[str, Any]]:
        """Execute search with a specific provider."""
        try:
            results = await provider.search(query, max_results)
            
            # Add source information to each result
            for result in results:
                result["provider"] = provider.__class__.__name__
            
            return results
        except Exception as e:
            self.logger.error(f"Error searching with provider {provider.__class__.__name__}: {e}")
            return []
    
    async def _generate_summary(self, query: str, results: List[Dict[str, Any]]) -> str:
        """Generate a summary of the research results."""
        if not results:
            return f"No results found for query: {query}"
        
        # Create a simple summary - in a real implementation, this would use
        # AI to generate a more sophisticated summary
        titles = [r.get("title", "Untitled") for r in results[:3]]  # Top 3 results
        summary = f"Found {len(results)} results for '{query}'. Top sources include: {', '.join(titles)}"
        
        return summary
    
    async def get_research_sources(self) -> List[ResearchSource]:
        """Get information about all available research sources."""
        sources = []
        for provider in self.providers:
            sources.append(provider.get_source_info())
        return sources
    
    async def close(self):
        """Close resources used by the research engine."""
        if hasattr(self.wikipedia_provider, 'close'):
            await self.wikipedia_provider.close()


class ResearchTool:
    """Tool for conducting multi-source research."""
    
    def __init__(self, research_engine: MultiSourceResearchEngine):
        self.research_engine = research_engine
        self.logger = logging.getLogger(f"{__name__}.ResearchTool")
    
    async def conduct_research(
        self,
        query: str,
        max_sources: int = 5,
        max_results_per_source: int = 5
    ) -> ToolResult:
        """Conduct research and return results."""
        try:
            result = await self.research_engine.conduct_research(
                query=query,
                max_sources=max_sources,
                max_results_per_source=max_results_per_source
            )
            
            # Format the result for the tool
            formatted_result = {
                "query": result.query,
                "summary": result.summary,
                "confidence_score": result.confidence_score,
                "sources_used": [s.name for s in result.sources_used],
                "results_count": len(result.results),
                "results": result.results[:10]  # Limit to first 10 results
            }
            
            return ToolResult(
                content=json.dumps(formatted_result, indent=2, default=str),
                tool_error=False
            )
        except Exception as e:
            self.logger.error(f"Error conducting research: {e}")
            return ToolResult(
                content=f"Error conducting research: {str(e)}",
                tool_error=True
            )
    
    def to_param(self) -> Dict[str, Any]:
        """Convert to parameter format for tool registration."""
        return {
            "type": "function",
            "function": {
                "name": "conduct_research",
                "description": "Conduct multi-source research on a topic",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The research query or topic"
                        },
                        "max_sources": {
                            "type": "integer",
                            "description": "Maximum number of sources to use (default: 5)",
                            "default": 5
                        },
                        "max_results_per_source": {
                            "type": "integer",
                            "description": "Maximum results per source (default: 5)",
                            "default": 5
                        }
                    },
                    "required": ["query"]
                }
            }
        }


# Example usage
if __name__ == "__main__":
    import asyncio
    
    async def example():
        # This example would require actual tool instances
        # For demonstration, we'll create a simplified version
        
        # Create a basic research engine
        research_engine = MultiSourceResearchEngine()
        
        # Conduct a sample research
        print("Conducting sample research...")
        sample_result = await research_engine.conduct_research(
            query="Artificial Intelligence developments in 2026",
            max_sources=3,
            max_results_per_source=3
        )
        
        print(f"Query: {sample_result.query}")
        print(f"Summary: {sample_result.summary}")
        print(f"Confidence: {sample_result.confidence_score:.2f}")
        print(f"Sources used: {[s.name for s in sample_result.sources_used]}")
        print(f"Number of results: {len(sample_result.results)}")
        
        # Show first few results
        for i, result in enumerate(sample_result.results[:3]):
            print(f"  Result {i+1}: {result.get('title', 'No title')}")
        
        # Close resources
        await research_engine.close()
        print("Research engine closed")
    
    # Note: The full example would require actual tool instances
    # which would need to be properly initialized
    asyncio.run(example())