#!/usr/bin/env python3
"""
Weebot Enhanced Model Cascade
==============================

Advanced OpenRouter integration with:
- Model variants (:free, :nitro, :floor, :exacto, :extended, :thinking)
- Native OpenRouter fallbacks (models array)
- Auto Router support (openrouter/auto)
- Provider routing control
- Structured outputs

Usage:
    from weebot.core.openrouter_enhanced_cascade import (
        EnhancedCascadeConfig,
        OpenRouterEnhancedCascade,
        ModelVariant,
    )
    
    config = EnhancedCascadeConfig(
        task_type="coding",
        variant=ModelVariant.NITRO,
        enable_native_fallbacks=True
    )
"""

import os
from typing import Optional, Any
from dataclasses import dataclass, field
from enum import Enum
import requests
import json

from weebot.core.model_cascade_config import MODEL_CASCADE, get_cascade_for_task, ModelConfig


class ModelVariant(str, Enum):
    """OpenRouter model variant suffixes."""
    NONE = ""              # No variant
    FREE = "free"          # :free - zero cost
    EXTENDED = "extended"  # :extended - larger context
    THINKING = "thinking"  # :thinking - reasoning enabled
    NITRO = "nitro"        # :nitro - high throughput
    FLOOR = "floor"        # :floor - lowest price
    EXACTO = "exacto"      # :exacto - quality-first tool calling


class ProviderSort(str, Enum):
    """Provider sorting strategies."""
    PRICE = "price"           # Lowest cost
    THROUGHPUT = "throughput"  # Highest tokens/sec
    LATENCY = "latency"       # Lowest time to first token


@dataclass
class PerformanceThresholds:
    """Performance threshold configuration."""
    min_throughput_p50: Optional[int] = None  # tokens/sec at 50th percentile
    min_throughput_p90: Optional[int] = None  # tokens/sec at 90th percentile
    max_latency_p50: Optional[float] = None   # seconds at 50th percentile
    max_latency_p95: Optional[float] = None   # seconds at 95th percentile


@dataclass
class PriceCeiling:
    """Maximum acceptable price per million tokens."""
    prompt: Optional[float] = None      # $ per 1M prompt tokens
    completion: Optional[float] = None  # $ per 1M completion tokens
    request: Optional[float] = None     # $ per request


@dataclass
class EnhancedCascadeConfig:
    """
    Enhanced cascade configuration with OpenRouter features.
    
    Attributes:
        task_type: Type of task (coding, analysis, chat, debugging)
        max_tier: Maximum price tier allowed
        variant: Model variant suffix (:free, :nitro, etc.)
        use_auto_router: Use openrouter/auto for intelligent routing
        provider_sort: How to sort providers (price, throughput, latency)
        require_zdr: Require Zero Data Retention providers
        data_collection: Provider data collection policy (allow/deny)
        price_ceiling: Maximum acceptable prices
        performance_thresholds: Minimum performance requirements
        use_structured_outputs: Enable JSON schema enforcement
        json_schema: Schema for structured outputs
        enable_native_fallbacks: Use OpenRouter's native fallback chain
        custom_fallback_chain: Custom ordered list of fallback models
        extra_headers: Additional HTTP headers to send
        extra_body: Additional fields for request body
    """
    task_type: str = "coding"
    max_tier: str = "standard"  # free, budget, standard, premium, enterprise
    
    # Model variant
    variant: ModelVariant = ModelVariant.NONE
    
    # Auto Router
    use_auto_router: bool = False
    
    # Provider routing
    provider_sort: Optional[ProviderSort] = None
    require_zdr: bool = False
    data_collection: Optional[str] = None  # "allow" or "deny"
    price_ceiling: Optional[PriceCeiling] = None
    performance_thresholds: Optional[PerformanceThresholds] = None
    
    # Output formatting
    use_structured_outputs: bool = False
    json_schema: Optional[dict] = None
    
    # Fallback configuration
    enable_native_fallbacks: bool = True
    custom_fallback_chain: Optional[list[str]] = None
    
    # Extra parameters
    extra_headers: dict = field(default_factory=dict)
    extra_body: dict = field(default_factory=dict)


@dataclass
class CascadeRequest:
    """Prepared OpenRouter API request."""
    model: str
    models: Optional[list[str]]  # Fallback chain
    provider: Optional[dict]
    response_format: Optional[dict]
    headers: dict
    extra_body: dict
    estimated_cost: float


class OpenRouterEnhancedCascade:
    """
    Enhanced cascade service with full OpenRouter feature support.
    """
    
    AUTO_ROUTER = "openrouter/auto"
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        self.base_url = "https://openrouter.ai/api/v1"
    
    def prepare_request(
        self,
        config: EnhancedCascadeConfig,
        messages: list[dict],
        tools: Optional[list] = None,
        tool_choice: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> CascadeRequest:
        """
        Prepare an OpenRouter API request from enhanced config.
        
        Args:
            config: Enhanced cascade configuration
            messages: Chat messages
            tools: Available tools for tool calling
            tool_choice: Tool choice strategy
            temperature: Sampling temperature
            max_tokens: Maximum response tokens
        
        Returns:
            CascadeRequest with all parameters prepared
        """
        # Determine primary model
        if config.use_auto_router:
            primary_model = self.AUTO_ROUTER
        else:
            primary_model = self._select_model(config)
        
        # Build fallback chain
        fallback_models = self._build_fallback_chain(config) if config.enable_native_fallbacks else None
        
        # Build provider preferences
        provider_prefs = self._build_provider_preferences(config)
        
        # Build response format
        response_format = self._build_response_format(config)
        
        # Build headers
        headers = self._build_headers(config)
        
        # Estimate cost
        estimated_cost = self._estimate_request_cost(config, messages, max_tokens)
        
        # Build extra body parameters
        extra_body = self._build_extra_body(config)
        
        return CascadeRequest(
            model=primary_model,
            models=fallback_models,
            provider=provider_prefs,
            response_format=response_format,
            headers=headers,
            extra_body=extra_body,
            estimated_cost=estimated_cost,
        )
    
    def _select_model(self, config: EnhancedCascadeConfig) -> str:
        """Select the best model for the configuration."""
        if config.use_auto_router:
            return self.AUTO_ROUTER
        
        # Get models for task type
        models = get_cascade_for_task(config.task_type)
        
        # Filter by tier
        tier_priority = {"free": 0, "budget": 1, "standard": 2, "premium": 3, "enterprise": 4}
        max_priority = tier_priority.get(config.max_tier, 2)
        
        eligible = [
            m for m in models 
            if tier_priority.get(m.tier, 99) <= max_priority
        ]
        
        if not eligible:
            # Fallback to any available model
            eligible = models
        
        # Get first recommended model, or first available
        for model in eligible:
            if model.recommended:
                return self._apply_variant(model.id, config.variant)
        
        return self._apply_variant(eligible[0].id, config.variant) if eligible else "openai/gpt-4o"
    
    def _apply_variant(self, model_id: str, variant: ModelVariant) -> str:
        """Apply variant suffix to model ID."""
        if variant == ModelVariant.NONE:
            return model_id
        
        # Strip any existing variant suffixes to avoid doubles
        base_id = model_id
        known_variants = ["free", "extended", "thinking", "nitro", "floor", "exacto"]
        for v in known_variants:
            if base_id.endswith(f":{v}"):
                base_id = base_id[:-(len(v) + 1)]
                break
        
        return f"{base_id}:{variant.value}"
    
    def _build_fallback_chain(self, config: EnhancedCascadeConfig) -> Optional[list[str]]:
        """Build the native fallback chain."""
        if config.custom_fallback_chain:
            return config.custom_fallback_chain
        
        if not config.enable_native_fallbacks:
            return None
        
        # Build chain from cascade config
        models = get_cascade_for_task(config.task_type)
        
        # Filter by tier
        tier_priority = {"free": 0, "budget": 1, "standard": 2, "premium": 3, "enterprise": 4}
        max_priority = tier_priority.get(config.max_tier, 2)
        
        eligible = [
            m for m in models 
            if tier_priority.get(m.tier, 99) <= max_priority
        ]
        
        # Sort by recommendation and tier
        eligible.sort(key=lambda m: (not m.recommended, tier_priority.get(m.tier, 99)))
        
        # Take top 3, apply variant
        chain = [self._apply_variant(m.id, config.variant) for m in eligible[:3]]
        
        return chain if len(chain) > 1 else None
    
    def _build_provider_preferences(self, config: EnhancedCascadeConfig) -> Optional[dict]:
        """Build provider preference object."""
        prefs = {}
        
        # Sort strategy
        if config.provider_sort:
            prefs["sort"] = config.provider_sort.value
        elif config.variant == ModelVariant.NITRO:
            prefs["sort"] = "throughput"
        elif config.variant == ModelVariant.FLOOR:
            prefs["sort"] = "price"
        
        # Data retention
        if config.require_zdr:
            prefs["zdr"] = True
        
        # Data collection policy
        if config.data_collection:
            prefs["data_collection"] = config.data_collection
        
        # Price ceiling
        if config.price_ceiling:
            ceiling = {}
            if config.price_ceiling.prompt is not None:
                ceiling["prompt"] = config.price_ceiling.prompt
            if config.price_ceiling.completion is not None:
                ceiling["completion"] = config.price_ceiling.completion
            if config.price_ceiling.request is not None:
                ceiling["request"] = config.price_ceiling.request
            if ceiling:
                prefs["max_price"] = ceiling
        
        # Performance thresholds
        if config.performance_thresholds:
            pt = config.performance_thresholds
            
            if pt.min_throughput_p50 or pt.min_throughput_p90:
                prefs["preferred_min_throughput"] = {}
                if pt.min_throughput_p50:
                    prefs["preferred_min_throughput"]["p50"] = pt.min_throughput_p50
                if pt.min_throughput_p90:
                    prefs["preferred_min_throughput"]["p90"] = pt.min_throughput_p90
            
            if pt.max_latency_p50 or pt.max_latency_p95:
                prefs["preferred_max_latency"] = {}
                if pt.max_latency_p50:
                    prefs["preferred_max_latency"]["p50"] = pt.max_latency_p50
                if pt.max_latency_p95:
                    prefs["preferred_max_latency"]["p95"] = pt.max_latency_p95
        
        return prefs if prefs else None
    
    def _build_response_format(self, config: EnhancedCascadeConfig) -> Optional[dict]:
        """Build response format for structured outputs."""
        if not config.use_structured_outputs:
            return None
        
        if config.json_schema:
            return {
                "type": "json_schema",
                "json_schema": config.json_schema
            }
        
        # Default schema if none provided
        return {
            "type": "json_object"
        }
    
    def _build_headers(self, config: EnhancedCascadeConfig) -> dict:
        """Build request headers."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://weebot.ai",
            "X-Title": "Weebot AI Assistant",
        }
        
        # Add any extra headers from config
        headers.update(config.extra_headers)
        
        return headers
    
    def _build_extra_body(self, config: EnhancedCascadeConfig) -> dict:
        """Build extra body parameters."""
        extra = dict(config.extra_body)
        
        # Add variant-specific settings
        if config.variant == ModelVariant.EXACTO:
            # Exacto is handled via the variant suffix, but we can add extra hints
            extra["require_tool_support"] = True
        
        return extra
    
    def _estimate_request_cost(
        self, 
        config: EnhancedCascadeConfig, 
        messages: list[dict],
        max_tokens: Optional[int]
    ) -> float:
        """Estimate the cost of this request."""
        # Simple estimation: count characters / 4 for tokens
        input_chars = sum(len(m.get("content", "")) for m in messages)
        input_tokens = input_chars // 4
        output_tokens = max_tokens or 1000
        
        # Get model pricing (rough estimate)
        if config.use_auto_router:
            # Auto router averages around $2/1M for input
            return (input_tokens + output_tokens) / 1_000_000 * 2.0
        
        models = get_cascade_for_task(config.task_type)
        if models:
            model = models[0]
            input_cost = (input_tokens / 1_000_000) * model.prompt_price
            output_cost = (output_tokens / 1_000_000) * model.completion_price
            return input_cost + output_cost
        
        return 0.0
    
    def execute(
        self,
        config: EnhancedCascadeConfig,
        messages: list[dict],
        tools: Optional[list] = None,
        tool_choice: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False,
    ) -> dict:
        """
        Execute a request with enhanced cascade configuration.
        
        Args:
            config: Enhanced cascade configuration
            messages: Chat messages
            tools: Available tools
            tool_choice: Tool choice strategy
            temperature: Sampling temperature
            max_tokens: Maximum response tokens
            stream: Enable streaming
        
        Returns:
            API response as dictionary
        """
        request = self.prepare_request(
            config=config,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        
        body = {
            "model": request.model,
            "messages": messages,
            "temperature": temperature,
            "stream": stream,
        }
        
        if request.models:
            body["models"] = request.models
        
        if request.provider:
            body["provider"] = request.provider
        
        if request.response_format:
            body["response_format"] = request.response_format
        
        if max_tokens:
            body["max_tokens"] = max_tokens
        
        if tools:
            body["tools"] = tools
        
        if tool_choice:
            body["tool_choice"] = tool_choice
        
        body.update(request.extra_body)
        
        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers=request.headers,
            json=body,
            timeout=300,
        )
        
        response.raise_for_status()
        return response.json()


# ============================================================================
# PRESET CONFIGURATIONS
# ============================================================================

# Fast coding - prioritize throughput
CODING_FAST = EnhancedCascadeConfig(
    task_type="coding",
    max_tier="standard",
    variant=ModelVariant.NITRO,
    provider_sort=ProviderSort.THROUGHPUT,
    performance_thresholds=PerformanceThresholds(
        max_latency_p95=3.0,
        min_throughput_p90=50,
    ),
)

# Cost-optimized batch processing
BATCH_PROCESSING = EnhancedCascadeConfig(
    task_type="analysis",
    max_tier="budget",
    variant=ModelVariant.FLOOR,
    provider_sort=ProviderSort.PRICE,
    price_ceiling=PriceCeiling(
        prompt=0.50,
        completion=1.50,
    ),
)

# High-quality agentic workflow
AGENTIC_WORKFLOW = EnhancedCascadeConfig(
    task_type="coding",
    max_tier="premium",
    variant=ModelVariant.EXACTO,
    use_structured_outputs=True,
)

# Privacy-sensitive (ZDR required)
PRIVACY_SENSITIVE = EnhancedCascadeConfig(
    task_type="analysis",
    max_tier="enterprise",
    require_zdr=True,
    data_collection="deny",
)

# Extended context for large files
LARGE_CONTEXT = EnhancedCascadeConfig(
    task_type="coding",
    max_tier="standard",
    variant=ModelVariant.EXTENDED,
)

# Complex reasoning with thinking
COMPLEX_REASONING = EnhancedCascadeConfig(
    task_type="coding",
    max_tier="premium",
    variant=ModelVariant.THINKING,
)

# Zero-cost (free models only)
ZERO_COST = EnhancedCascadeConfig(
    task_type="chat",
    max_tier="free",
    variant=ModelVariant.FREE,
)

# Auto-router for intelligent selection
AUTO_ROUTE = EnhancedCascadeConfig(
    task_type="coding",
    use_auto_router=True,
    enable_native_fallbacks=False,
)


# ============================================================================
# DEMO
# ============================================================================

def demo():
    """Demonstrate enhanced cascade features."""
    print("=" * 80)
    print("WEEBOT ENHANCED MODEL CASCADE - DEMO")
    print("=" * 80)
    print()
    
    cascade = OpenRouterEnhancedCascade(api_key="sk-test")
    
    messages = [
        {"role": "system", "content": "You are a helpful coding assistant."},
        {"role": "user", "content": "Write a Python function to calculate fibonacci numbers."}
    ]
    
    configs = [
        ("Fast Coding (NITRO)", CODING_FAST),
        ("Batch Processing (FLOOR)", BATCH_PROCESSING),
        ("Agentic Workflow (EXACTO)", AGENTIC_WORKFLOW),
        ("Privacy Sensitive (ZDR)", PRIVACY_SENSITIVE),
        ("Large Context (EXTENDED)", LARGE_CONTEXT),
        ("Complex Reasoning (THINKING)", COMPLEX_REASONING),
        ("Zero Cost (FREE)", ZERO_COST),
        ("Auto Router", AUTO_ROUTE),
    ]
    
    for name, config in configs:
        print(f"\n{name}:")
        print("-" * 40)
        
        request = cascade.prepare_request(
            config=config,
            messages=messages,
            temperature=0.7,
            max_tokens=1000,
        )
        
        print(f"  Primary Model: {request.model}")
        print(f"  Fallback Chain: {request.models}")
        print(f"  Provider Prefs: {json.dumps(request.provider, indent=4) if request.provider else 'None'}")
        print(f"  Response Format: {request.response_format}")
        print(f"  Est. Cost: ${request.estimated_cost:.4f}")
    
    print()
    print("=" * 80)
    print("DEMO COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    demo()
