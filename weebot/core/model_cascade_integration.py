#!/usr/bin/env python3
"""
Model Cascade Integration
=========================

Integrates model_cascade_config.py with the existing model_cascade.py service.

Usage:
    from weebot.core.model_cascade_integration import get_cascade_service
    
    service = get_cascade_service()
    result = await service.execute_with_cascade(
        prompt="Write a Python function...",
        config=CascadeConfig(task_type="coding", max_tier=ModelTier.STANDARD)
    )
"""

import asyncio
from typing import Optional
from dataclasses import dataclass
from enum import Enum

from weebot.core.model_cascade_config import (
    MODEL_CASCADE,
    get_cascade_for_task,
    get_recommended_model,
    estimate_cost,
    ModelConfig,
)


class ModelTier(str, Enum):
    """Model price tiers."""
    FREE = "free"
    BUDGET = "budget"
    STANDARD = "standard"
    PREMIUM = "premium"
    ENTERPRISE = "enterprise"


@dataclass
class CascadeConfig:
    """Configuration for cascade execution."""
    task_type: str  # "coding", "analysis", "chat"
    max_tier: ModelTier = ModelTier.STANDARD
    timeout_seconds: int = 60
    max_attempts: int = 3
    prefer_recommended: bool = True


@dataclass
class CascadeResult:
    """Result from cascade execution."""
    success: bool
    content: Optional[str]
    model_used: Optional[str]
    tier: Optional[str]
    attempts: int
    total_cost: float
    error: Optional[str] = None


class ModelCascadeService:
    """Service for executing prompts with automatic model cascading."""
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.attempt_history = []
    
    def _get_tier_priority(self, tier: str) -> int:
        """Get numeric priority for tier (lower = higher priority)."""
        order = ["free", "budget", "standard", "premium", "enterprise"]
        return order.index(tier) if tier in order else 99
    
    def _filter_by_max_tier(self, models: list[ModelConfig], max_tier: ModelTier) -> list[ModelConfig]:
        """Filter models by maximum tier."""
        max_priority = self._get_tier_priority(max_tier.value)
        return [m for m in models if self._get_tier_priority(m.tier) <= max_priority]
    
    def select_models(self, config: CascadeConfig) -> list[ModelConfig]:
        """Select models for the cascade based on config.
        
        Args:
            config: Cascade configuration
        
        Returns:
            List of models ordered by preference
        """
        # Get full cascade for task
        all_models = get_cascade_for_task(config.task_type)
        
        # Filter by max tier
        filtered = self._filter_by_max_tier(all_models, config.max_tier)
        
        # If prefer_recommended, put recommended models first
        if config.prefer_recommended:
            recommended = [m for m in filtered if m.recommended]
            others = [m for m in filtered if not m.recommended]
            return recommended + others
        
        return filtered
    
    async def execute_with_cascade(
        self,
        prompt: str,
        config: CascadeConfig,
    ) -> CascadeResult:
        """Execute a prompt with automatic model fallback.
        
        Args:
            prompt: The prompt to send
            config: Cascade configuration
        
        Returns:
            CascadeResult with success/failure info
        """
        models = self.select_models(config)
        
        if not models:
            return CascadeResult(
                success=False,
                content=None,
                model_used=None,
                tier=None,
                attempts=0,
                total_cost=0.0,
                error="No models available for this configuration",
            )
        
        attempts = 0
        total_cost = 0.0
        
        for model in models[:config.max_attempts]:
            attempts += 1
            
            try:
                # Simulate API call (replace with actual OpenRouter call)
                # In real implementation, this would call OpenRouter API
                result = await self._call_model(prompt, model, config)
                
                if result["success"]:
                    # Estimate cost (in real implementation, use actual tokens)
                    prompt_tokens = len(prompt) // 4  # Rough estimate
                    completion_tokens = len(result["content"]) // 4
                    cost = estimate_cost(model.id, prompt_tokens, completion_tokens)
                    
                    return CascadeResult(
                        success=True,
                        content=result["content"],
                        model_used=model.id,
                        tier=model.tier,
                        attempts=attempts,
                        total_cost=total_cost + cost,
                    )
                
            except Exception as e:
                # Log failure and continue to next model
                self.attempt_history.append({
                    "model": model.id,
                    "error": str(e),
                    "attempt": attempts,
                })
                continue
        
        # All attempts failed
        return CascadeResult(
            success=False,
            content=None,
            model_used=None,
            tier=None,
            attempts=attempts,
            total_cost=total_cost,
            error=f"All {attempts} models failed. Last error: {self.attempt_history[-1].get('error', 'Unknown')}",
        )
    
    async def _call_model(
        self,
        prompt: str,
        model: ModelConfig,
        config: CascadeConfig,
    ) -> dict:
        """Call a specific model. (Placeholder - integrate with actual API)
        
        In real implementation, this would:
        1. Format request for OpenRouter API
        2. Send request with timeout
        3. Handle retries
        4. Parse response
        """
        # Placeholder implementation
        # Replace with actual OpenRouter integration
        return {
            "success": True,
            "content": f"Response from {model.name}",
            "model": model.id,
        }


# Singleton instance
_cascade_service: Optional[ModelCascadeService] = None


def get_cascade_service(api_key: Optional[str] = None) -> ModelCascadeService:
    """Get or create the cascade service singleton."""
    global _cascade_service
    if _cascade_service is None:
        _cascade_service = ModelCascadeService(api_key)
    return _cascade_service


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

async def demo():
    """Demonstrate cascade service usage."""
    print("=" * 70)
    print("MODEL CASCADE INTEGRATION DEMO")
    print("=" * 70)
    print()
    
    service = get_cascade_service()
    
    # Demo 1: Coding task with free tier only
    print("1. Coding task (FREE tier only):")
    config = CascadeConfig(
        task_type="coding",
        max_tier=ModelTier.FREE,
        max_attempts=3,
    )
    models = service.select_models(config)
    for m in models[:3]:
        print(f"   - {m.id} ({m.tier})")
    print()
    
    # Demo 2: Coding task with standard tier
    print("2. Coding task (up to STANDARD tier):")
    config = CascadeConfig(
        task_type="coding",
        max_tier=ModelTier.STANDARD,
        max_attempts=3,
    )
    models = service.select_models(config)
    for m in models[:5]:
        print(f"   - {m.id} ({m.tier})")
    print()
    
    # Demo 3: Analysis task with premium tier
    print("3. Analysis task (up to PREMIUM tier):")
    config = CascadeConfig(
        task_type="analysis",
        max_tier=ModelTier.PREMIUM,
        max_attempts=3,
    )
    models = service.select_models(config)
    for m in models[:5]:
        print(f"   - {m.id} ({m.tier})")
    print()
    
    # Demo 4: Cost estimation
    print("4. Cost estimation for 1M input + 500K output tokens:")
    for task in ["coding", "analysis", "chat"]:
        for tier in ["free", "budget", "standard", "premium"]:
            model = get_recommended_model(task, tier)
            if model:
                cost = estimate_cost(model.id, 1_000_000, 500_000)
                print(f"   {task:10} {tier:10}: ${cost:.2f} ({model.id})")
    print()
    
    print("=" * 70)
    print("DEMO COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(demo())
