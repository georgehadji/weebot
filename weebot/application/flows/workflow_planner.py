"""
Automated Workflow Planner for Weebot

This module provides intelligent workflow planning capabilities
to automatically generate task sequences based on user requirements.
"""
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum
import re
from datetime import datetime
from weebot.application.services.nlp_understanding import IntentRecognitionResult, IntentType
from weebot.core.dependency_graph import DependencyGraph


class TaskCategory(Enum):
    """Categories of tasks that can be planned."""
    RESEARCH = "research"
    DATA_ANALYSIS = "data_analysis"
    CONTENT_CREATION = "content_creation"
    SYSTEM_AUTOMATION = "system_automation"
    COMMUNICATION = "communication"
    PLANNING = "planning"
    OTHER = "other"


@dataclass
class PlannedTask:
    """Represents a planned task in a workflow."""
    id: str
    name: str
    description: str
    category: TaskCategory
    required_tools: List[str]
    dependencies: List[str]  # IDs of tasks this depends on
    estimated_duration_minutes: int
    priority: int  # Lower number means higher priority
    parameters: Dict[str, Any]  # Task-specific parameters


@dataclass
class WorkflowPlan:
    """Represents a complete workflow plan."""
    id: str
    name: str
    description: str
    tasks: List[PlannedTask]
    created_at: datetime
    estimated_total_duration: int  # in minutes
    dependencies: Dict[str, List[str]]  # task_id -> [dependencies]


class WorkflowPlanner:
    """
    Intelligent planner that creates workflow plans based on user requirements.
    
    Uses intent recognition and purpose analysis to generate appropriate
    task sequences with proper dependencies and resource allocation.
    """
    
    def __init__(self):
        # Define task templates for different categories
        self.task_templates = {
            TaskCategory.RESEARCH: [
                {
                    "name": "gather_information",
                    "description": "Collect relevant information on the topic",
                    "required_tools": ["web_search"],
                    "estimated_duration": 15,
                    "priority": 1
                },
                {
                    "name": "analyze_sources",
                    "description": "Evaluate and analyze collected sources",
                    "required_tools": ["read_document", "summarize"],
                    "estimated_duration": 20,
                    "priority": 2
                },
                {
                    "name": "synthesize_findings",
                    "description": "Combine findings into coherent summary",
                    "required_tools": ["summarize", "outline"],
                    "estimated_duration": 25,
                    "priority": 3
                }
            ],
            TaskCategory.DATA_ANALYSIS: [
                {
                    "name": "load_data",
                    "description": "Load and prepare data for analysis",
                    "required_tools": ["file_editor"],
                    "estimated_duration": 10,
                    "priority": 1
                },
                {
                    "name": "clean_data",
                    "description": "Clean and preprocess the data",
                    "required_tools": ["python_tool"],
                    "estimated_duration": 20,
                    "priority": 2
                },
                {
                    "name": "analyze_data",
                    "description": "Perform statistical analysis",
                    "required_tools": ["python_tool", "advanced_browser"],
                    "estimated_duration": 30,
                    "priority": 3
                },
                {
                    "name": "visualize_results",
                    "description": "Create visualizations of results",
                    "required_tools": ["python_tool", "advanced_browser"],
                    "estimated_duration": 25,
                    "priority": 4
                }
            ],
            TaskCategory.CONTENT_CREATION: [
                {
                    "name": "outline_content",
                    "description": "Create outline for the content",
                    "required_tools": ["outline"],
                    "estimated_duration": 15,
                    "priority": 1
                },
                {
                    "name": "draft_content",
                    "description": "Write initial draft",
                    "required_tools": ["file_editor"],
                    "estimated_duration": 45,
                    "priority": 2
                },
                {
                    "name": "review_content",
                    "description": "Review and edit the content",
                    "required_tools": ["file_editor"],
                    "estimated_duration": 30,
                    "priority": 3
                },
                {
                    "name": "finalize_content",
                    "description": "Finalize and format the content",
                    "required_tools": ["file_editor"],
                    "estimated_duration": 15,
                    "priority": 4
                }
            ],
            TaskCategory.SYSTEM_AUTOMATION: [
                {
                    "name": "identify_processes",
                    "description": "Identify processes to automate",
                    "required_tools": ["file_editor"],
                    "estimated_duration": 20,
                    "priority": 1
                },
                {
                    "name": "design_automation",
                    "description": "Design automation workflow",
                    "required_tools": ["file_editor"],
                    "estimated_duration": 30,
                    "priority": 2
                },
                {
                    "name": "implement_automation",
                    "description": "Implement the automation",
                    "required_tools": ["bash_tool", "python_tool"],
                    "estimated_duration": 60,
                    "priority": 3
                },
                {
                    "name": "test_automation",
                    "description": "Test the automation workflow",
                    "required_tools": ["bash_tool", "python_tool"],
                    "estimated_duration": 30,
                    "priority": 4
                }
            ]
        }
        
        # Define common task dependencies
        self.dependencies = {
            "analyze_sources": ["gather_information"],
            "synthesize_findings": ["analyze_sources"],
            "clean_data": ["load_data"],
            "analyze_data": ["clean_data"],
            "visualize_results": ["analyze_data"],
            "draft_content": ["outline_content"],
            "review_content": ["draft_content"],
            "finalize_content": ["review_content"],
            "design_automation": ["identify_processes"],
            "implement_automation": ["design_automation"],
            "test_automation": ["implement_automation"]
        }
    
    def create_workflow_plan(
        self, 
        user_requirement: str, 
        intent_result: IntentRecognitionResult
    ) -> Optional[WorkflowPlan]:
        """
        Create a workflow plan based on user requirement and intent analysis.
        
        Args:
            user_requirement: The original user requirement
            intent_result: The analyzed intent and purpose
            
        Returns:
            A WorkflowPlan or None if planning fails
        """
        # Map intent to task category
        category = self._map_intent_to_category(intent_result.intent)
        
        if category not in self.task_templates:
            # If no specific template, try to infer from keywords
            category = self._infer_category_from_keywords(user_requirement)
        
        if category not in self.task_templates:
            return None
        
        # Generate tasks based on the category
        tasks = self._generate_tasks_for_category(category, user_requirement, intent_result)
        
        # Create dependencies based on the task sequence
        dependencies = self._create_dependencies(tasks)
        
        # Calculate total estimated duration
        total_duration = sum(task.estimated_duration_minutes for task in tasks)
        
        # Create the workflow plan
        plan = WorkflowPlan(
            id=f"plan_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            name=f"{category.value.title()} Plan",
            description=f"Automated plan for {user_requirement}",
            tasks=tasks,
            created_at=datetime.now(),
            estimated_total_duration=total_duration,
            dependencies=dependencies
        )
        
        return plan
    
    def _map_intent_to_category(self, intent: IntentType) -> TaskCategory:
        """Map an intent to a task category."""
        intent_mapping = {
            IntentType.RESEARCH: TaskCategory.RESEARCH,
            IntentType.ANALYSIS: TaskCategory.DATA_ANALYSIS,
            IntentType.CONTENT_CREATION: TaskCategory.CONTENT_CREATION,
            IntentType.AUTOMATION: TaskCategory.SYSTEM_AUTOMATION,
            IntentType.TASK_EXECUTION: TaskCategory.OTHER,
            IntentType.INFORMATION_REQUEST: TaskCategory.RESEARCH
        }
        
        return intent_mapping.get(intent, TaskCategory.OTHER)
    
    def _infer_category_from_keywords(self, user_requirement: str) -> Optional[TaskCategory]:
        """Infer task category from keywords in the requirement."""
        text_lower = user_requirement.lower()
        
        # Look for keywords that suggest specific categories
        if any(keyword in text_lower for keyword in ["analyze", "data", "statistics", "report", "metrics"]):
            return TaskCategory.DATA_ANALYSIS
        elif any(keyword in text_lower for keyword in ["write", "create", "draft", "blog", "article", "document"]):
            return TaskCategory.CONTENT_CREATION
        elif any(keyword in text_lower for keyword in ["automate", "schedule", "workflow", "process"]):
            return TaskCategory.SYSTEM_AUTOMATION
        elif any(keyword in text_lower for keyword in ["research", "find", "study", "investigate", "explore"]):
            return TaskCategory.RESEARCH
        else:
            return None
    
    def _generate_tasks_for_category(
        self, 
        category: TaskCategory, 
        user_requirement: str, 
        intent_result: IntentRecognitionResult
    ) -> List[PlannedTask]:
        """Generate tasks for a specific category."""
        if category not in self.task_templates:
            return []
        
        template_tasks = self.task_templates[category]
        tasks = []
        
        for i, template_task in enumerate(template_tasks):
            # Create a unique task ID
            task_id = f"task_{category.value}_{i+1}_{template_task['name']}"
            
            # Customize description based on user requirement if possible
            description = template_task["description"]
            if category == TaskCategory.RESEARCH:
                if "topic" in intent_result.entities:
                    description = description.replace("the topic", intent_result.entities["topic"])
            
            # Create parameters based on intent analysis
            parameters = self._create_task_parameters(template_task["name"], intent_result)
            
            task = PlannedTask(
                id=task_id,
                name=template_task["name"],
                description=description,
                category=category,
                required_tools=template_task["required_tools"],
                dependencies=[],  # Will be filled in later
                estimated_duration_minutes=template_task["estimated_duration"],
                priority=template_task["priority"],
                parameters=parameters
            )
            
            tasks.append(task)
        
        return tasks
    
    def _create_task_parameters(self, task_name: str, intent_result: IntentRecognitionResult) -> Dict[str, Any]:
        """Create task-specific parameters based on intent analysis."""
        parameters = {}
        
        # Add common parameters based on the intent result
        if intent_result.entities:
            parameters.update(intent_result.entities)
        
        # Add task-specific parameters
        if task_name == "gather_information":
            if "topic" in intent_result.entities:
                parameters["query"] = intent_result.entities["topic"]
            else:
                parameters["query"] = "general research topic"
        
        elif task_name == "outline_content":
            if "topic" in intent_result.entities:
                parameters["subject"] = intent_result.entities["topic"]
        
        elif task_name == "load_data":
            # If there are file-related entities, use them
            if "file" in intent_result.entities:
                parameters["file_path"] = intent_result.entities["file"]
        
        return parameters
    
    def _create_dependencies(self, tasks: List[PlannedTask]) -> Dict[str, List[str]]:
        """Create dependencies between tasks."""
        dependencies = {}
        
        # For now, create simple sequential dependencies
        # In a more advanced implementation, this would use more complex logic
        for i, task in enumerate(tasks):
            if i > 0:
                # Each task depends on the previous one
                dependencies[task.id] = [tasks[i-1].id]
            else:
                # First task has no dependencies
                dependencies[task.id] = []
        
        return dependencies
    
    def validate_plan(self, plan: WorkflowPlan) -> Tuple[bool, List[str]]:
        """
        Validate a workflow plan for correctness.
        
        Args:
            plan: The plan to validate
            
        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []
        
        # Check for circular dependencies
        try:
            graph = DependencyGraph({task.id: {"deps": plan.dependencies[task.id]} for task in plan.tasks})
            graph.validate()
        except Exception as e:
            errors.append(f"Dependency validation failed: {str(e)}")
        
        # Check that all dependencies refer to existing tasks
        all_task_ids = {task.id for task in plan.tasks}
        for task_id, deps in plan.dependencies.items():
            for dep in deps:
                if dep not in all_task_ids:
                    errors.append(f"Task {task_id} depends on non-existent task {dep}")
        
        # Check for missing required tools
        for task in plan.tasks:
            # This would check if the required tools are available in the system
            pass
        
        return len(errors) == 0, errors


# Example usage
if __name__ == "__main__":
    from weebot.nlp_understanding import NaturalLanguageProcessor
    
    planner = WorkflowPlanner()
    processor = NaturalLanguageProcessor()
    
    # Test with different types of requests
    test_requests = [
        "I need to research the latest trends in artificial intelligence",
        "Analyze the sales data from last quarter",
        "Write a blog post about renewable energy",
        "Automate the weekly status report generation"
    ]
    
    for request in test_requests:
        print(f"\nPlanning for: {request}")
        
        # Process the request to understand intent
        intent_result = processor.process_user_request(request)
        
        # Create a plan based on the understanding
        plan = planner.create_workflow_plan(request, intent_result)
        
        if plan:
            print(f"Plan: {plan.name}")
            print(f"Estimated duration: {plan.estimated_total_duration} minutes")
            print("Tasks:")
            for task in plan.tasks:
                print(f"  - {task.name}: {task.description} ({task.estimated_duration_minutes} min)")
                if plan.dependencies[task.id]:
                    print(f"    Depends on: {', '.join(plan.dependencies[task.id])}")
            
            # Validate the plan
            is_valid, errors = planner.validate_plan(plan)
            if is_valid:
                print("✓ Plan is valid")
            else:
                print(f"✗ Plan has errors: {errors}")
        else:
            print("Could not create a plan for this request")