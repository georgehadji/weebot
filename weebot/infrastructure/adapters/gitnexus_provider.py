"""
GitNexus Integration for Weebot - Code Intelligence & Knowledge Graph

This module provides integration between GitNexus and Weebot
to enable codebase-aware AI interactions, intelligent context provision,
and architectural understanding for AI agents.
"""
import asyncio
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass
from weebot.domain.models.task_type import TaskType

logger = logging.getLogger(__name__)


@dataclass
class GitNexusConfig:
    """Configuration for GitNexus integration."""
    # GitNexus executable path
    gitnexus_path: str = "npx"
    gitnexus_args: List[str] = None
    
    # Indexing settings
    skip_embeddings: bool = False
    force_reindex: bool = False
    
    # Analysis settings
    max_depth: int = 3
    min_confidence: float = 0.7
    
    def __post_init__(self):
        if self.gitnexus_args is None:
            self.gitnexus_args = ["-y", "gitnexus@latest"]

    @classmethod
    def from_env(cls) -> 'GitNexusConfig':
        """Create configuration from environment variables."""
        return cls(
            gitnexus_path=os.getenv("GITNEXUS_PATH", "npx"),
            skip_embeddings=os.getenv("GITNEXUS_SKIP_EMBEDDINGS", "false").lower() == "true",
            force_reindex=os.getenv("GITNEXUS_FORCE_REINDEX", "false").lower() == "true",
            max_depth=int(os.getenv("GITNEXUS_MAX_DEPTH", "3")),
            min_confidence=float(os.getenv("GITNEXUS_MIN_CONFIDENCE", "0.7"))
        )


class GitNexusProvider:
    """
    GitNexus provider that enables codebase-aware AI interactions.
    
    Provides intelligent context about code structure, dependencies, 
    execution flows, and architectural relationships.
    """
    
    def __init__(self, config: Optional[GitNexusConfig] = None):
        self.config = config or GitNexusConfig.from_env()
        self._available = self._check_availability()
        self._repo_analyzed = False
        
    def _check_availability(self) -> bool:
        """Check if GitNexus is available in the system."""
        try:
            result = subprocess.run(
                [self.config.gitnexus_path, "--version"], 
                capture_output=True, 
                text=True, 
                timeout=10
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
    
    async def is_available(self) -> bool:
        """Check if GitNexus is available asynchronously."""
        return self._available
    
    async def analyze_repository(self, repo_path: str = ".") -> bool:
        """
        Analyze the repository and build the knowledge graph.
        
        Args:
            repo_path: Path to the repository to analyze (default: current directory)
            
        Returns:
            True if analysis was successful, False otherwise
        """
        if not self._available:
            logger.warning("GitNexus is not available. Skipping repository analysis.")
            return False
        
        try:
            cmd = self.config.gitnexus_args + ["analyze"]
            if self.config.skip_embeddings:
                cmd.append("--skip-embeddings")
            if self.config.force_reindex:
                cmd.append("--force")
            
            # Run gitnexus analyze in the specified directory
            proc = await asyncio.create_subprocess_exec(
                self.config.gitnexus_path,
                *cmd,
                cwd=repo_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await proc.communicate()
            
            if proc.returncode == 0:
                logger.info(f"GitNexus analysis completed for {repo_path}")
                self._repo_analyzed = True
                return True
            else:
                logger.error(f"GitNexus analysis failed: {stderr.decode()}")
                return False
                
        except Exception as e:
            logger.error(f"Error during GitNexus analysis: {e}")
            return False
    
    async def query_codebase(self, query: str, repo_path: str = ".") -> Dict[str, Any]:
        """
        Query the codebase knowledge graph for relevant information.
        
        Args:
            query: Natural language query about the codebase
            repo_path: Path to the repository (default: current directory)
            
        Returns:
            Dictionary with query results including processes, symbols, and definitions
        """
        if not self._available:
            return {"error": "GitNexus is not available"}
        
        if not self._repo_analyzed:
            await self.analyze_repository(repo_path)
        
        try:
            # Use GitNexus query tool via subprocess
            cmd = self.config.gitnexus_args + [
                "tool", "query", 
                "--query", query,
                "--json"  # Get structured output
            ]
            
            proc = await asyncio.create_subprocess_exec(
                self.config.gitnexus_path,
                *cmd,
                cwd=repo_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await proc.communicate()
            
            if proc.returncode == 0:
                try:
                    result = json.loads(stdout.decode())
                    return result
                except json.JSONDecodeError:
                    # If JSON parsing fails, return the raw output
                    return {
                        "raw_output": stdout.decode(),
                        "error": "Could not parse GitNexus output as JSON"
                    }
            else:
                return {
                    "error": f"GitNexus query failed: {stderr.decode()}",
                    "return_code": proc.returncode
                }
                
        except Exception as e:
            logger.error(f"Error querying GitNexus: {e}")
            return {"error": f"GitNexus query error: {str(e)}"}
    
    async def get_symbol_context(self, symbol_name: str, repo_path: str = ".") -> Dict[str, Any]:
        """
        Get comprehensive context about a specific symbol (function, class, etc.).
        
        Args:
            symbol_name: Name of the symbol to get context for
            repo_path: Path to the repository (default: current directory)
            
        Returns:
            Dictionary with symbol context including references, dependencies, and processes
        """
        if not self._available:
            return {"error": "GitNexus is not available"}
        
        if not self._repo_analyzed:
            await self.analyze_repository(repo_path)
        
        try:
            # Use GitNexus context tool
            cmd = self.config.gitnexus_args + [
                "tool", "context",
                "--name", symbol_name,
                "--json"
            ]
            
            proc = await asyncio.create_subprocess_exec(
                self.config.gitnexus_path,
                *cmd,
                cwd=repo_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await proc.communicate()
            
            if proc.returncode == 0:
                try:
                    result = json.loads(stdout.decode())
                    return result
                except json.JSONDecodeError:
                    return {
                        "raw_output": stdout.decode(),
                        "error": "Could not parse GitNexus output as JSON"
                    }
            else:
                return {
                    "error": f"GitNexus context query failed: {stderr.decode()}",
                    "return_code": proc.returncode
                }
                
        except Exception as e:
            logger.error(f"Error getting symbol context from GitNexus: {e}")
            return {"error": f"GitNexus context error: {str(e)}"}
    
    async def analyze_impact(self, target: str, direction: str = "upstream", repo_path: str = ".") -> Dict[str, Any]:
        """
        Analyze the impact of changing a specific target (function, class, etc.).
        
        Args:
            target: Name of the target to analyze impact for
            direction: Direction of impact ("upstream" for dependents, "downstream" for dependencies)
            repo_path: Path to the repository (default: current directory)
            
        Returns:
            Dictionary with impact analysis results
        """
        if not self._available:
            return {"error": "GitNexus is not available"}
        
        if not self._repo_analyzed:
            await self.analyze_repository(repo_path)
        
        try:
            # Use GitNexus impact tool
            cmd = self.config.gitnexus_args + [
                "tool", "impact",
                "--target", target,
                "--direction", direction,
                "--max-depth", str(self.config.max_depth),
                "--min-confidence", str(self.config.min_confidence),
                "--json"
            ]
            
            proc = await asyncio.create_subprocess_exec(
                self.config.gitnexus_path,
                *cmd,
                cwd=repo_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await proc.communicate()
            
            if proc.returncode == 0:
                try:
                    result = json.loads(stdout.decode())
                    return result
                except json.JSONDecodeError:
                    return {
                        "raw_output": stdout.decode(),
                        "error": "Could not parse GitNexus output as JSON"
                    }
            else:
                return {
                    "error": f"GitNexus impact analysis failed: {stderr.decode()}",
                    "return_code": proc.returncode
                }
                
        except Exception as e:
            logger.error(f"Error analyzing impact with GitNexus: {e}")
            return {"error": f"GitNexus impact analysis error: {str(e)}"}
    
    async def detect_changes(self, task_type: TaskType, scope: str = "unstaged", repo_path: str = ".") -> Dict[str, Any]:
        """
        Detect changes in the repository and analyze their impact.
        
        Args:
            task_type: Type of task being performed (affects analysis depth)
            scope: Scope of changes ("unstaged", "staged", "all", "compare")
            repo_path: Path to the repository (default: current directory)
            
        Returns:
            Dictionary with change detection results
        """
        if not self._available:
            return {"error": "GitNexus is not available"}
        
        if not self._repo_analyzed:
            await self.analyze_repository(repo_path)
        
        try:
            # Use GitNexus detect_changes tool
            cmd = self.config.gitnexus_args + [
                "tool", "detect_changes",
                "--scope", scope,
                "--json"
            ]
            
            proc = await asyncio.create_subprocess_exec(
                self.config.gitnexus_path,
                *cmd,
                cwd=repo_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await proc.communicate()
            
            if proc.returncode == 0:
                try:
                    result = json.loads(stdout.decode())
                    
                    # For debugging tasks, also analyze impact of changes
                    if task_type == TaskType.DEBUGGING and "changed_symbols" in result:
                        impact_analysis = {}
                        changed_symbols = result.get("changed_symbols", [])
                        for symbol in changed_symbols[:5]:  # Limit to first 5 symbols
                            if isinstance(symbol, dict) and "name" in symbol:
                                impact = await self.analyze_impact(
                                    symbol["name"], 
                                    "upstream", 
                                    repo_path
                                )
                                if "error" not in impact:
                                    impact_analysis[symbol["name"]] = impact
                        result["impact_analysis"] = impact_analysis
                    
                    return result
                except json.JSONDecodeError:
                    return {
                        "raw_output": stdout.decode(),
                        "error": "Could not parse GitNexus output as JSON"
                    }
            else:
                return {
                    "error": f"GitNexus change detection failed: {stderr.decode()}",
                    "return_code": proc.returncode
                }
                
        except Exception as e:
            logger.error(f"Error detecting changes with GitNexus: {e}")
            return {"error": f"GitNexus change detection error: {str(e)}"}
    
    async def get_repository_context(self, repo_path: str = ".") -> Dict[str, Any]:
        """
        Get overall repository context and statistics.
        
        Args:
            repo_path: Path to the repository (default: current directory)
            
        Returns:
            Dictionary with repository context information
        """
        if not self._available:
            return {"error": "GitNexus is not available"}
        
        if not self._repo_analyzed:
            await self.analyze_repository(repo_path)
        
        try:
            # Use GitNexus list_repos tool to get context
            cmd = self.config.gitnexus_args + [
                "tool", "list_repos",
                "--json"
            ]
            
            proc = await asyncio.create_subprocess_exec(
                self.config.gitnexus_path,
                *cmd,
                cwd=repo_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await proc.communicate()
            
            if proc.returncode == 0:
                try:
                    result = json.loads(stdout.decode())
                    return result
                except json.JSONDecodeError:
                    return {
                        "raw_output": stdout.decode(),
                        "error": "Could not parse GitNexus output as JSON"
                    }
            else:
                return {
                    "error": f"GitNexus repository context failed: {stderr.decode()}",
                    "return_code": proc.returncode
                }
                
        except Exception as e:
            logger.error(f"Error getting repository context from GitNexus: {e}")
            return {"error": f"GitNexus repository context error: {str(e)}"}


# Global GitNexus provider instance
_gitnexus_provider: Optional[GitNexusProvider] = None


def get_gitnexus_provider() -> GitNexusProvider:
    """
    Get the global GitNexus provider instance.
    
    Returns:
        GitNexusProvider instance
    """
    global _gitnexus_provider
    if _gitnexus_provider is None:
        _gitnexus_provider = GitNexusProvider()
    return _gitnexus_provider


async def enhance_prompt_with_code_context(
    prompt: str, 
    task_context: Optional[str] = None,
    target_symbol: Optional[str] = None
) -> str:
    """
    Enhance a prompt with relevant code context from GitNexus.
    
    Args:
        prompt: Original prompt to enhance
        task_context: Context about what task is being performed
        target_symbol: Specific symbol to get context for
        
    Returns:
        Enhanced prompt with code context
    """
    provider = get_gitnexus_provider()
    
    if not await provider.is_available():
        # If GitNexus is not available, return original prompt
        return prompt
    
    context_parts = [prompt]
    
    # Add repository context
    repo_context = await provider.get_repository_context()
    if "error" not in repo_context:
        context_parts.append("\n\nREPOSITORY CONTEXT:")
        context_parts.append(json.dumps(repo_context, indent=2))
    
    # Add specific symbol context if requested
    if target_symbol:
        symbol_context = await provider.get_symbol_context(target_symbol)
        if "error" not in symbol_context:
            context_parts.append(f"\n\nSYMBOL '{target_symbol}' CONTEXT:")
            context_parts.append(json.dumps(symbol_context, indent=2))
    
    # Add query results if task context provided
    if task_context:
        query_results = await provider.query_codebase(task_context)
        if "error" not in query_results:
            context_parts.append(f"\n\nCODEBASE QUERY RESULTS FOR '{task_context}':")
            context_parts.append(json.dumps(query_results, indent=2))
    
    return "\n".join(context_parts)


async def analyze_code_impact(
    target: str,
    direction: str = "upstream",
    repo_path: str = "."
) -> Dict[str, Any]:
    """
    Convenience function to analyze code impact using GitNexus.
    
    Args:
        target: Target to analyze (function, class, etc.)
        direction: Direction of impact ("upstream" or "downstream")
        repo_path: Path to repository
        
    Returns:
        Impact analysis results
    """
    provider = get_gitnexus_provider()
    return await provider.analyze_impact(target, direction, repo_path)


async def detect_repository_changes(
    scope: str = "unstaged",
    repo_path: str = "."
) -> Dict[str, Any]:
    """
    Convenience function to detect repository changes using GitNexus.
    
    Args:
        scope: Scope of changes to detect
        repo_path: Path to repository
        
    Returns:
        Change detection results
    """
    provider = get_gitnexus_provider()
    return await provider.detect_changes(scope, repo_path)