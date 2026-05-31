"""
Learning from Successful Executions System for Weebot

This module provides capabilities for learning from successful template executions
to improve future performance and recommendations.
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
from collections import defaultdict, Counter
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans
from sklearn.linear_model import LinearRegression
import re

from weebot.templates.registry import TemplateRegistry
from weebot.templates.parser import WorkflowTemplate
from weebot.templates.engine import TemplateEngine
from weebot.templates.adaptive import AdaptiveSuggestionEngine
from weebot.workflow_planner import WorkflowPlan, PlannedTask
from weebot.user_profile_model import UserProfile, UserProfileManager


class LearningEventType(Enum):
    """Types of learning events."""
    EXECUTION_SUCCESS = "execution_success"
    EXECUTION_FAILURE = "execution_failure"
    PERFORMANCE_IMPROVEMENT = "performance_improvement"
    PARAMETER_OPTIMIZATION = "parameter_optimization"
    WORKFLOW_OPTIMIZATION = "workflow_optimization"
    USER_SATISFACTION = "user_satisfaction"
    RESOURCE_OPTIMIZATION = "resource_optimization"
    ERROR_RECOVERY = "error_recovery"


class LearningOutcome(Enum):
    """Outcomes of learning events."""
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
    INSIGHTFUL = "insightful"


@dataclass
class ExecutionRecord:
    """Record of a template execution."""
    execution_id: str
    template_name: str
    user_id: str
    parameters: Dict[str, Any]
    success: bool
    execution_time: float  # in seconds
    resource_usage: Dict[str, float]  # CPU, memory, etc.
    output_size: int  # Size of output in characters
    error_message: Optional[str] = None
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    user_satisfaction: Optional[float] = None  # 0.0 to 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LearningInsight:
    """An insight learned from execution data."""
    insight_id: str
    insight_type: LearningEventType
    description: str
    template_name: str
    parameters: Dict[str, Any]  # Relevant parameters
    conditions: Dict[str, Any]  # Conditions under which insight applies
    recommendations: List[str]  # Recommendations based on insight
    confidence: float  # 0.0 to 1.0
    outcome: LearningOutcome
    timestamp: datetime
    supporting_data: List[Dict[str, Any]]  # Supporting execution records
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PerformancePattern:
    """A pattern identified in execution performance."""
    pattern_id: str
    template_name: str
    pattern_type: str  # "parameter_correlation", "resource_usage", "timing", etc.
    description: str
    correlation_data: Dict[str, Any]  # Data showing the pattern
    impact_score: float  # How impactful this pattern is (0.0 to 1.0)
    frequency: int  # How often this pattern occurs
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


class ExecutionLearningEngine(ABC):
    """Abstract base class for execution learning engines."""
    
    @abstractmethod
    async def learn_from_execution(
        self,
        execution_record: ExecutionRecord
    ) -> List[LearningInsight]:
        """Learn from a single execution record."""
        pass
    
    @abstractmethod
    async def analyze_execution_patterns(
        self,
        template_name: str,
        execution_records: List[ExecutionRecord]
    ) -> List[PerformancePattern]:
        """Analyze patterns in execution data."""
        pass


class ParameterCorrelationLearner(ExecutionLearningEngine):
    """Learns correlations between parameters and execution outcomes."""
    
    def __init__(self, template_registry: TemplateRegistry):
        self.template_registry = template_registry
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.param_correlations: Dict[str, Dict[str, float]] = defaultdict(dict)
    
    async def learn_from_execution(
        self,
        execution_record: ExecutionRecord
    ) -> List[LearningInsight]:
        """Learn from parameter-outcome correlations."""
        insights = []
        
        # Get the template to understand parameter types
        template = self.template_registry.get(execution_record.template_name)
        if not template:
            self.logger.warning(f"Template {execution_record.template_name} not found for learning")
            return []
        
        # Analyze each parameter's correlation with success
        for param_name, param_value in execution_record.parameters.items():
            correlation_key = f"{execution_record.template_name}:{param_name}"
            
            # Update correlation data
            if correlation_key not in self.param_correlations:
                self.param_correlations[correlation_key] = {
                    "success_sum": 0,
                    "total_sum": 0,
                    "count": 0
                }
            
            self.param_correlations[correlation_key]["count"] += 1
            self.param_correlations[correlation_key]["total_sum"] += 1
            if execution_record.success:
                self.param_correlations[correlation_key]["success_sum"] += 1
        
        # Generate insights based on strong correlations
        for param_name, param_value in execution_record.parameters.items():
            correlation_key = f"{execution_record.template_name}:{param_name}"
            corr_data = self.param_correlations[correlation_key]
            
            if corr_data["count"] >= 5:  # Only consider if we have enough data
                success_rate = corr_data["success_sum"] / corr_data["count"]
                
                # Generate insight if correlation is strong
                if success_rate >= 0.9 or success_rate <= 0.1:
                    strength = abs(success_rate - 0.5) * 2  # 0 to 1 scale
                    outcome = LearningOutcome.POSITIVE if success_rate >= 0.9 else LearningOutcome.NEGATIVE
                    
                    insight = LearningInsight(
                        insight_id=f"param_corr_{uuid.uuid4().hex[:8]}",
                        insight_type=LearningEventType.PARAMETER_OPTIMIZATION,
                        description=f"Parameter '{param_name}' value '{param_value}' correlates with {success_rate:.1%} success rate",
                        template_name=execution_record.template_name,
                        parameters={param_name: param_value},
                        conditions={
                            "success_rate": success_rate,
                            "sample_size": corr_data["count"]
                        },
                        recommendations=[
                            f"Consider defaulting '{param_name}' to '{param_value}' for higher success rate" if success_rate >= 0.9
                            else f"Avoid '{param_value}' for '{param_name}' as it leads to low success rate"
                        ],
                        confidence=min(1.0, strength),
                        outcome=outcome,
                        timestamp=datetime.now(),
                        supporting_data=[{
                            "execution_id": execution_record.execution_id,
                            "success": execution_record.success,
                            "param_value": param_value
                        }],
                        metadata={"correlation_strength": strength}
                    )
                    
                    insights.append(insight)
        
        return insights
    
    async def analyze_execution_patterns(
        self,
        template_name: str,
        execution_records: List[ExecutionRecord]
    ) -> List[PerformancePattern]:
        """Analyze parameter correlation patterns."""
        patterns = []
        
        # Group records by template
        template_records = [rec for rec in execution_records if rec.template_name == template_name]
        
        if len(template_records) < 5:
            return []  # Not enough data
        
        # Analyze each parameter
        all_params = set()
        for record in template_records:
            all_params.update(record.parameters.keys())
        
        for param_name in all_params:
            # Calculate success rates for different parameter values
            value_success_rates = defaultdict(lambda: {"success": 0, "total": 0})
            
            for record in template_records:
                if param_name in record.parameters:
                    param_value = str(record.parameters[param_name])  # Convert to string for grouping
                    value_success_rates[param_value]["total"] += 1
                    if record.success:
                        value_success_rates[param_value]["success"] += 1
            
            # Find values with high/low success rates
            for param_value, counts in value_success_rates.items():
                if counts["total"] >= 3:  # At least 3 occurrences
                    success_rate = counts["success"] / counts["total"]
                    
                    if success_rate >= 0.8 or success_rate <= 0.2:
                        pattern_strength = abs(success_rate - 0.5) * 2
                        
                        pattern = PerformancePattern(
                            pattern_id=f"param_corr_{uuid.uuid4().hex[:8]}",
                            template_name=template_name,
                            pattern_type="parameter_correlation",
                            description=f"Parameter '{param_name}' value '{param_value}' has {success_rate:.1%} success rate",
                            correlation_data={
                                "parameter_name": param_name,
                                "parameter_value": param_value,
                                "success_rate": success_rate,
                                "sample_size": counts["total"]
                            },
                            impact_score=pattern_strength,
                            frequency=counts["total"],
                            timestamp=datetime.now(),
                            metadata={"correlation_type": "success_rate"}
                        )
                        
                        patterns.append(pattern)
        
        return patterns


class ResourceOptimizationLearner(ExecutionLearningEngine):
    """Learns resource usage patterns to optimize performance."""
    
    def __init__(self, template_registry: TemplateRegistry):
        self.template_registry = template_registry
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.resource_patterns: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    
    async def learn_from_execution(
        self,
        execution_record: ExecutionRecord
    ) -> List[LearningInsight]:
        """Learn from resource usage patterns."""
        insights = []
        
        if not execution_record.resource_usage:
            return []  # No resource data to learn from
        
        # Store resource usage data
        template_key = execution_record.template_name
        self.resource_patterns[template_key].append({
            "parameters": execution_record.parameters,
            "resource_usage": execution_record.resource_usage,
            "execution_time": execution_record.execution_time,
            "success": execution_record.success,
            "timestamp": execution_record.start_time
        })
        
        # Keep only recent data (last 100 executions)
        if len(self.resource_patterns[template_key]) > 100:
            self.resource_patterns[template_key] = self.resource_patterns[template_key][-100:]
        
        # Look for resource optimization opportunities
        recent_records = self.resource_patterns[template_key][-20:]  # Look at last 20 executions
        
        if len(recent_records) >= 5:
            # Calculate average resource usage
            avg_cpu = np.mean([rec["resource_usage"].get("cpu", 0) for rec in recent_records])
            avg_memory = np.mean([rec["resource_usage"].get("memory", 0) for rec in recent_records])
            avg_time = np.mean([rec["execution_time"] for rec in recent_records])
            
            # Generate insights for high resource usage
            if avg_cpu > 0.8:  # High CPU usage
                insight = LearningInsight(
                    insight_id=f"resource_cpu_{uuid.uuid4().hex[:8]}",
                    insight_type=LearningEventType.RESOURCE_OPTIMIZATION,
                    description=f"Template {template_key} has high average CPU usage ({avg_cpu:.1%})",
                    template_name=template_key,
                    parameters=execution_record.parameters,
                    conditions={
                        "avg_cpu_usage": avg_cpu,
                        "sample_size": len(recent_records)
                    },
                    recommendations=[
                        "Consider optimizing CPU-intensive operations",
                        "Implement parallel processing where possible",
                        "Review algorithm efficiency"
                    ],
                    confidence=0.7,
                    outcome=LearningOutcome.NEGATIVE,
                    timestamp=datetime.now(),
                    supporting_data=recent_records[-5:],  # Last 5 records
                    metadata={"resource_type": "cpu", "average_usage": avg_cpu}
                )
                insights.append(insight)
            
            if avg_memory > 0.8:  # High memory usage
                insight = LearningInsight(
                    insight_id=f"resource_mem_{uuid.uuid4().hex[:8]}",
                    insight_type=LearningEventType.RESOURCE_OPTIMIZATION,
                    description=f"Template {template_key} has high average memory usage ({avg_memory:.1%})",
                    template_name=template_key,
                    parameters=execution_record.parameters,
                    conditions={
                        "avg_memory_usage": avg_memory,
                        "sample_size": len(recent_records)
                    },
                    recommendations=[
                        "Consider implementing memory-efficient algorithms",
                        "Add garbage collection at appropriate intervals",
                        "Process data in smaller chunks"
                    ],
                    confidence=0.7,
                    outcome=LearningOutcome.NEGATIVE,
                    timestamp=datetime.now(),
                    supporting_data=recent_records[-5:],  # Last 5 records
                    metadata={"resource_type": "memory", "average_usage": avg_memory}
                )
                insights.append(insight)
        
        return insights
    
    async def analyze_execution_patterns(
        self,
        template_name: str,
        execution_records: List[ExecutionRecord]
    ) -> List[PerformancePattern]:
        """Analyze resource usage patterns."""
        patterns = []
        
        template_records = [rec for rec in execution_records if rec.template_name == template_name]
        
        if len(template_records) < 5:
            return []
        
        # Calculate resource usage statistics
        cpu_values = [rec.resource_usage.get("cpu", 0) for rec in template_records if rec.resource_usage]
        memory_values = [rec.resource_usage.get("memory", 0) for rec in template_records if rec.resource_usage]
        time_values = [rec.execution_time for rec in template_records]
        
        if cpu_values:
            avg_cpu = np.mean(cpu_values)
            std_cpu = np.std(cpu_values)
            
            pattern = PerformancePattern(
                pattern_id=f"resource_cpu_{uuid.uuid4().hex[:8]}",
                template_name=template_name,
                pattern_type="resource_usage",
                description=f"CPU usage: avg={avg_cpu:.1%}, std={std_cpu:.2f}",
                correlation_data={
                    "metric": "cpu",
                    "average": avg_cpu,
                    "std_deviation": std_cpu,
                    "sample_size": len(cpu_values)
                },
                impact_score=std_cpu,  # Higher std dev indicates more variability
                frequency=len(cpu_values),
                timestamp=datetime.now(),
                metadata={"resource_type": "cpu"}
            )
            patterns.append(pattern)
        
        if memory_values:
            avg_memory = np.mean(memory_values)
            std_memory = np.std(memory_values)
            
            pattern = PerformancePattern(
                pattern_id=f"resource_mem_{uuid.uuid4().hex[:8]}",
                template_name=template_name,
                pattern_type="resource_usage",
                description=f"Memory usage: avg={avg_memory:.1%}, std={std_memory:.2f}",
                correlation_data={
                    "metric": "memory",
                    "average": avg_memory,
                    "std_deviation": std_memory,
                    "sample_size": len(memory_values)
                },
                impact_score=std_memory,
                frequency=len(memory_values),
                timestamp=datetime.now(),
                metadata={"resource_type": "memory"}
            )
            patterns.append(pattern)
        
        if time_values:
            avg_time = np.mean(time_values)
            std_time = np.std(time_values)
            
            pattern = PerformancePattern(
                pattern_id=f"perf_time_{uuid.uuid4().hex[:8]}",
                template_name=template_name,
                pattern_type="timing",
                description=f"Execution time: avg={avg_time:.2f}s, std={std_time:.2f}",
                correlation_data={
                    "metric": "execution_time",
                    "average": avg_time,
                    "std_deviation": std_time,
                    "sample_size": len(time_values)
                },
                impact_score=std_time,
                frequency=len(time_values),
                timestamp=datetime.now(),
                metadata={"metric_type": "execution_time"}
            )
            patterns.append(pattern)
        
        return patterns


class SuccessPatternLearner(ExecutionLearningEngine):
    """Learns from successful execution patterns."""
    
    def __init__(self, template_registry: TemplateRegistry):
        self.template_registry = template_registry
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.success_patterns: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    
    async def learn_from_execution(
        self,
        execution_record: ExecutionRecord
    ) -> List[LearningInsight]:
        """Learn from successful execution patterns."""
        insights = []
        
        # Store successful execution patterns
        if execution_record.success:
            template_key = execution_record.template_name
            self.success_patterns[template_key].append({
                "parameters": execution_record.parameters,
                "execution_time": execution_record.execution_time,
                "resource_usage": execution_record.resource_usage,
                "user_satisfaction": execution_record.user_satisfaction,
                "timestamp": execution_record.start_time
            })
        
        # Keep only recent successful executions
        template_key = execution_record.template_name
        if len(self.success_patterns[template_key]) > 50:
            self.success_patterns[template_key] = self.success_patterns[template_key][-50:]
        
        # Analyze successful patterns if we have enough data
        successful_records = self.success_patterns[template_key]
        if len(successful_records) >= 10:
            # Find common parameter combinations in successful executions
            param_combinations = Counter()
            for record in successful_records:
                # Create a hashable representation of parameters
                param_tuple = tuple(sorted((k, str(v)) for k, v in record["parameters"].items()))
                param_combinations[param_tuple] += 1
            
            # Look for frequently successful parameter combinations
            for param_combo, count in param_combinations.most_common(3):
                if count >= 3:  # At least 3 times successful
                    param_dict = dict(param_combo)
                    
                    insight = LearningInsight(
                        insight_id=f"success_pattern_{uuid.uuid4().hex[:8]}",
                        insight_type=LearningEventType.PERFORMANCE_IMPROVEMENT,
                        description=f"Parameter combination successful {count} times: {param_dict}",
                        template_name=template_key,
                        parameters=param_dict,
                        conditions={
                            "success_count": count,
                            "total_success_records": len(successful_records)
                        },
                        recommendations=[
                            f"Consider suggesting these parameter values: {param_dict}",
                            f"These parameters led to {count} successful executions"
                        ],
                        confidence=count / len(successful_records),
                        outcome=LearningOutcome.POSITIVE,
                        timestamp=datetime.now(),
                        supporting_data=successful_records[-count:],  # Last 'count' records
                        metadata={"pattern_frequency": count}
                    )
                    insights.append(insight)
        
        return insights
    
    async def analyze_execution_patterns(
        self,
        template_name: str,
        execution_records: List[ExecutionRecord]
    ) -> List[PerformancePattern]:
        """Analyze success pattern correlations."""
        patterns = []
        
        # Separate successful and failed executions
        successful = [rec for rec in execution_records if rec.success and rec.template_name == template_name]
        failed = [rec for rec in execution_records if not rec.success and rec.template_name == template_name]
        
        if len(successful) < 5 or len(failed) < 2:
            return []  # Need both successful and failed examples
        
        # Analyze differences between successful and failed executions
        success_params = [rec.parameters for rec in successful]
        fail_params = [rec.parameters for rec in failed]
        
        # Find parameters that differ significantly between success and failure
        all_param_names = set()
        for params in success_params + fail_params:
            all_param_names.update(params.keys())
        
        for param_name in all_param_names:
            success_values = [params.get(param_name) for params in success_params if param_name in params]
            fail_values = [params.get(param_name) for params in fail_params if param_name in params]
            
            # Count occurrences of each value in success vs failure
            success_counts = Counter(str(v) for v in success_values if v is not None)
            fail_counts = Counter(str(v) for v in fail_values if v is not None)
            
            # Calculate success rates for each value
            for value in set(success_counts.keys()) | set(fail_counts.keys()):
                success_count = success_counts.get(value, 0)
                fail_count = fail_counts.get(value, 0)
                total = success_count + fail_count
                
                if total >= 3:  # At least 3 occurrences
                    success_rate = success_count / total if total > 0 else 0
                    
                    if success_rate >= 0.8 or success_rate <= 0.2:
                        pattern_strength = abs(success_rate - 0.5) * 2
                        
                        pattern = PerformancePattern(
                            pattern_id=f"success_corr_{uuid.uuid4().hex[:8]}",
                            template_name=template_name,
                            pattern_type="success_correlation",
                            description=f"Parameter '{param_name}' value '{value}' has {success_rate:.1%} success rate",
                            correlation_data={
                                "parameter_name": param_name,
                                "parameter_value": value,
                                "success_rate": success_rate,
                                "success_count": success_count,
                                "fail_count": fail_count
                            },
                            impact_score=pattern_strength,
                            frequency=total,
                            timestamp=datetime.now(),
                            metadata={"correlation_direction": "positive" if success_rate >= 0.8 else "negative"}
                        )
                        
                        patterns.append(pattern)
        
        return patterns


class ExecutionLearningManager:
    """Main manager for learning from executions."""
    
    def __init__(
        self,
        template_registry: TemplateRegistry,
        profile_manager: Optional[UserProfileManager] = None
    ):
        self.template_registry = template_registry
        self.profile_manager = profile_manager
        self.logger = logging.getLogger(f"{__name__}.ExecutionLearningManager")
        
        # Initialize learners
        self.learners = [
            ParameterCorrelationLearner(template_registry),
            ResourceOptimizationLearner(template_registry),
            SuccessPatternLearner(template_registry)
        ]
        
        # Store execution records
        self.execution_records: List[ExecutionRecord] = []
        self.learning_insights: List[LearningInsight] = []
        self.performance_patterns: List[PerformancePattern] = []
        
        # Store execution history by template
        self.template_execution_history: Dict[str, List[ExecutionRecord]] = defaultdict(list)
    
    async def record_execution(
        self,
        template_name: str,
        user_id: str,
        parameters: Dict[str, Any],
        success: bool,
        execution_time: float,
        resource_usage: Optional[Dict[str, float]] = None,
        output_size: int = 0,
        error_message: Optional[str] = None,
        user_satisfaction: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Record a template execution for learning."""
        execution_id = f"exec_{uuid.uuid4().hex[:8]}"
        
        record = ExecutionRecord(
            execution_id=execution_id,
            template_name=template_name,
            user_id=user_id,
            parameters=parameters,
            success=success,
            execution_time=execution_time,
            resource_usage=resource_usage or {},
            output_size=output_size,
            error_message=error_message,
            end_time=datetime.now(),
            user_satisfaction=user_satisfaction,
            metadata=metadata or {}
        )
        
        # Store the record
        self.execution_records.append(record)
        self.template_execution_history[template_name].append(record)
        
        # Keep only recent records (last 1000)
        if len(self.execution_records) > 1000:
            self.execution_records = self.execution_records[-1000:]
        
        # Keep only recent records per template (last 100 per template)
        if len(self.template_execution_history[template_name]) > 100:
            self.template_execution_history[template_name] = self.template_execution_history[template_name][-100:]
        
        # Learn from this execution
        await self.learn_from_single_execution(record)
        
        self.logger.info(f"Recorded execution {execution_id} for template {template_name}, success: {success}")
        
        return execution_id
    
    async def learn_from_single_execution(self, execution_record: ExecutionRecord):
        """Learn from a single execution record."""
        all_insights = []
        
        # Apply each learner
        for learner in self.learners:
            try:
                insights = await learner.learn_from_execution(execution_record)
                all_insights.extend(insights)
            except Exception as e:
                self.logger.error(f"Error in learner {type(learner).__name__}: {e}")
                continue
        
        # Store insights
        self.learning_insights.extend(all_insights)
        
        # Keep only recent insights (last 500)
        if len(self.learning_insights) > 500:
            self.learning_insights = self.learning_insights[-500:]
        
        self.logger.info(f"Generated {len(all_insights)} insights from execution {execution_record.execution_id}")
    
    async def analyze_template_performance(
        self,
        template_name: str,
        time_window_hours: int = 24
    ) -> Dict[str, Any]:
        """Analyze performance of a template over a time window."""
        # Get recent executions for this template
        cutoff_time = datetime.now() - timedelta(hours=time_window_hours)
        recent_executions = [
            rec for rec in self.template_execution_history[template_name]
            if rec.start_time >= cutoff_time
        ]
        
        if not recent_executions:
            return {
                "template_name": template_name,
                "time_window_hours": time_window_hours,
                "executions_count": 0,
                "success_rate": 0.0,
                "avg_execution_time": 0.0,
                "avg_resource_usage": {},
                "insights_count": 0,
                "patterns_count": 0
            }
        
        # Calculate metrics
        execution_count = len(recent_executions)
        successful_count = sum(1 for rec in recent_executions if rec.success)
        success_rate = successful_count / execution_count if execution_count > 0 else 0.0
        
        execution_times = [rec.execution_time for rec in recent_executions]
        avg_execution_time = sum(execution_times) / len(execution_times) if execution_times else 0.0
        
        # Aggregate resource usage
        resource_totals = defaultdict(float)
        resource_counts = defaultdict(int)
        for rec in recent_executions:
            for resource, value in rec.resource_usage.items():
                resource_totals[resource] += value
                resource_counts[resource] += 1
        
        avg_resource_usage = {
            resource: resource_totals[resource] / resource_counts[resource]
            for resource in resource_totals
        }
        
        # Get related insights and patterns
        related_insights = [
            insight for insight in self.learning_insights
            if insight.template_name == template_name
        ]
        
        related_patterns = [
            pattern for pattern in self.performance_patterns
            if pattern.template_name == template_name
        ]
        
        return {
            "template_name": template_name,
            "time_window_hours": time_window_hours,
            "executions_count": execution_count,
            "success_rate": success_rate,
            "avg_execution_time": avg_execution_time,
            "avg_resource_usage": avg_resource_usage,
            "insights_count": len(related_insights),
            "patterns_count": len(related_patterns),
            "recent_executions": [
                {
                    "execution_id": rec.execution_id,
                    "success": rec.success,
                    "execution_time": rec.execution_time,
                    "timestamp": rec.start_time.isoformat()
                }
                for rec in recent_executions[-5:]  # Last 5 executions
            ]
        }
    
    async def get_learning_insights(
        self,
        template_name: Optional[str] = None,
        insight_type: Optional[LearningEventType] = None,
        min_confidence: float = 0.5
    ) -> List[LearningInsight]:
        """Get learning insights, optionally filtered."""
        insights = self.learning_insights
        
        if template_name:
            insights = [insight for insight in insights if insight.template_name == template_name]
        
        if insight_type:
            insights = [insight for insight in insights if insight.insight_type == insight_type]
        
        # Filter by confidence
        insights = [insight for insight in insights if insight.confidence >= min_confidence]
        
        # Sort by confidence (descending)
        insights.sort(key=lambda x: x.confidence, reverse=True)
        
        return insights
    
    async def get_performance_patterns(
        self,
        template_name: Optional[str] = None,
        pattern_type: Optional[str] = None,
        min_impact: float = 0.3
    ) -> List[PerformancePattern]:
        """Get performance patterns, optionally filtered."""
        patterns = self.performance_patterns
        
        if template_name:
            patterns = [pattern for pattern in patterns if pattern.template_name == template_name]
        
        if pattern_type:
            patterns = [pattern for pattern in patterns if pattern.pattern_type == pattern_type]
        
        # Filter by impact score
        patterns = [pattern for pattern in patterns if pattern.impact_score >= min_impact]
        
        # Sort by impact score (descending)
        patterns.sort(key=lambda x: x.impact_score, reverse=True)
        
        return patterns
    
    async def run_periodic_analysis(self):
        """Run periodic analysis of all templates."""
        self.logger.info("Starting periodic analysis of execution patterns...")
        
        all_patterns = []
        
        # Analyze each template with sufficient execution history
        for template_name in self.template_execution_history:
            template_executions = self.template_execution_history[template_name]
            
            if len(template_executions) >= 5:  # Need minimum data
                # Apply each learner's pattern analysis
                for learner in self.learners:
                    try:
                        patterns = await learner.analyze_execution_patterns(
                            template_name, template_executions
                        )
                        all_patterns.extend(patterns)
                    except Exception as e:
                        self.logger.error(f"Error in pattern analysis for {template_name} with {type(learner).__name__}: {e}")
                        continue
        
        # Store the patterns
        self.performance_patterns.extend(all_patterns)
        
        # Keep only recent patterns (last 500)
        if len(self.performance_patterns) > 500:
            self.performance_patterns = self.performance_patterns[-500:]
        
        self.logger.info(f"Periodic analysis completed. Generated {len(all_patterns)} new patterns.")
    
    async def apply_learning_to_template(
        self,
        template_name: str
    ) -> Dict[str, Any]:
        """Apply learned insights to improve a template."""
        # Get relevant insights for this template
        insights = await self.get_learning_insights(template_name, min_confidence=0.6)
        
        # Get relevant patterns for this template
        patterns = await self.get_performance_patterns(template_name, min_impact=0.5)
        
        # Generate recommendations
        recommendations = []
        
        for insight in insights:
            recommendations.extend(insight.recommendations)
        
        # Create improvement plan
        improvement_plan = {
            "template_name": template_name,
            "insights_count": len(insights),
            "patterns_count": len(patterns),
            "recommendations": list(set(recommendations)),  # Remove duplicates
            "high_confidence_insights": [i.description for i in insights if i.confidence >= 0.8],
            "significant_patterns": [p.description for p in patterns if p.impact_score >= 0.7]
        }
        
        return improvement_plan
    
    async def get_user_execution_summary(
        self,
        user_id: str
    ) -> Dict[str, Any]:
        """Get summary of a user's template executions."""
        user_executions = [
            rec for rec in self.execution_records
            if rec.user_id == user_id
        ]
        
        if not user_executions:
            return {
                "user_id": user_id,
                "total_executions": 0,
                "success_rate": 0.0,
                "favorite_templates": [],
                "avg_execution_time": 0.0
            }
        
        total_executions = len(user_executions)
        successful_executions = sum(1 for rec in user_executions if rec.success)
        success_rate = successful_executions / total_executions if total_executions > 0 else 0.0
        
        # Calculate favorite templates
        template_counts = Counter(rec.template_name for rec in user_executions)
        favorite_templates = [tpl for tpl, count in template_counts.most_common(5)]
        
        execution_times = [rec.execution_time for rec in user_executions]
        avg_execution_time = sum(execution_times) / len(execution_times) if execution_times else 0.0
        
        return {
            "user_id": user_id,
            "total_executions": total_executions,
            "success_rate": success_rate,
            "favorite_templates": favorite_templates,
            "avg_execution_time": avg_execution_time,
            "recent_executions": [
                {
                    "template_name": rec.template_name,
                    "success": rec.success,
                    "execution_time": rec.execution_time,
                    "timestamp": rec.start_time.isoformat()
                }
                for rec in user_executions[-5:]  # Last 5 executions
            ]
        }


class ExecutionLearningTool:
    """Tool for managing execution learning."""
    
    def __init__(self, learning_manager: ExecutionLearningManager):
        self.learning_manager = learning_manager
        self.logger = logging.getLogger(f"{__name__}.ExecutionLearningTool")
    
    async def record_execution(
        self,
        template_name: str,
        user_id: str,
        parameters: Dict[str, Any],
        success: bool,
        execution_time: float,
        resource_usage: Optional[Dict[str, float]] = None,
        output_size: int = 0,
        error_message: Optional[str] = None,
        user_satisfaction: Optional[float] = None
    ) -> Dict[str, Any]:
        """Record a template execution."""
        try:
            execution_id = await self.learning_manager.record_execution(
                template_name=template_name,
                user_id=user_id,
                parameters=parameters,
                success=success,
                execution_time=execution_time,
                resource_usage=resource_usage,
                output_size=output_size,
                error_message=error_message,
                user_satisfaction=user_satisfaction
            )
            
            return {
                "success": True,
                "execution_id": execution_id,
                "message": f"Recorded execution for template {template_name}"
            }
        except Exception as e:
            self.logger.error(f"Error recording execution: {e}")
            return {
                "success": False,
                "error": f"Error recording execution: {str(e)}"
            }
    
    async def analyze_template(
        self,
        template_name: str,
        time_window_hours: int = 24
    ) -> Dict[str, Any]:
        """Analyze performance of a template."""
        try:
            analysis = await self.learning_manager.analyze_template_performance(
                template_name, time_window_hours
            )
            
            return {
                "success": True,
                "template_name": template_name,
                "analysis": analysis
            }
        except Exception as e:
            self.logger.error(f"Error analyzing template: {e}")
            return {
                "success": False,
                "error": f"Error analyzing template: {str(e)}",
                "template_name": template_name
            }
    
    async def get_insights(
        self,
        template_name: Optional[str] = None,
        min_confidence: float = 0.5
    ) -> Dict[str, Any]:
        """Get learning insights."""
        try:
            insights = await self.learning_manager.get_learning_insights(
                template_name, min_confidence=min_confidence
            )
            
            formatted_insights = []
            for insight in insights[:10]:  # Limit to top 10
                formatted_insights.append({
                    "insight_id": insight.insight_id,
                    "insight_type": insight.insight_type.value,
                    "description": insight.description,
                    "template_name": insight.template_name,
                    "confidence": insight.confidence,
                    "outcome": insight.outcome.value,
                    "recommendations": insight.recommendations,
                    "timestamp": insight.timestamp.isoformat()
                })
            
            return {
                "success": True,
                "insights_count": len(formatted_insights),
                "insights": formatted_insights
            }
        except Exception as e:
            self.logger.error(f"Error getting insights: {e}")
            return {
                "success": False,
                "error": f"Error getting insights: {str(e)}"
            }
    
    async def get_improvement_plan(
        self,
        template_name: str
    ) -> Dict[str, Any]:
        """Get improvement plan for a template based on learning."""
        try:
            plan = await self.learning_manager.apply_learning_to_template(template_name)
            
            return {
                "success": True,
                "template_name": template_name,
                "improvement_plan": plan
            }
        except Exception as e:
            self.logger.error(f"Error getting improvement plan: {e}")
            return {
                "success": False,
                "error": f"Error getting improvement plan: {str(e)}",
                "template_name": template_name
            }
    
    async def get_user_summary(
        self,
        user_id: str
    ) -> Dict[str, Any]:
        """Get execution summary for a user."""
        try:
            summary = await self.learning_manager.get_user_execution_summary(user_id)
            
            return {
                "success": True,
                "user_id": user_id,
                "summary": summary
            }
        except Exception as e:
            self.logger.error(f"Error getting user summary: {e}")
            return {
                "success": False,
                "error": f"Error getting user summary: {str(e)}",
                "user_id": user_id
            }
    
    def to_param(self) -> Dict[str, Any]:
        """Convert to parameter format for tool registration."""
        return {
            "type": "function",
            "function": {
                "name": "execution_learning_tool",
                "description": "Learn from template executions to improve performance",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["record_execution", "analyze_template", "get_insights", "get_improvement_plan", "get_user_summary"],
                            "description": "Action to perform"
                        },
                        "template_name": {
                            "type": "string",
                            "description": "Name of the template (required for most actions)"
                        },
                        "user_id": {
                            "type": "string",
                            "description": "User ID (for record_execution and get_user_summary)"
                        },
                        "parameters": {
                            "type": "object",
                            "description": "Template parameters (for record_execution)"
                        },
                        "success": {
                            "type": "boolean",
                            "description": "Whether execution was successful (for record_execution)"
                        },
                        "execution_time": {
                            "type": "number",
                            "description": "Execution time in seconds (for record_execution)"
                        },
                        "resource_usage": {
                            "type": "object",
                            "description": "Resource usage metrics (for record_execution)"
                        },
                        "time_window_hours": {
                            "type": "integer",
                            "description": "Time window for analysis in hours (for analyze_template)",
                            "default": 24
                        },
                        "min_confidence": {
                            "type": "number",
                            "description": "Minimum confidence for insights (for get_insights)",
                            "default": 0.5
                        }
                    },
                    "required": ["action"]
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
        
        # Create learning manager
        template_registry = MockTemplateRegistry()
        learning_manager = ExecutionLearningManager(template_registry)
        
        print("Recording template executions...")
        
        # Record some sample executions
        await learning_manager.record_execution(
            template_name="Research Analysis Workflow",
            user_id="user_123",
            parameters={"topic": "AI developments"},
            success=True,
            execution_time=120.5,
            resource_usage={"cpu": 0.45, "memory": 0.6},
            output_size=2500,
            user_satisfaction=0.8
        )
        
        await learning_manager.record_execution(
            template_name="Research Analysis Workflow",
            user_id="user_123",
            parameters={"topic": "Market trends"},
            success=True,
            execution_time=95.2,
            resource_usage={"cpu": 0.35, "memory": 0.4},
            output_size=1800,
            user_satisfaction=0.9
        )
        
        await learning_manager.record_execution(
            template_name="Research Analysis Workflow",
            user_id="user_456",
            parameters={"topic": "Complex analysis"},
            success=False,
            execution_time=300.0,
            resource_usage={"cpu": 0.85, "memory": 0.9},
            output_size=0,
            error_message="Timeout error",
            user_satisfaction=0.2
        )
        
        print("Analyzing template performance...")
        
        # Analyze template performance
        analysis = await learning_manager.analyze_template_performance("Research Analysis Workflow")
        
        print(f"Template: {analysis['template_name']}")
        print(f"Executions: {analysis['executions_count']}")
        print(f"Success rate: {analysis['success_rate']:.2f}")
        print(f"Avg execution time: {analysis['avg_execution_time']:.2f}s")
        print(f"Avg resource usage: {analysis['avg_resource_usage']}")
        print(f"Related insights: {analysis['insights_count']}")
        
        print("\nGetting learning insights...")
        
        # Get insights
        insights = await learning_manager.get_learning_insights("Research Analysis Workflow", min_confidence=0.5)
        
        print(f"Found {len(insights)} insights:")
        for i, insight in enumerate(insights[:3], 1):  # Show first 3
            print(f"\n{i}. {insight.insight_type.value}")
            print(f"   Description: {insight.description}")
            print(f"   Confidence: {insight.confidence:.2f}")
            print(f"   Outcome: {insight.outcome.value}")
            print(f"   Recommendations: {insight.recommendations}")
        
        print("\nGenerating improvement plan...")
        
        # Get improvement plan
        plan = await learning_manager.apply_learning_to_template("Research Analysis Workflow")
        
        print(f"Improvement plan for {plan['template_name']}:")
        print(f"  Insights: {plan['insights_count']}")
        print(f"  Patterns: {plan['patterns_count']}")
        print(f"  Recommendations: {len(plan['recommendations'])}")
        for rec in plan['recommendations']:
            print(f"    - {rec}")
        
        print("\nGetting user summary...")
        
        # Get user summary
        user_summary = await learning_manager.get_user_execution_summary("user_123")
        
        print(f"User summary for {user_summary['user_id']}:")
        print(f"  Total executions: {user_summary['total_executions']}")
        print(f"  Success rate: {user_summary['success_rate']:.2f}")
        print(f"  Avg execution time: {user_summary['avg_execution_time']:.2f}s")
        print(f"  Favorite templates: {user_summary['favorite_templates']}")
        
        print("\nRunning periodic analysis...")
        
        # Run periodic analysis
        await learning_manager.run_periodic_analysis()
        
        print("Periodic analysis completed.")
        
        print("\nExample completed successfully!")
    
    asyncio.run(example())