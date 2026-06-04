"""
GitNexus Router - Intelligent Codebase Analysis & Context Provision

This module provides intelligent routing between different GitNexus analysis modes
based on the type of task and required depth of analysis.
"""
import asyncio
import logging
from enum import Enum
from typing import Dict, Any, Optional, List
from pathlib import Path

from .gitnexus_provider import GitNexusProvider, get_gitnexus_provider
from .gitnexus_config import GitNexusConfig, get_gitnexus_config
from weebot.domain.models.task_type import TaskType

logger = logging.getLogger(__name__)


class AnalysisMode(Enum):
    """Different modes of codebase analysis."""
    QUICK = "quick"          # Fast analysis, surface-level
    DEEP = "deep"            # Thorough analysis, full context
    IMPACT = "impact"        # Impact-focused analysis
    STRUCTURAL = "structural"  # Structure-focused analysis
    SEARCH = "search"        # Search-focused analysis


class GitNexusRouter:
    """
    Intelligent router for GitNexus analysis modes.
    
    Selects the optimal analysis approach based on task type, 
    complexity, and required depth of understanding.
    """
    
    def __init__(self, config: Optional[GitNexusConfig] = None):
        self.config = config or get_gitnexus_config()
        self.provider = get_gitnexus_provider()
        
        # Define analysis preferences for different task types
        self.analysis_preferences = {
            TaskType.CODE_GENERATION: AnalysisMode.SEARCH,
            TaskType.CODE_REVIEW: AnalysisMode.STRUCTURAL,
            TaskType.DEBUGGING: AnalysisMode.IMPACT,
            TaskType.ARCHITECTURE: AnalysisMode.DEEP,
            TaskType.DOCUMENTATION: AnalysisMode.QUICK,
            TaskType.ANALYSIS: AnalysisMode.DEEP,
            TaskType.CREATIVE: AnalysisMode.QUICK,
            TaskType.CHAT: AnalysisMode.QUICK,
        }
    
    def select_analysis_mode(self, task_type: TaskType, 
                           complexity: str = "medium") -> AnalysisMode:
        """
        Select the appropriate analysis mode based on task type and complexity.
        
        Args:
            task_type: Type of task being performed
            complexity: Complexity level ("low", "medium", "high")
            
        Returns:
            AnalysisMode enum value
        """
        base_mode = self.analysis_preferences.get(task_type, AnalysisMode.QUICK)
        
        # Adjust for complexity
        if complexity == "high" and base_mode in [AnalysisMode.QUICK, AnalysisMode.SEARCH]:
            return AnalysisMode.DEEP
        elif complexity == "low" and base_mode in [AnalysisMode.DEEP, AnalysisMode.IMPACT]:
            return AnalysisMode.QUICK
        
        return base_mode
    
    async def analyze_codebase(self, 
                              query: str, 
                              task_type: TaskType,
                              repo_path: str = ".",
                              complexity: str = "medium") -> Dict[str, Any]:
        """
        Perform intelligent codebase analysis based on task requirements.
        
        Args:
            query: Natural language query about the codebase
            task_type: Type of task being performed
            repo_path: Path to repository (default: current directory)
            complexity: Complexity level ("low", "medium", "high")
            
        Returns:
            Dictionary with analysis results
        """
        if not await self.provider.is_available():
            return {
                "error": "GitNexus is not available",
                "fallback": "Proceeding with standard analysis"
            }
        
        analysis_mode = self.select_analysis_mode(task_type, complexity)
        
        try:
            if analysis_mode == AnalysisMode.SEARCH:
                # Use search-focused analysis for code generation/documentation tasks
                return await self._perform_search_analysis(query, repo_path)
            elif analysis_mode == AnalysisMode.STRUCTURAL:
                # Use structural analysis for code review tasks
                return await self._perform_structural_analysis(query, repo_path)
            elif analysis_mode == AnalysisMode.IMPACT:
                # Use impact analysis for debugging tasks
                return await self._perform_impact_analysis(query, repo_path)
            elif analysis_mode == AnalysisMode.DEEP:
                # Use deep analysis for architecture/analysis tasks
                return await self._perform_deep_analysis(query, repo_path)
            else:
                # Use quick analysis for chat/creative tasks
                return await self._perform_quick_analysis(query, repo_path)
                
        except Exception as e:
            logger.error(f"GitNexus analysis failed: {e}")
            return {
                "error": f"GitNexus analysis failed: {str(e)}",
                "fallback": "Proceeding with standard analysis"
            }
    
    async def _perform_search_analysis(self, query: str, repo_path: str) -> Dict[str, Any]:
        """Perform search-focused analysis."""
        return await self.provider.query_codebase(query, repo_path)
    
    async def _perform_structural_analysis(self, query: str, repo_path: str) -> Dict[str, Any]:
        """Perform structural analysis focusing on code relationships."""
        # First get search results
        search_results = await self.provider.query_codebase(query, repo_path)
        
        # Then get structural context for key symbols
        structural_context = {}
        if "process_symbols" in search_results:
            for symbol in search_results["process_symbols"][:5]:  # Limit to top 5
                if "name" in symbol:
                    context = await self.provider.get_symbol_context(symbol["name"], repo_path)
                    if "error" not in context:
                        structural_context[symbol["name"]] = context
        
        return {
            "search_results": search_results,
            "structural_context": structural_context
        }
    
    async def _perform_impact_analysis(self, query: str, repo_path: str) -> Dict[str, Any]:
        """Perform impact-focused analysis."""
        # Try to identify specific targets from the query
        # This is a simplified approach - in practice, you'd use NLP to extract targets
        import re
        
        # Look for potential function/class names in the query
        potential_targets = re.findall(r'\b([A-Za-z_][A-Za-z0-9_]*)\b', query)
        
        impact_results = {}
        for target in potential_targets[:3]:  # Limit to top 3 potential targets
            impact = await self.provider.analyze_impact(target, "upstream", repo_path)
            if "error" not in impact:
                impact_results[target] = impact
        
        return {
            "query_analysis": await self.provider.query_codebase(query, repo_path),
            "impact_analysis": impact_results
        }
    
    async def _perform_deep_analysis(self, query: str, repo_path: str) -> Dict[str, Any]:
        """Perform deep analysis with comprehensive context."""
        # Get search results
        search_results = await self.provider.query_codebase(query, repo_path)
        
        # Get repository context
        repo_context = await self.provider.get_repository_context(repo_path)
        
        # Get structural context for key elements
        structural_context = {}
        if "process_symbols" in search_results:
            for symbol in search_results["process_symbols"][:3]:  # Limit to top 3
                if "name" in symbol:
                    context = await self.provider.get_symbol_context(symbol["name"], repo_path)
                    if "error" not in context:
                        structural_context[symbol["name"]] = context
        
        # If this looks like a change request, also do impact analysis
        change_indicators = ["change", "modify", "update", "fix", "refactor", "improve"]
        if any(indicator in query.lower() for indicator in change_indicators):
            # Extract potential targets and analyze impact
            import re
            potential_targets = re.findall(r'\b([A-Za-z_][A-Za-z0-9_]*)\b', query)
            impact_results = {}
            for target in potential_targets[:2]:
                impact = await self.provider.analyze_impact(target, "upstream", repo_path)
                if "error" not in impact:
                    impact_results[target] = impact
        else:
            impact_results = {}
        
        return {
            "search_results": search_results,
            "repository_context": repo_context,
            "structural_context": structural_context,
            "impact_analysis": impact_results if impact_results else None
        }
    
    async def _perform_quick_analysis(self, query: str, repo_path: str) -> Dict[str, Any]:
        """Perform quick analysis with minimal context."""
        return await self.provider.query_codebase(query, repo_path)
    
    async def get_symbol_context(self, 
                                symbol_name: str, 
                                task_type: TaskType,
                                repo_path: str = ".") -> Dict[str, Any]:
        """
        Get context for a specific symbol with task-appropriate depth.
        
        Args:
            symbol_name: Name of the symbol to get context for
            task_type: Type of task being performed
            repo_path: Path to repository (default: current directory)
            
        Returns:
            Dictionary with symbol context
        """
        if not await self.provider.is_available():
            return {"error": "GitNexus is not available"}
        
        analysis_mode = self.select_analysis_mode(task_type)
        
        try:
            if analysis_mode in [AnalysisMode.DEEP, AnalysisMode.STRUCTURAL, AnalysisMode.IMPACT]:
                # Get comprehensive context
                return await self.provider.get_symbol_context(symbol_name, repo_path)
            else:
                # Get basic context
                return await self.provider.get_symbol_context(symbol_name, repo_path)
                
        except Exception as e:
            logger.error(f"GitNexus symbol context failed: {e}")
            return {"error": f"GitNexus symbol context failed: {str(e)}"}
    
    async def analyze_change_impact(self, 
                                   target: str, 
                                   task_type: TaskType,
                                   direction: str = "upstream",
                                   repo_path: str = ".") -> Dict[str, Any]:
        """
        Analyze the impact of changes to a target with task-appropriate depth.
        
        Args:
            target: Name of the target to analyze (function, class, etc.)
            task_type: Type of task being performed
            direction: Direction of impact ("upstream" or "downstream")
            repo_path: Path to repository (default: current directory)
            
        Returns:
            Dictionary with impact analysis
        """
        if not await self.provider.is_available():
            return {"error": "GitNexus is not available"}
        
        try:
            return await self.provider.analyze_impact(target, direction, repo_path)
        except Exception as e:
            logger.error(f"GitNexus impact analysis failed: {e}")
            return {"error": f"GitNexus impact analysis failed: {str(e)}"}
    
    async def detect_repository_changes(self,
                                       task_type: TaskType,
                                       scope: str = "unstaged",
                                       repo_path: str = ".") -> Dict[str, Any]:
        """
        Detect repository changes with task-appropriate analysis.
        
        Args:
            scope: Scope of changes ("unstaged", "staged", "all", "compare")
            task_type: Type of task being performed
            repo_path: Path to repository (default: current directory)
            
        Returns:
            Dictionary with change detection results
        """
        if not await self.provider.is_available():
            return {"error": "GitNexus is not available"}
        
        try:
            results = await self.provider.detect_changes(task_type, scope, repo_path)
            
            # For debugging tasks, also analyze impact of changes
            if task_type == TaskType.DEBUGGING and "changed_symbols" in results:
                impact_analysis = {}
                for symbol in results["changed_symbols"][:5]:  # Limit to top 5
                    if "name" in symbol:
                        impact = await self.analyze_change_impact(
                            symbol["name"], task_type, "upstream", repo_path
                        )
                        if "error" not in impact:
                            impact_analysis[symbol["name"]] = impact
                results["change_impact"] = impact_analysis
            
            return results
        except Exception as e:
            logger.error(f"GitNexus change detection failed: {e}")
            return {"error": f"GitNexus change detection failed: {str(e)}"}


# Global router instance
_gitnexus_router: Optional[GitNexusRouter] = None


def get_gitnexus_router() -> GitNexusRouter:
    """
    Get the global GitNexus router instance.
    
    Returns:
        GitNexusRouter instance
    """
    global _gitnexus_router
    if _gitnexus_router is None:
        _gitnexus_router = GitNexusRouter()
    return _gitnexus_router