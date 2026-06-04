"""Legacy bridge for ModelRouter and TaskType."""
from weebot.application.services.model_selection import TaskType, ModelSelectionService, ModelTier, ModelConfig

class ModelRouter(ModelSelectionService):
    """Bridge to the new ModelSelectionService."""
    def __init__(self, daily_budget: float = 10.0, cache_dir: str = None) -> None:
        super().__init__()
        self.daily_budget = daily_budget
        self.cache_dir = cache_dir

    def select_model(self, task_type: TaskType, budget_constraint: float = None) -> str:
        from weebot.application.services.model_selection import BestPerformance
        strategy = BestPerformance()
        candidates = list(self.MODELS.items())
        return strategy.select(candidates, task_type, budget_constraint)

class CostTracker:
    def get_stats(self) -> dict:
        return {"today": 0.0}

class ResponseCache:
    def clear_old_entries(self) -> None:
        pass
