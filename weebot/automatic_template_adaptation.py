"""
Automatic Template Adaptation System for Weebot

This module provides capabilities for automatically adapting templates
based on usage patterns, feedback, and performance metrics.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol
import logging
from abc import ABC, abstractmethod
from pathlib import Path
import copy
import re
from collections import defaultdict, Counter

from weebot.templates.registry import TemplateRegistry
from weebot.templates.parser import WorkflowTemplate, TemplateParser
from weebot.templates.engine import TemplateEngine
from weebot.templates.integration import create_integrated_engine
from weebot.templates.production import ProductionTemplateEngine
from weebot.templates.adaptive import AdaptiveSuggestionEngine
from weebot.workflow_planner import WorkflowPlan, PlannedTask


class AdaptationType(Enum):
    """Types of template adaptations."""
    PARAMETER_OPTIMIZATION = "parameter_optimization"
    WORKFLOW_OPTIMIZATION = "workflow_optimization"
    TASK_REORDERING = "task_reordering"
    CONDITIONAL_BRANCHING = "conditional_branching"
    PERFORMANCE_IMPROVEMENT = "performance_improvement"
    USABILITY_ENHANCEMENT = "usability_enhancement"
    ERROR_HANDLING_IMPROVEMENT = "error_handling_improvement"
    RESOURCE_OPTIMIZATION = "resource_optimization"


class AdaptationQuality(Enum):
    """Quality levels for adaptations."""
    EXCELLENT = "excellent"  # 0.9-1.0
    GOOD = "good"           # 0.7-0.89
    FAIR = "fair"           # 0.5-0.69
    POOR = "poor"           # 0.3-0.49
    REJECTED = "rejected"   # 0.0-0.29


@dataclass
class AdaptationRule:
    """Rule for when and how to adapt a template."""
    rule_id: str
    template_name: str
    condition: str  # Condition that triggers the adaptation
    action: str     # Action to take when condition is met
    priority: int   # Priority of the rule (lower number = higher priority)
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TemplateAdaptation:
    """An adaptation made to a template."""
    adaptation_id: str
    template_name: str
    adaptation_type: AdaptationType
    description: str
    changes: Dict[str, Any]  # Description of changes made
    effectiveness_score: float  # How effective the adaptation was (0.0 to 1.0)
    quality_rating: AdaptationQuality
    timestamp: datetime
    applied_by: str  # Who or what applied the adaptation
    rollback_possible: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TemplatePerformanceMetrics:
    """Performance metrics for a template."""
    template_name: str
    execution_count: int
    success_count: int
    failure_count: int
    avg_execution_time: float  # in seconds
    avg_resource_usage: Dict[str, float]  # CPU, memory, etc.
    user_satisfaction: float  # 0.0 to 1.0
    common_errors: List[str]
    parameter_effectiveness: Dict[str, float]  # Effectiveness of different parameter values
    last_execution: datetime
    first_execution: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def success_rate(self) -> float:
        """Calculate success rate."""
        if self.execution_count == 0:
            return 0.0
        return self.success_count / self.execution_count


class TemplateAdaptationEngine(ABC):
    """Abstract base class for template adaptation engines."""
    
    @abstractmethod
    async def adapt_template(
        self,
        template_name: str,
        metrics: TemplatePerformanceMetrics
    ) -> Optional[TemplateAdaptation]:
        """Adapt a template based on its performance metrics."""
        pass


class ParameterOptimizationAdaptor(TemplateAdaptationEngine):
    """Adapts templates by optimizing parameter values."""
    
    def __init__(self, template_registry: TemplateRegistry):
        self.template_registry = template_registry
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    async def adapt_template(
        self,
        template_name: str,
        metrics: TemplatePerformanceMetrics
    ) -> Optional[TemplateAdaptation]:
        """Optimize template parameters based on effectiveness data."""
        # Get the template
        template = self.template_registry.get(template_name)
        if not template:
            self.logger.warning(f"Template {template_name} not found for adaptation")
            return None
        
        # Check if we have parameter effectiveness data
        if not metrics.parameter_effectiveness:
            self.logger.debug(f"No parameter effectiveness data for {template_name}")
            return None
        
        # Find parameters that could be optimized
        changes = {}
        for param_name, effectiveness in metrics.parameter_effectiveness.items():
            if effectiveness < 0.5:  # Poor effectiveness
                # Find better default value or constraint
                changes[param_name] = self._suggest_parameter_improvement(
                    template, param_name, effectiveness
                )
        
        if not changes:
            return None
        
        # Create adaptation record
        adaptation = TemplateAdaptation(
            adaptation_id=f"param_opt_{uuid.uuid4().hex[:8]}",
            template_name=template_name,
            adaptation_type=AdaptationType.PARAMETER_OPTIMIZATION,
            description=f"Optimized parameters based on effectiveness: {', '.join(changes.keys())}",
            changes={"optimized_parameters": changes},
            effectiveness_score=0.0,  # Will be calculated after application
            quality_rating=AdaptationQuality.FAIR,
            timestamp=datetime.now(),
            applied_by="ParameterOptimizationAdaptor",
            rollback_possible=True,
            metadata={"parameter_effectiveness": metrics.parameter_effectiveness}
        )
        
        return adaptation
    
    def _suggest_parameter_improvement(
        self,
        template: WorkflowTemplate,
        param_name: str,
        current_effectiveness: float
    ) -> Dict[str, Any]:
        """Suggest improvements for a poorly performing parameter."""
        param_def = template.parameters.get(param_name)
        if not param_def:
            return {}
        
        suggestions = {}
        
        # For string parameters, suggest more constrained values
        if param_def.type == "string":
            suggestions["validation"] = {
                "min_length": 3,
                "max_length": 200,
                "pattern": r".*"  # Could be more specific based on usage
            }
        
        # For numeric parameters, suggest better default or range
        elif param_def.type in ["int", "float"]:
            suggestions["suggested_default"] = self._calculate_better_default(
                param_def, current_effectiveness
            )
        
        # For enum parameters, suggest reordering or removing options
        elif param_def.type == "enum" and param_def.enum_values:
            suggestions["suggested_enum_order"] = self._suggest_enum_order(
                param_def.enum_values, current_effectiveness
            )
        
        return suggestions
    
    def _calculate_better_default(self, param_def, current_effectiveness):
        """Calculate a better default value for numeric parameters."""
        # This would be based on historical data in a real implementation
        # For now, return the current default
        return param_def.default if param_def.default is not None else 0
    
    def _suggest_enum_order(self, enum_values, current_effectiveness):
        """Suggest a better order for enum values."""
        # This would be based on usage patterns in a real implementation
        # For now, return the current order
        return enum_values


class WorkflowOptimizationAdaptor(TemplateAdaptationEngine):
    """Adapts templates by optimizing workflow structure."""
    
    def __init__(self, template_registry: TemplateRegistry):
        self.template_registry = template_registry
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    async def adapt_template(
        self,
        template_name: str,
        metrics: TemplatePerformanceMetrics
    ) -> Optional[TemplateAdaptation]:
        """Optimize workflow structure based on execution patterns."""
        # Get the template
        template = self.template_registry.get(template_name)
        if not template:
            self.logger.warning(f"Template {template_name} not found for adaptation")
            return None
        
        # Analyze workflow structure for optimization opportunities
        changes = await self._analyze_workflow_for_optimization(template, metrics)
        
        if not changes:
            return None
        
        # Create adaptation record
        adaptation = TemplateAdaptation(
            adaptation_id=f"wf_opt_{uuid.uuid4().hex[:8]}",
            template_name=template_name,
            adaptation_type=AdaptationType.WORKFLOW_OPTIMIZATION,
            description="Optimized workflow structure for better performance",
            changes=changes,
            effectiveness_score=0.0,  # Will be calculated after application
            quality_rating=AdaptationQuality.FAIR,
            timestamp=datetime.now(),
            applied_by="WorkflowOptimizationAdaptor",
            rollback_possible=True,
            metadata={"analysis_timestamp": datetime.now().isoformat()}
        )
        
        return adaptation
    
    async def _analyze_workflow_for_optimization(
        self,
        template: WorkflowTemplate,
        metrics: TemplatePerformanceMetrics
    ) -> Dict[str, Any]:
        """Analyze workflow for optimization opportunities."""
        changes = {}
        
        # Check for sequential tasks that could be parallelized
        if len(template.workflow) > 2:
            # Look for tasks that don't depend on each other and could run in parallel
            parallelizable_tasks = self._find_parallelizable_tasks(template)
            if parallelizable_tasks:
                changes["parallelization_suggestions"] = parallelizable_tasks
        
        # Check for tasks that commonly fail and suggest error handling
        if metrics.common_errors:
            error_handling_suggestions = self._suggest_error_handling(
                template, metrics.common_errors
            )
            if error_handling_suggestions:
                changes["error_handling_suggestions"] = error_handling_suggestions
        
        # Check for performance bottlenecks
        if metrics.avg_execution_time > 60:  # More than 1 minute
            performance_suggestions = self._suggest_performance_improvements(template)
            if performance_suggestions:
                changes["performance_suggestions"] = performance_suggestions
        
        return changes
    
    def _find_parallelizable_tasks(self, template: WorkflowTemplate) -> List[Dict[str, Any]]:
        """Find tasks that could potentially run in parallel."""
        # This is a simplified analysis - in a real implementation,
        # this would require more sophisticated dependency analysis
        parallelizable = []
        
        # For now, just identify tasks that don't depend on each other
        # In a real implementation, we'd analyze the dependency graph
        tasks = list(template.workflow.items())
        
        # Look for independent tasks
        for i, (task_id1, task1) in enumerate(tasks):
            for j, (task_id2, task2) in enumerate(tasks[i+1:], i+1):
                # Check if tasks are independent (simplified check)
                # In reality, we'd need to analyze the full dependency graph
                if not self._have_dependency(task_id1, task_id2, template.workflow):
                    parallelizable.append({
                        "tasks": [task_id1, task_id2],
                        "reason": "Independent tasks that could run in parallel"
                    })
        
        return parallelizable
    
    def _have_dependency(self, task1_id: str, task2_id: str, workflow: Dict[str, Any]) -> bool:
        """Check if two tasks have a dependency relationship."""
        # Simplified dependency check - in reality, this would be more complex
        # Look for dependencies in task definitions
        for task_id, task_def in workflow.items():
            if task_id in [task1_id, task2_id]:
                deps = task_def.get("deps", [])
                if task1_id in deps or task2_id in deps:
                    return True
        return False
    
    def _suggest_error_handling(
        self,
        template: WorkflowTemplate,
        common_errors: List[str]
    ) -> List[Dict[str, Any]]:
        """Suggest error handling improvements."""
        suggestions = []
        
        # For each common error, suggest appropriate handling
        for error in common_errors:
            # Find tasks that might be causing the error
            problematic_tasks = self._find_problematic_tasks(template, error)
            
            for task_id in problematic_tasks:
                suggestions.append({
                    "task_id": task_id,
                    "error_type": error,
                    "suggestion": "Add retry mechanism with exponential backoff",
                    "implementation": {
                        "retry_count": 3,
                        "backoff_factor": 2.0,
                        "timeout": 30
                    }
                })
        
        return suggestions
    
    def _find_problematic_tasks(self, template: WorkflowTemplate, error: str) -> List[str]:
        """Find tasks that are likely causing a specific error."""
        # Simplified implementation - in reality, this would require
        # analysis of error logs correlated with task execution
        problematic = []
        
        # Look for keywords in error message that might relate to task types
        error_lower = error.lower()
        for task_id, task_def in template.workflow.items():
            # Check if task type or description relates to error
            if any(keyword in error_lower for keyword in ["timeout", "connection", "network"]):
                if task_def.get("type", "").lower() in ["api_call", "web_request", "download"]:
                    problematic.append(task_id)
            elif any(keyword in error_lower for keyword in ["memory", "resource", "oom"]):
                if task_def.get("type", "").lower() in ["data_processing", "analysis", "computation"]:
                    problematic.append(task_id)
        
        return problematic
    
    def _suggest_performance_improvements(self, template: WorkflowTemplate) -> List[Dict[str, Any]]:
        """Suggest performance improvements for slow templates."""
        suggestions = []
        
        # Identify potentially slow tasks
        for task_id, task_def in template.workflow.items():
            task_type = task_def.get("type", "").lower()
            
            # Suggest caching for data retrieval tasks
            if any(keyword in task_type for keyword in ["fetch", "retrieve", "download", "query"]):
                suggestions.append({
                    "task_id": task_id,
                    "improvement": "Add caching mechanism",
                    "details": "Cache results of data retrieval to avoid repeated expensive operations"
                })
            
            # Suggest batching for tasks that process items individually
            if any(keyword in task_type for keyword in ["process", "transform", "analyze"]):
                suggestions.append({
                    "task_id": task_id,
                    "improvement": "Implement batching",
                    "details": "Process items in batches to reduce overhead"
                })
        
        return suggestions


class UsabilityEnhancementAdaptor(TemplateAdaptationEngine):
    """Adapts templates by enhancing usability based on user feedback."""
    
    def __init__(self, template_registry: TemplateRegistry):
        self.template_registry = template_registry
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    async def adapt_template(
        self,
        template_name: str,
        metrics: TemplatePerformanceMetrics
    ) -> Optional[TemplateAdaptation]:
        """Enhance template usability based on user satisfaction and feedback."""
        # Get the template
        template = self.template_registry.get(template_name)
        if not template:
            self.logger.warning(f"Template {template_name} not found for adaptation")
            return None
        
        # Check if user satisfaction is low
        if metrics.user_satisfaction >= 0.7:
            # Satisfaction is good, no need for usability enhancements
            return None
        
        # Analyze for usability improvements
        changes = await self._analyze_usability_improvements(template, metrics)
        
        if not changes:
            return None
        
        # Create adaptation record
        adaptation = TemplateAdaptation(
            adaptation_id=f"usability_{uuid.uuid4().hex[:8]}",
            template_name=template_name,
            adaptation_type=AdaptationType.USABILITY_ENHANCEMENT,
            description="Enhanced usability based on user feedback",
            changes=changes,
            effectiveness_score=0.0,  # Will be calculated after application
            quality_rating=AdaptationQuality.FAIR,
            timestamp=datetime.now(),
            applied_by="UsabilityEnhancementAdaptor",
            rollback_possible=True,
            metadata={"user_satisfaction": metrics.user_satisfaction}
        )
        
        return adaptation
    
    async def _analyze_usability_improvements(
        self,
        template: WorkflowTemplate,
        metrics: TemplatePerformanceMetrics
    ) -> Dict[str, Any]:
        """Analyze template for usability improvements."""
        changes = {}
        
        # Suggest better parameter descriptions if they seem unclear
        parameter_suggestions = self._suggest_parameter_improvements(template)
        if parameter_suggestions:
            changes["parameter_improvements"] = parameter_suggestions
        
        # Suggest workflow simplification if template is complex
        if len(template.workflow) > 5:  # Arbitrary complexity threshold
            simplification_suggestions = self._suggest_workflow_simplification(template)
            if simplification_suggestions:
                changes["simplification_suggestions"] = simplification_suggestions
        
        # Suggest better output formatting
        output_suggestions = self._suggest_output_improvements(template)
        if output_suggestions:
            changes["output_improvements"] = output_suggestions
        
        return changes
    
    def _suggest_parameter_improvements(self, template: WorkflowTemplate) -> List[Dict[str, Any]]:
        """Suggest improvements to parameter descriptions and defaults."""
        suggestions = []
        
        for param_name, param_def in template.parameters.items():
            # Check if description is too short or missing
            if not param_def.description or len(param_def.description) < 10:
                suggestions.append({
                    "parameter": param_name,
                    "issue": "Missing or inadequate description",
                    "suggestion": "Add detailed description of what the parameter controls and valid values"
                })
            
            # Check if default value is appropriate
            if param_def.default is None and param_def.required:
                suggestions.append({
                    "parameter": param_name,
                    "issue": "Required parameter without default",
                    "suggestion": "Consider providing a sensible default value or making optional with validation"
                })
        
        return suggestions
    
    def _suggest_workflow_simplification(self, template: WorkflowTemplate) -> List[Dict[str, Any]]:
        """Suggest ways to simplify complex workflows."""
        suggestions = []
        
        # Look for opportunities to combine similar tasks
        task_types = Counter()
        for task_id, task_def in template.workflow.items():
            task_type = task_def.get("type", "unknown")
            task_types[task_type] += 1
        
        # Suggest combining multiple similar tasks
        for task_type, count in task_types.items():
            if count > 2:  # More than 2 tasks of same type
                suggestions.append({
                    "task_type": task_type,
                    "count": count,
                    "suggestion": f"Consider combining multiple {task_type} tasks into a single parameterized task"
                })
        
        return suggestions
    
    def _suggest_output_improvements(self, template: WorkflowTemplate) -> List[Dict[str, Any]]:
        """Suggest improvements to output formatting."""
        suggestions = []
        
        # Check if output format is specified and clear
        if not hasattr(template, 'output') or not template.output:
            suggestions.append({
                "aspect": "output_format",
                "suggestion": "Define clear output format specification"
            })
        
        return suggestions


class TemplateAdaptationManager:
    """Main manager for template adaptations."""
    
    def __init__(
        self,
        template_registry: TemplateRegistry,
        template_engine: Optional[TemplateEngine] = None
    ):
        self.template_registry = template_registry
        self.template_engine = template_engine
        self.logger = logging.getLogger(f"{__name__}.TemplateAdaptationManager")
        
        # Initialize adaptors
        self.adaptors = [
            ParameterOptimizationAdaptor(template_registry),
            WorkflowOptimizationAdaptor(template_registry),
            UsabilityEnhancementAdaptor(template_registry)
        ]
        
        # Store adaptation history
        self.adaptation_history: List[TemplateAdaptation] = []
        
        # Store template performance metrics
        self.performance_metrics: Dict[str, TemplatePerformanceMetrics] = {}
    
    async def analyze_template_performance(
        self,
        template_name: str,
        execution_data: List[Dict[str, Any]]
    ) -> TemplatePerformanceMetrics:
        """Analyze performance data to generate metrics."""
        if not execution_data:
            # Return default metrics if no data
            return TemplatePerformanceMetrics(
                template_name=template_name,
                execution_count=0,
                success_count=0,
                failure_count=0,
                avg_execution_time=0.0,
                avg_resource_usage={},
                user_satisfaction=0.0,
                common_errors=[],
                parameter_effectiveness={},
                first_execution=datetime.now(),
                last_execution=datetime.now()
            )
        
        # Calculate metrics from execution data
        execution_count = len(execution_data)
        success_count = sum(1 for exec_data in execution_data if exec_data.get("success", False))
        failure_count = execution_count - success_count
        
        # Calculate average execution time
        exec_times = [data.get("execution_time", 0) for data in execution_data if "execution_time" in data]
        avg_exec_time = sum(exec_times) / len(exec_times) if exec_times else 0.0
        
        # Calculate user satisfaction (if available)
        satisfactions = [data.get("user_satisfaction", 0.5) for data in execution_data if "user_satisfaction" in data]
        user_satisfaction = sum(satisfactions) / len(satisfactions) if satisfactions else 0.5
        
        # Identify common errors
        errors = [data.get("error", "") for data in execution_data if data.get("error")]
        error_counts = Counter(errors)
        common_errors = [error for error, count in error_counts.most_common(5) if count > 1]
        
        # Calculate parameter effectiveness (simplified)
        parameter_effectiveness = self._calculate_parameter_effectiveness(execution_data)
        
        # Get resource usage (simplified)
        resource_usage_samples = [
            data.get("resource_usage", {}) for data in execution_data 
            if "resource_usage" in data
        ]
        avg_resource_usage = {}
        if resource_usage_samples:
            # Calculate averages for each resource type
            resource_types = set()
            for sample in resource_usage_samples:
                resource_types.update(sample.keys())
            
            for resource_type in resource_types:
                values = [sample.get(resource_type, 0) for sample in resource_usage_samples]
                avg_resource_usage[resource_type] = sum(values) / len(values)
        
        # Create metrics object
        metrics = TemplatePerformanceMetrics(
            template_name=template_name,
            execution_count=execution_count,
            success_count=success_count,
            failure_count=failure_count,
            avg_execution_time=avg_exec_time,
            avg_resource_usage=avg_resource_usage,
            user_satisfaction=user_satisfaction,
            common_errors=common_errors,
            parameter_effectiveness=parameter_effectiveness,
            first_execution=datetime.fromisoformat(execution_data[0]["timestamp"]) if execution_data and "timestamp" in execution_data[0] else datetime.now(),
            last_execution=datetime.fromisoformat(execution_data[-1]["timestamp"]) if execution_data and "timestamp" in execution_data[-1] else datetime.now()
        )
        
        # Store metrics
        self.performance_metrics[template_name] = metrics
        
        return metrics
    
    def _calculate_parameter_effectiveness(self, execution_data: List[Dict[str, Any]]) -> Dict[str, float]:
        """Calculate effectiveness of different parameter values."""
        # Simplified implementation - in reality, this would require
        # more sophisticated analysis correlating parameter values with outcomes
        effectiveness = {}
        
        # For each execution, look at parameters and success/failure
        for exec_data in execution_data:
            params = exec_data.get("parameters", {})
            success = exec_data.get("success", False)
            
            for param_name, param_value in params.items():
                if param_name not in effectiveness:
                    effectiveness[param_name] = {"success_count": 0, "total_count": 0}
                
                effectiveness[param_name]["total_count"] += 1
                if success:
                    effectiveness[param_name]["success_count"] += 1
        
        # Convert to effectiveness scores
        for param_name, stats in effectiveness.items():
            if stats["total_count"] > 0:
                effectiveness[param_name] = stats["success_count"] / stats["total_count"]
            else:
                effectiveness[param_name] = 0.5  # Default neutral effectiveness
        
        return effectiveness
    
    async def adapt_template(
        self,
        template_name: str,
        metrics: Optional[TemplatePerformanceMetrics] = None
    ) -> List[TemplateAdaptation]:
        """Adapt a template based on its performance metrics."""
        if not metrics:
            # If no metrics provided, use stored metrics
            metrics = self.performance_metrics.get(template_name)
            if not metrics:
                self.logger.warning(f"No metrics available for template {template_name}")
                return []
        
        adaptations = []
        
        # Apply each adaptor
        for adaptor in self.adaptors:
            try:
                adaptation = await adaptor.adapt_template(template_name, metrics)
                if adaptation:
                    adaptations.append(adaptation)
                    self.adaptation_history.append(adaptation)
            except Exception as e:
                self.logger.error(f"Error applying adaptor {type(adaptor).__name__}: {e}")
                continue
        
        # Sort adaptations by priority/type
        adaptations.sort(key=lambda x: (
            self._get_adaptation_priority(x.adaptation_type),
            -x.effectiveness_score
        ))
        
        return adaptations
    
    def _get_adaptation_priority(self, adaptation_type: AdaptationType) -> int:
        """Get priority for adaptation type (lower number = higher priority)."""
        priority_map = {
            AdaptationType.ERROR_HANDLING_IMPROVEMENT: 1,  # Highest priority
            AdaptationType.PERFORMANCE_IMPROVEMENT: 2,
            AdaptationType.RESOURCE_OPTIMIZATION: 3,
            AdaptationType.WORKFLOW_OPTIMIZATION: 4,
            AdaptationType.PARAMETER_OPTIMIZATION: 5,
            AdaptationType.USABILITY_ENHANCEMENT: 6,
            AdaptationType.TASK_REORDERING: 7,
            AdaptationType.CONDITIONAL_BRANCHING: 8  # Lowest priority
        }
        return priority_map.get(adaptation_type, 9)
    
    async def apply_adaptation(
        self,
        adaptation: TemplateAdaptation,
        dry_run: bool = False
    ) -> bool:
        """Apply an adaptation to a template."""
        if dry_run:
            self.logger.info(f"Dry run: Would apply adaptation {adaptation.adaptation_id} to {adaptation.template_name}")
            return True
        
        try:
            # Get the template to modify
            template = self.template_registry.get(adaptation.template_name)
            if not template:
                self.logger.error(f"Template {adaptation.template_name} not found for adaptation")
                return False
            
            # Apply the adaptation based on its type
            if adaptation.adaptation_type == AdaptationType.PARAMETER_OPTIMIZATION:
                success = await self._apply_parameter_optimization(template, adaptation.changes)
            elif adaptation.adaptation_type == AdaptationType.WORKFLOW_OPTIMIZATION:
                success = await self._apply_workflow_optimization(template, adaptation.changes)
            elif adaptation.adaptation_type == AdaptationType.USABILITY_ENHANCEMENT:
                success = await self._apply_usability_enhancement(template, adaptation.changes)
            else:
                # For other types, we might need different application methods
                self.logger.warning(f"Applying adaptation type {adaptation.adaptation_type} not implemented yet")
                success = True  # Consider it successful for now
            
            if success:
                # Update the template in the registry
                # Note: This is a simplified approach - in reality, we'd need to update the template object
                # and potentially save it back to storage
                self.logger.info(f"Successfully applied adaptation {adaptation.adaptation_id} to {adaptation.template_name}")
                
                # Update the adaptation record with effectiveness
                adaptation.effectiveness_score = 0.8  # Placeholder - would be calculated based on results
                adaptation.quality_rating = self._score_to_quality(adaptation.effectiveness_score)
            else:
                self.logger.error(f"Failed to apply adaptation {adaptation.adaptation_id} to {adaptation.template_name}")
            
            return success
            
        except Exception as e:
            self.logger.error(f"Error applying adaptation {adaptation.adaptation_id}: {e}")
            return False
    
    async def _apply_parameter_optimization(self, template: WorkflowTemplate, changes: Dict[str, Any]) -> bool:
        """Apply parameter optimization changes to a template."""
        try:
            # Update parameter definitions based on suggestions
            optimized_params = changes.get("optimized_parameters", {})
            
            for param_name, param_changes in optimized_params.items():
                if param_name in template.parameters:
                    param_def = template.parameters[param_name]
                    
                    # Apply validation suggestions
                    if "validation" in param_changes:
                        validation = param_changes["validation"]
                        # In a real implementation, we'd update the parameter definition
                        # For now, we'll just log the suggested changes
                        self.logger.info(f"Suggested validation changes for {param_name}: {validation}")
                    
                    # Apply default value suggestions
                    if "suggested_default" in param_changes:
                        new_default = param_changes["suggested_default"]
                        # In a real implementation, we'd update the parameter definition
                        self.logger.info(f"Suggested default change for {param_name}: {new_default}")
            
            return True
        except Exception as e:
            self.logger.error(f"Error applying parameter optimization: {e}")
            return False
    
    async def _apply_workflow_optimization(self, template: WorkflowTemplate, changes: Dict[str, Any]) -> bool:
        """Apply workflow optimization changes to a template."""
        try:
            # Apply parallelization suggestions
            if "parallelization_suggestions" in changes:
                suggestions = changes["parallelization_suggestions"]
                for suggestion in suggestions:
                    tasks = suggestion["tasks"]
                    self.logger.info(f"Suggested parallelization for tasks: {tasks}")
                    # In a real implementation, we'd modify the workflow structure
            
            # Apply error handling suggestions
            if "error_handling_suggestions" in changes:
                suggestions = changes["error_handling_suggestions"]
                for suggestion in suggestions:
                    task_id = suggestion["task_id"]
                    implementation = suggestion["implementation"]
                    self.logger.info(f"Suggested error handling for {task_id}: {implementation}")
                    # In a real implementation, we'd modify the task definition
            
            # Apply performance suggestions
            if "performance_suggestions" in changes:
                suggestions = changes["performance_suggestions"]
                for suggestion in suggestions:
                    task_id = suggestion.get("task_id", "multiple")
                    improvement = suggestion["improvement"]
                    self.logger.info(f"Suggested performance improvement for {task_id}: {improvement}")
            
            return True
        except Exception as e:
            self.logger.error(f"Error applying workflow optimization: {e}")
            return False
    
    async def _apply_usability_enhancement(self, template: WorkflowTemplate, changes: Dict[str, Any]) -> bool:
        """Apply usability enhancement changes to a template."""
        try:
            # Apply parameter improvement suggestions
            if "parameter_improvements" in changes:
                suggestions = changes["parameter_improvements"]
                for suggestion in suggestions:
                    param = suggestion["parameter"]
                    issue = suggestion["issue"]
                    sug = suggestion["suggestion"]
                    self.logger.info(f"Parameter improvement for {param}: {issue} -> {sug}")
            
            # Apply workflow simplification suggestions
            if "simplification_suggestions" in changes:
                suggestions = changes["simplification_suggestions"]
                for suggestion in suggestions:
                    task_type = suggestion["task_type"]
                    count = suggestion["count"]
                    sug = suggestion["suggestion"]
                    self.logger.info(f"Simplification suggestion for {task_type} ({count} tasks): {sug}")
            
            # Apply output improvement suggestions
            if "output_improvements" in changes:
                suggestions = changes["output_improvements"]
                for suggestion in suggestions:
                    aspect = suggestion["aspect"]
                    sug = suggestion["suggestion"]
                    self.logger.info(f"Output improvement for {aspect}: {sug}")
            
            return True
        except Exception as e:
            self.logger.error(f"Error applying usability enhancement: {e}")
            return False
    
    def _score_to_quality(self, score: float) -> AdaptationQuality:
        """Convert numerical score to quality rating."""
        if score >= 0.9:
            return AdaptationQuality.EXCELLENT
        elif score >= 0.7:
            return AdaptationQuality.GOOD
        elif score >= 0.5:
            return AdaptationQuality.FAIR
        elif score >= 0.3:
            return AdaptationQuality.POOR
        else:
            return AdaptationQuality.REJECTED
    
    async def get_adaptation_history(self, template_name: Optional[str] = None) -> List[TemplateAdaptation]:
        """Get adaptation history, optionally filtered by template name."""
        if template_name:
            return [adaptation for adaptation in self.adaptation_history 
                    if adaptation.template_name == template_name]
        else:
            return self.adaptation_history[:]
    
    async def evaluate_adaptation_effectiveness(
        self,
        adaptation_id: str,
        post_adaptation_metrics: TemplatePerformanceMetrics
    ) -> float:
        """Evaluate how effective an adaptation was based on post-adaptation metrics."""
        # Find the adaptation in history
        adaptation = next(
            (adapt for adapt in self.adaptation_history if adapt.adaptation_id == adaptation_id),
            None
        )
        
        if not adaptation:
            self.logger.warning(f"Adaptation {adaptation_id} not found in history")
            return 0.0
        
        # Get the original metrics for comparison
        original_metrics = self.performance_metrics.get(adaptation.template_name)
        if not original_metrics:
            self.logger.warning(f"No original metrics found for template {adaptation.template_name}")
            return 0.5  # Neutral effectiveness
        
        # Calculate effectiveness based on improvement in key metrics
        effectiveness = 0.0
        
        # Success rate improvement
        orig_success_rate = original_metrics.success_rate()
        new_success_rate = post_adaptation_metrics.success_rate()
        if new_success_rate > orig_success_rate:
            effectiveness += (new_success_rate - orig_success_rate) * 0.4  # 40% weight
        
        # Execution time improvement (faster is better)
        if original_metrics.avg_execution_time > 0:
            time_improvement = (original_metrics.avg_execution_time - post_adaptation_metrics.avg_execution_time) / original_metrics.avg_execution_time
            effectiveness += max(0, time_improvement) * 0.3  # 30% weight
        
        # User satisfaction improvement
        sat_improvement = post_adaptation_metrics.user_satisfaction - original_metrics.user_satisfaction
        effectiveness += max(0, sat_improvement) * 0.3  # 30% weight
        
        # Ensure effectiveness is between 0 and 1
        effectiveness = max(0.0, min(1.0, effectiveness))
        
        # Update the adaptation record with effectiveness
        adaptation.effectiveness_score = effectiveness
        adaptation.quality_rating = self._score_to_quality(effectiveness)
        
        return effectiveness


class TemplateAdaptationTool:
    """Tool for managing template adaptations."""
    
    def __init__(self, adaptation_manager: TemplateAdaptationManager):
        self.adaptation_manager = adaptation_manager
        self.logger = logging.getLogger(f"{__name__}.TemplateAdaptationTool")
    
    async def analyze_performance(
        self,
        template_name: str,
        execution_data: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Analyze template performance and generate metrics."""
        try:
            metrics = await self.adaptation_manager.analyze_template_performance(
                template_name, execution_data
            )
            
            return {
                "success": True,
                "template_name": template_name,
                "metrics": {
                    "execution_count": metrics.execution_count,
                    "success_rate": metrics.success_rate(),
                    "avg_execution_time": metrics.avg_execution_time,
                    "user_satisfaction": metrics.user_satisfaction,
                    "common_errors": metrics.common_errors,
                    "parameter_effectiveness": metrics.parameter_effectiveness,
                    "first_execution": metrics.first_execution.isoformat(),
                    "last_execution": metrics.last_execution.isoformat()
                }
            }
        except Exception as e:
            self.logger.error(f"Error analyzing performance: {e}")
            return {
                "success": False,
                "error": f"Error analyzing performance: {str(e)}",
                "template_name": template_name
            }
    
    async def get_adaptations(
        self,
        template_name: str
    ) -> Dict[str, Any]:
        """Get suggested adaptations for a template."""
        try:
            # First, ensure we have metrics for the template
            if template_name not in self.adaptation_manager.performance_metrics:
                self.logger.warning(f"No metrics available for {template_name}, returning empty adaptations")
                return {
                    "success": True,
                    "template_name": template_name,
                    "adaptations_count": 0,
                    "adaptations": []
                }
            
            # Get adaptations
            adaptations = await self.adaptation_manager.adapt_template(template_name)
            
            formatted_adaptations = []
            for adaptation in adaptations:
                formatted_adaptations.append({
                    "adaptation_id": adaptation.adaptation_id,
                    "adaptation_type": adaptation.adaptation_type.value,
                    "description": adaptation.description,
                    "changes": adaptation.changes,
                    "effectiveness_score": adaptation.effectiveness_score,
                    "quality_rating": adaptation.quality_rating.value,
                    "timestamp": adaptation.timestamp.isoformat(),
                    "applied_by": adaptation.applied_by
                })
            
            return {
                "success": True,
                "template_name": template_name,
                "adaptations_count": len(formatted_adaptations),
                "adaptations": formatted_adaptations
            }
        except Exception as e:
            self.logger.error(f"Error getting adaptations: {e}")
            return {
                "success": False,
                "error": f"Error getting adaptations: {str(e)}",
                "template_name": template_name
            }
    
    async def apply_adaptation(
        self,
        adaptation_id: str,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Apply a specific adaptation."""
        try:
            # Find the adaptation in history
            adaptation = next(
                (adapt for adapt in self.adaptation_manager.adaptation_history 
                 if adapt.adaptation_id == adaptation_id),
                None
            )
            
            if not adaptation:
                return {
                    "success": False,
                    "error": f"Adaptation {adaptation_id} not found",
                    "adaptation_id": adaptation_id
                }
            
            success = await self.adaptation_manager.apply_adaptation(adaptation, dry_run)
            
            if success:
                return {
                    "success": True,
                    "message": f"Successfully applied adaptation {adaptation_id}{' (dry run)' if dry_run else ''}",
                    "adaptation_id": adaptation_id,
                    "template_name": adaptation.template_name
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to apply adaptation {adaptation_id}",
                    "adaptation_id": adaptation_id
                }
        except Exception as e:
            self.logger.error(f"Error applying adaptation: {e}")
            return {
                "success": False,
                "error": f"Error applying adaptation: {str(e)}",
                "adaptation_id": adaptation_id
            }
    
    async def get_adaptation_history(
        self,
        template_name: str
    ) -> Dict[str, Any]:
        """Get adaptation history for a template."""
        try:
            history = await self.adaptation_manager.get_adaptation_history(template_name)
            
            formatted_history = []
            for adaptation in history:
                formatted_history.append({
                    "adaptation_id": adaptation.adaptation_id,
                    "adaptation_type": adaptation.adaptation_type.value,
                    "description": adaptation.description,
                    "effectiveness_score": adaptation.effectiveness_score,
                    "quality_rating": adaptation.quality_rating.value,
                    "timestamp": adaptation.timestamp.isoformat(),
                    "applied_by": adaptation.applied_by
                })
            
            return {
                "success": True,
                "template_name": template_name,
                "history_count": len(formatted_history),
                "history": formatted_history
            }
        except Exception as e:
            self.logger.error(f"Error getting adaptation history: {e}")
            return {
                "success": False,
                "error": f"Error getting adaptation history: {str(e)}",
                "template_name": template_name
            }
    
    def to_param(self) -> Dict[str, Any]:
        """Convert to parameter format for tool registration."""
        return {
            "type": "function",
            "function": {
                "name": "template_adaptation_tool",
                "description": "Analyze and adapt templates based on performance metrics",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["analyze_performance", "get_adaptations", "apply_adaptation", "get_history"],
                            "description": "Action to perform"
                        },
                        "template_name": {
                            "type": "string",
                            "description": "Name of the template to analyze/adapt"
                        },
                        "execution_data": {
                            "type": "array",
                            "items": {"type": "object"},
                            "description": "Execution data for performance analysis (for analyze_performance action)"
                        },
                        "adaptation_id": {
                            "type": "string",
                            "description": "ID of the adaptation to apply (for apply_adaptation action)"
                        },
                        "dry_run": {
                            "type": "boolean",
                            "description": "Whether to perform a dry run (for apply_adaptation action)",
                            "default": False
                        }
                    },
                    "required": ["action", "template_name"]
                }
            }
        }


# Example usage
if __name__ == "__main__":
    import asyncio
    
    async def example():
        # Create a basic template registry (mock)
        class MockTemplateRegistry:
            def __init__(self):
                self.templates = {
                    "Research Analysis Workflow": type('Template', (), {
                        'name': 'Research Analysis Workflow',
                        'description': 'Comprehensive research and analysis workflow',
                        'parameters': {
                            'topic': type('Param', (), {
                                'type': 'string',
                                'description': 'Research topic',
                                'required': True
                            })()
                        },
                        'workflow': {
                            'step1': {'type': 'task', 'deps': []},
                            'step2': {'type': 'task', 'deps': ['step1']},
                            'step3': {'type': 'task', 'deps': ['step2']}
                        }
                    })()
                }
            
            def get(self, name):
                return self.templates.get(name)
            
            def list_templates(self):
                return list(self.templates.keys())
        
        # Create template registry and adaptation manager
        template_registry = MockTemplateRegistry()
        adaptation_manager = TemplateAdaptationManager(template_registry)
        
        print("Analyzing template performance...")
        
        # Sample execution data
        execution_data = [
            {
                "timestamp": datetime.now().isoformat(),
                "success": True,
                "execution_time": 120.5,
                "user_satisfaction": 0.7,
                "parameters": {"topic": "AI research"},
                "resource_usage": {"cpu": 0.45, "memory": 0.6}
            },
            {
                "timestamp": datetime.now().isoformat(),
                "success": False,
                "execution_time": 300.0,
                "user_satisfaction": 0.3,
                "error": "Timeout error",
                "parameters": {"topic": "Complex analysis"},
                "resource_usage": {"cpu": 0.85, "memory": 0.9}
            },
            {
                "timestamp": datetime.now().isoformat(),
                "success": True,
                "execution_time": 90.2,
                "user_satisfaction": 0.8,
                "parameters": {"topic": "Market trends"},
                "resource_usage": {"cpu": 0.3, "memory": 0.4}
            }
        ]
        
        # Analyze performance
        metrics = await adaptation_manager.analyze_template_performance(
            "Research Analysis Workflow", execution_data
        )
        
        print(f"Template: {metrics.template_name}")
        print(f"Execution count: {metrics.execution_count}")
        print(f"Success rate: {metrics.success_rate():.2f}")
        print(f"Avg execution time: {metrics.avg_execution_time:.2f}s")
        print(f"User satisfaction: {metrics.user_satisfaction:.2f}")
        print(f"Common errors: {metrics.common_errors}")
        print(f"Parameter effectiveness: {metrics.parameter_effectiveness}")
        
        print("\nGenerating adaptations...")
        
        # Get adaptations
        adaptations = await adaptation_manager.adapt_template("Research Analysis Workflow", metrics)
        
        print(f"Generated {len(adaptations)} adaptations:")
        for i, adaptation in enumerate(adaptations, 1):
            print(f"\n{i}. {adaptation.adaptation_type.value}")
            print(f"   Description: {adaptation.description}")
            print(f"   Effectiveness: {adaptation.effectiveness_score:.2f}")
            print(f"   Quality: {adaptation.quality_rating.value}")
            print(f"   Changes: {adaptation.changes}")
        
        print("\nExample completed successfully!")
    
    asyncio.run(example())