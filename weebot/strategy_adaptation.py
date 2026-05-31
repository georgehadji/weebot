"""
Strategy Adaptation System for Weebot

This module provides dynamic strategy adjustment capabilities
based on task outcomes, performance metrics, and environmental factors.
"""
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timedelta
import asyncio
import logging
from weebot.workflow_planner import WorkflowPlan, PlannedTask
from weebot.nlp_understanding import IntentRecognitionResult


class AdaptationTrigger(Enum):
    """Events that can trigger strategy adaptation."""
    PERFORMANCE_BELOW_THRESHOLD = "performance_below_threshold"
    RESOURCE_CONSTRAINT_DETECTED = "resource_constraint_detected"
    USER_FEEDBACK_RECEIVED = "user_feedback_received"
    TASK_COMPLEXITY_MISMATCH = "task_complexity_mismatch"
    ENVIRONMENT_CHANGE = "environment_change"
    RECURRING_PATTERN_DETECTED = "recurring_pattern_detected"


class StrategyType(Enum):
    """Types of strategies that can be adapted."""
    TASK_SCHEDULING = "task_scheduling"
    RESOURCE_ALLOCATION = "resource_allocation"
    AGENT_SELECTION = "agent_selection"
    WORKFLOW_STRUCTURE = "workflow_structure"
    TOOL_CHOICE = "tool_choice"
    ERROR_HANDLING = "error_handling"


@dataclass
class PerformanceMetric:
    """Represents a performance metric for evaluation."""
    name: str
    value: float
    threshold: float
    direction: str  # "higher_is_better" or "lower_is_better"
    timestamp: datetime
    context: Dict[str, Any]  # Additional context for the metric


@dataclass
class AdaptationRecommendation:
    """A recommended adaptation to the current strategy."""
    strategy_type: StrategyType
    action: str  # What to change
    parameters: Dict[str, Any]  # Parameters for the change
    confidence: float  # 0.0 to 1.0
    reason: str  # Why this adaptation is recommended
    trigger: AdaptationTrigger  # What triggered this recommendation


class StrategyAdapter:
    """
    Adaptive system that modifies strategies based on performance
    and environmental feedback.
    """
    
    def __init__(self):
        self.performance_history: List[PerformanceMetric] = []
        self.adaptation_history: List[AdaptationRecommendation] = []
        self.current_strategies: Dict[StrategyType, Dict[str, Any]] = {
            StrategyType.TASK_SCHEDULING: {"concurrency_limit": 4, "priority_algorithm": "fifo"},
            StrategyType.RESOURCE_ALLOCATION: {"cpu_quota": 0.8, "memory_limit_mb": 1024},
            StrategyType.AGENT_SELECTION: {"selection_method": "capability_match", "fallback_strategy": "generalist"},
            StrategyType.WORKFLOW_STRUCTURE: {"optimization_level": "moderate", "parallelization": True},
            StrategyType.TOOL_CHOICE: {"preference_weight": "reliability", "fallback_enabled": True},
            StrategyType.ERROR_HANDLING: {"retry_attempts": 3, "timeout_multiplier": 1.5}
        }
        self.performance_thresholds = {
            "success_rate": 0.8,
            "average_completion_time_factor": 1.2,  # Factor relative to estimate
            "resource_utilization": 0.9,
            "user_satisfaction": 0.7
        }
        self.logger = logging.getLogger(__name__)
    
    def record_performance_metric(self, metric: PerformanceMetric):
        """Record a performance metric for future analysis."""
        self.performance_history.append(metric)
        
        # Keep only recent metrics (last 100)
        if len(self.performance_history) > 100:
            self.performance_history = self.performance_history[-100:]
        
        # Check if adaptation is needed
        recommendations = self._analyze_performance_and_recommend_adaptations([metric])
        for rec in recommendations:
            self.adaptation_history.append(rec)
            self.logger.info(f"Adaptation recommended: {rec.action} for {rec.strategy_type.value} - {rec.reason}")
    
    def get_adaptation_recommendations(
        self, 
        trigger: Optional[AdaptationTrigger] = None,
        strategy_types: Optional[List[StrategyType]] = None
    ) -> List[AdaptationRecommendation]:
        """
        Get adaptation recommendations based on recent performance.
        
        Args:
            trigger: Specific trigger to consider
            strategy_types: Specific strategy types to analyze
            
        Returns:
            List of adaptation recommendations
        """
        recent_metrics = self.performance_history[-20:] if self.performance_history else []
        
        recommendations = self._analyze_performance_and_recommend_adaptations(
            recent_metrics, trigger, strategy_types
        )
        
        # Update adaptation history
        for rec in recommendations:
            self.adaptation_history.append(rec)
        
        return recommendations
    
    def apply_adaptation(self, recommendation: AdaptationRecommendation) -> bool:
        """
        Apply an adaptation recommendation to the current strategies.
        
        Args:
            recommendation: The recommendation to apply
            
        Returns:
            True if successfully applied, False otherwise
        """
        try:
            # Update the current strategy with the recommended changes
            if recommendation.strategy_type in self.current_strategies:
                self.current_strategies[recommendation.strategy_type].update(recommendation.parameters)
                
                self.logger.info(f"Applied adaptation: {recommendation.action} for {recommendation.strategy_type.value}")
                return True
            else:
                self.logger.warning(f"No current strategy found for type: {recommendation.strategy_type.value}")
                return False
        except Exception as e:
            self.logger.error(f"Failed to apply adaptation: {e}")
            return False
    
    def _analyze_performance_and_recommend_adaptations(
        self,
        metrics: List[PerformanceMetric],
        trigger: Optional[AdaptationTrigger] = None,
        strategy_types: Optional[List[StrategyType]] = None
    ) -> List[AdaptationRecommendation]:
        """Analyze performance metrics and recommend adaptations."""
        recommendations = []
        
        # Filter metrics if specific strategy types are requested
        if strategy_types:
            filtered_metrics = [m for m in metrics if any(st.value in m.name for st in strategy_types)]
        else:
            filtered_metrics = metrics
        
        # Analyze each metric
        for metric in filtered_metrics:
            # Check if metric is below threshold
            if self._is_metric_below_threshold(metric):
                rec = self._recommend_adaptation_for_metric(metric, trigger)
                if rec:
                    recommendations.append(rec)
        
        # Also look for patterns in the data
        pattern_recommendations = self._analyze_patterns_and_recommend_adaptations(trigger)
        recommendations.extend(pattern_recommendations)
        
        return recommendations
    
    def _is_metric_below_threshold(self, metric: PerformanceMetric) -> bool:
        """Check if a metric is below its threshold."""
        if metric.direction == "higher_is_better":
            return metric.value < metric.threshold
        else:  # lower_is_better
            return metric.value > metric.threshold
    
    def _recommend_adaptation_for_metric(
        self, 
        metric: PerformanceMetric, 
        trigger: Optional[AdaptationTrigger]
    ) -> Optional[AdaptationRecommendation]:
        """Recommend an adaptation based on a specific metric."""
        trigger_type = trigger or AdaptationTrigger.PERFORMANCE_BELOW_THRESHOLD
        
        # Define recommendations based on metric name
        if "success_rate" in metric.name:
            return AdaptationRecommendation(
                strategy_type=StrategyType.ERROR_HANDLING,
                action="increase_retry_attempts",
                parameters={"retry_attempts": min(10, self.current_strategies[StrategyType.ERROR_HANDLING].get("retry_attempts", 3) + 1)},
                confidence=0.8,
                reason=f"Success rate below threshold: {metric.value} < {metric.threshold}",
                trigger=trigger_type
            )
        elif "completion_time" in metric.name:
            return AdaptationRecommendation(
                strategy_type=StrategyType.RESOURCE_ALLOCATION,
                action="increase_resource_allocation",
                parameters={"cpu_quota": min(1.0, self.current_strategies[StrategyType.RESOURCE_ALLOCATION].get("cpu_quota", 0.8) + 0.1)},
                confidence=0.7,
                reason=f"Completion time factor too high: {metric.value} > {metric.threshold}",
                trigger=trigger_type
            )
        elif "resource_utilization" in metric.name:
            return AdaptationRecommendation(
                strategy_type=StrategyType.RESOURCE_ALLOCATION,
                action="adjust_memory_limit",
                parameters={"memory_limit_mb": self.current_strategies[StrategyType.RESOURCE_ALLOCATION].get("memory_limit_mb", 1024) * 1.2},
                confidence=0.75,
                reason=f"Resource utilization high: {metric.value} > {metric.threshold}",
                trigger=trigger_type
            )
        elif "user_satisfaction" in metric.name:
            return AdaptationRecommendation(
                strategy_type=StrategyType.AGENT_SELECTION,
                action="change_selection_method",
                parameters={"selection_method": "experience_based"},
                confidence=0.85,
                reason=f"User satisfaction low: {metric.value} < {metric.threshold}",
                trigger=trigger_type
            )
        
        return None
    
    def _analyze_patterns_and_recommend_adaptations(
        self, 
        trigger: Optional[AdaptationTrigger]
    ) -> List[AdaptationRecommendation]:
        """Analyze patterns in performance history and recommend adaptations."""
        recommendations = []
        trigger_type = trigger or AdaptationTrigger.RECURRING_PATTERN_DETECTED
        
        # Look for recurring patterns in the data
        if len(self.performance_history) >= 10:
            # Example: Check if success rate has been consistently declining
            recent_success_rates = [
                m for m in self.performance_history[-10:] 
                if "success_rate" in m.name and m.direction == "higher_is_better"
            ]
            
            if len(recent_success_rates) >= 5:
                # Check if there's a downward trend
                values = [m.value for m in recent_success_rates]
                if len(values) > 1 and values[-1] < values[0] and all(values[i] >= values[i+1] for i in range(len(values)-1)):
                    # Success rate is consistently declining
                    rec = AdaptationRecommendation(
                        strategy_type=StrategyType.ERROR_HANDLING,
                        action="switch_to_more_robust_approach",
                        parameters={
                            "retry_attempts": 5,
                            "timeout_multiplier": 2.0,
                            "fallback_enabled": True
                        },
                        confidence=0.8,
                        reason="Detecting consistent decline in success rate",
                        trigger=trigger_type
                    )
                    recommendations.append(rec)
        
        return recommendations
    
    def adapt_workflow_plan(
        self, 
        plan: WorkflowPlan, 
        intent_result: Optional[IntentRecognitionResult] = None
    ) -> WorkflowPlan:
        """
        Adapt a workflow plan based on current strategies and historical performance.
        
        Args:
            plan: The original workflow plan
            intent_result: Optional intent analysis for context
            
        Returns:
            Adapted workflow plan
        """
        # Create a copy of the plan to modify
        adapted_tasks = []
        
        for task in plan.tasks:
            # Apply adaptations based on current strategies
            adapted_task = self._adapt_task(task)
            adapted_tasks.append(adapted_task)
        
        # Create adapted plan
        adapted_plan = WorkflowPlan(
            id=f"{plan.id}_adapted_{datetime.now().strftime('%H%M%S')}",
            name=f"{plan.name} (Adapted)",
            description=f"Adapted version of: {plan.description}",
            tasks=adapted_tasks,
            created_at=datetime.now(),
            estimated_total_duration=plan.estimated_total_duration,
            dependencies=plan.dependencies
        )
        
        # Apply structural adaptations if needed
        adapted_plan = self._apply_structural_adaptations(adapted_plan, intent_result)
        
        return adapted_plan
    
    def _adapt_task(self, task: PlannedTask) -> PlannedTask:
        """Apply strategy-based adaptations to a single task."""
        # Modify task based on current resource allocation strategy
        resource_strategy = self.current_strategies[StrategyType.RESOURCE_ALLOCATION]
        cpu_quota = resource_strategy.get("cpu_quota", 0.8)
        
        # Adjust estimated duration based on resource allocation
        adjusted_duration = int(task.estimated_duration_minutes * (1.0 / cpu_quota))
        
        # Modify task based on error handling strategy
        error_strategy = self.current_strategies[StrategyType.ERROR_HANDLING]
        retry_attempts = error_strategy.get("retry_attempts", 3)
        
        # Add retry information to parameters
        new_parameters = task.parameters.copy()
        new_parameters["max_retries"] = retry_attempts
        
        return PlannedTask(
            id=task.id,
            name=task.name,
            description=task.description,
            category=task.category,
            required_tools=task.required_tools,
            dependencies=task.dependencies,
            estimated_duration_minutes=adjusted_duration,
            priority=task.priority,
            parameters=new_parameters
        )
    
    def _apply_structural_adaptations(
        self, 
        plan: WorkflowPlan, 
        intent_result: Optional[IntentRecognitionResult]
    ) -> WorkflowPlan:
        """Apply structural adaptations to the workflow plan."""
        # Check if parallelization should be adjusted based on current strategies
        workflow_strategy = self.current_strategies[StrategyType.WORKFLOW_STRUCTURE]
        should_parallelize = workflow_strategy.get("parallelization", True)
        
        if not should_parallelize:
            # Convert to sequential execution by updating dependencies
            new_dependencies = {}
            for i, task in enumerate(plan.tasks):
                if i == 0:
                    new_dependencies[task.id] = []
                else:
                    # Each task depends on the previous one
                    new_dependencies[task.id] = [plan.tasks[i-1].id]
            
            plan.dependencies = new_dependencies
        
        return plan
    
    def get_current_strategy_summary(self) -> Dict[str, Any]:
        """Get a summary of current strategies."""
        return {
            "timestamp": datetime.now(),
            "strategy_count": len(self.current_strategies),
            "recent_adaptations": len(self.adaptation_history[-10:]) if self.adaptation_history else 0,
            "performance_metrics_count": len(self.performance_history),
            "current_strategies": {
                k.value: v for k, v in self.current_strategies.items()
            }
        }


# Example usage
if __name__ == "__main__":
    adapter = StrategyAdapter()
    
    # Simulate recording some performance metrics
    from weebot.workflow_planner import PlannedTask, TaskCategory, WorkflowPlan
    
    # Create a sample task
    task = PlannedTask(
        id="task_1",
        name="sample_task",
        description="A sample task for testing",
        category=TaskCategory.RESEARCH,
        required_tools=["web_search"],
        dependencies=[],
        estimated_duration_minutes=15,
        priority=1,
        parameters={"query": "test query"}
    )
    
    # Create a sample plan
    plan = WorkflowPlan(
        id="plan_1",
        name="Sample Plan",
        description="A sample plan for testing",
        tasks=[task],
        created_at=datetime.now(),
        estimated_total_duration=15,
        dependencies={"task_1": []}
    )
    
    # Record some performance metrics
    adapter.record_performance_metric(PerformanceMetric(
        name="success_rate",
        value=0.75,
        threshold=0.8,
        direction="higher_is_better",
        timestamp=datetime.now(),
        context={"task_id": "task_1", "workflow_id": "plan_1"}
    ))
    
    adapter.record_performance_metric(PerformanceMetric(
        name="average_completion_time_factor",
        value=1.5,
        threshold=1.2,
        direction="lower_is_better",
        timestamp=datetime.now(),
        context={"task_id": "task_1", "workflow_id": "plan_1"}
    ))
    
    # Get adaptation recommendations
    recommendations = adapter.get_adaptation_recommendations()
    
    print("Adaptation Recommendations:")
    for rec in recommendations:
        print(f"- {rec.strategy_type.value}: {rec.action}")
        print(f"  Reason: {rec.reason}")
        print(f"  Confidence: {rec.confidence}")
        print(f"  Parameters: {rec.parameters}")
        print()
    
    # Apply adaptations to a plan
    adapted_plan = adapter.adapt_workflow_plan(plan)
    print(f"Original duration: {plan.estimated_total_duration} minutes")
    print(f"Adapted duration: {adapted_plan.estimated_total_duration} minutes")
    
    # Print current strategy summary
    summary = adapter.get_current_strategy_summary()
    print(f"\nCurrent Strategy Summary:")
    print(f"- Strategies configured: {summary['strategy_count']}")
    print(f"- Recent adaptations: {summary['recent_adaptations']}")
    print(f"- Performance metrics: {summary['performance_metrics_count']}")