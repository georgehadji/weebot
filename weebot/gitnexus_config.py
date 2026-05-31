"""
GitNexus Configuration for Weebot

This module provides configuration management for GitNexus integration,
including model routing, provider settings, and cost optimization parameters.
"""
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
import os
from pathlib import Path


@dataclass
class GitNexusConfig:
    """
    Configuration for GitNexus integration with Weebot.
    """
    # GitNexus executable settings
    gitnexus_path: str = "npx"
    gitnexus_args: List[str] = field(default_factory=lambda: ["-y", "gitnexus@latest"])
    
    # Indexing settings
    skip_embeddings: bool = False
    force_reindex: bool = False
    max_workers: int = 4
    
    # Analysis settings
    max_depth: int = 3
    min_confidence: float = 0.7
    
    # Performance settings
    timeout: int = 300  # Request timeout in seconds
    max_retries: int = 3
    
    # Caching settings
    enable_caching: bool = True
    cache_ttl_seconds: int = 3600  # 1 hour default
    
    # Repository settings
    default_repo_path: str = "."
    auto_analyze_on_startup: bool = True
    
    # Analysis preferences
    analysis_modes: List[str] = field(default_factory=lambda: [
        "structure", "parsing", "resolution", "clustering", "processes"
    ])
    
    def __post_init__(self):
        """Load settings from environment variables after initialization."""
        self.gitnexus_path = os.getenv("GITNEXUS_PATH", self.gitnexus_path)
        self.skip_embeddings = os.getenv("GITNEXUS_SKIP_EMBEDDINGS", str(self.skip_embeddings)).lower() == "true"
        self.force_reindex = os.getenv("GITNEXUS_FORCE_REINDEX", str(self.force_reindex)).lower() == "true"
        self.max_depth = int(os.getenv("GITNEXUS_MAX_DEPTH", str(self.max_depth)))
        self.min_confidence = float(os.getenv("GITNEXUS_MIN_CONFIDENCE", str(self.min_confidence)))
        self.timeout = int(os.getenv("GITNEXUS_TIMEOUT", str(self.timeout)))
        self.max_retries = int(os.getenv("GITNEXUS_MAX_RETRIES", str(self.max_retries)))
        self.enable_caching = os.getenv("GITNEXUS_ENABLE_CACHING", str(self.enable_caching)).lower() == "true"
        self.cache_ttl_seconds = int(os.getenv("GITNEXUS_CACHE_TTL", str(self.cache_ttl_seconds)))
        self.default_repo_path = os.getenv("GITNEXUS_DEFAULT_REPO_PATH", self.default_repo_path)
        self.auto_analyze_on_startup = os.getenv("GITNEXUS_AUTO_ANALYZE", str(self.auto_analyze_on_startup)).lower() == "true"


# Global configuration instance
_gitnexus_config: Optional[GitNexusConfig] = None


def get_gitnexus_config() -> GitNexusConfig:
    """
    Get the global GitNexus configuration instance.
    
    Returns:
        GitNexusConfig instance
    """
    global _gitnexus_config
    if _gitnexus_config is None:
        _gitnexus_config = GitNexusConfig()
    return _gitnexus_config