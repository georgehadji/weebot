"""
Model Registry for Weebot - AI Model Characteristics & Pricing Information

This module provides a registry of AI models with their characteristics, 
pricing information, and capabilities for intelligent model selection.
Based on the detailed model information from the RTK project.
"""
import json
import math
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Any
from pathlib import Path


class ModelProvider(Enum):
    """Supported AI model providers."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    AZURE = "azure"
    AWS_BEDROCK = "bedrock"
    COHERE = "cohere"
    ANYSCALE = "anyscale"
    PERPLEXITY = "perplexity"
    MISTRAL = "mistral"
    GROQ = "groq"
    TOGETHER_AI = "together_ai"
    OLLAMA = "ollama"
    HUGGINGFACE = "huggingface"
    DEEPSEEK = "deepseek"
    MOONSHOT = "moonshot"
    XAI = "xai"
    NVIDIA = "nvidia_nim"
    FIREWORKS_AI = "fireworks_ai"
    LEONARDO_AI = "leonardo_ai"
    REPLICATE = "replicate"
    VERTEX_AI = "vertex_ai"
    GEMINI = "gemini"
    OPENROUTER = "openrouter"
    LM_STUDIO = "lm_studio"
    VLLM = "vllm"
    CUSTOM_OPENAI = "custom_openai"


class ModelTier(Enum):
    """Model tiers based on capabilities and cost."""
    FRONTIER = "frontier"      # Most advanced models (Opus, GPT-5, etc.)
    PERFORMANCE = "performance"  # Balanced performance/cost (Sonnet, GPT-4)
    BUDGET = "budget"        # Cost-effective models (Haiku, GPT-4o-mini)
    OPEN_SOURCE = "open_source"  # Free/open source models


@dataclass
class ModelCharacteristics:
    """Detailed characteristics of an AI model."""
    reasoning: int = 0      # 0-100 scale
    coding: int = 0         # 0-100 scale
    agents: int = 0         # 0-100 scale
    creative: int = 0       # 0-100 scale
    speed: int = 0          # 0-100 scale (higher = faster)
    
    def get_average_score(self) -> float:
        """Get average of all characteristics."""
        return (self.reasoning + self.coding + self.agents + self.creative + self.speed) / 5.0


@dataclass
class ModelInfo:
    """Information about a specific AI model."""
    model_name: str
    provider: ModelProvider
    tier: ModelTier
    input_cost_per_token: float  # Cost per input token
    output_cost_per_token: float  # Cost per output token
    context_window: int          # Maximum context window in tokens
    characteristics: ModelCharacteristics
    best_for: List[str]
    agent_notes: str
    supports_function_calling: bool = False
    supports_vision: bool = False
    supports_audio_input: bool = False
    supports_audio_output: bool = False
    supports_system_messages: bool = True
    supports_response_schema: bool = False
    supports_prompt_caching: bool = False
    supports_reasoning: bool = False
    supports_parallel_function_calling: bool = False
    max_output_tokens: Optional[int] = None
    description: str = ""
    
    def calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Calculate the cost for a specific usage."""
        return (input_tokens * self.input_cost_per_token) + (output_tokens * self.output_cost_per_token)

    def calculate_cost_per_1k_tokens(self) -> float:
        """Get the average cost per 1k tokens (assuming equal input/output)."""
        return (self.input_cost_per_token + self.output_cost_per_token) * 1000


def _get_detailed_model_registry() -> Dict[str, ModelInfo]:
    """Get the detailed model registry with characteristics from RTK project."""
    return {
        # === Frontier / Reasoning Models ===
        "claude-4.6-opus": ModelInfo(
            model_name="claude-4.6-opus",
            provider=ModelProvider.ANTHROPIC,
            tier=ModelTier.FRONTIER,
            input_cost_per_token=5e-06,  # $5.0 per 1M tokens
            output_cost_per_token=2.5e-05,  # $25.0 per 1M tokens
            context_window=1000000,  # 1M tokens
            characteristics=ModelCharacteristics(
                reasoning=95,
                coding=92,
                agents=97,
                creative=90,
                speed=55
            ),
            best_for=["Deep reasoning", "Agent Teams", "Long-horizon tasks", "Research"],
            agent_notes="14.5h autonomous task horizon (METR). Native multi-agent collaboration. 16 agents wrote a C compiler in Rust.",
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="Anthropic's Claude Opus 4.6 - Frontier model for deep reasoning, agent teams, and long-horizon tasks. Native multi-agent collaboration with 14.5h autonomous task horizon."
        ),
        "gpt-5.2": ModelInfo(
            model_name="gpt-5.2",
            provider=ModelProvider.OPENAI,
            tier=ModelTier.FRONTIER,
            input_cost_per_token=1.75e-06,  # $1.75 per 1M tokens
            output_cost_per_token=3e-05,  # $30.0 per 1M tokens
            context_window=400000,  # 400K tokens
            characteristics=ModelCharacteristics(
                reasoning=93,
                coding=88,
                agents=78,
                creative=85,
                speed=60
            ),
            best_for=["Multi-step reasoning", "Math", "Multimodal"],
            agent_notes="Strong decomposition stability. 38.2% OSWorld (weak computer use). High output cost.",
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="OpenAI's GPT-5.2 - Frontier model for multi-step reasoning, math, and multimodal tasks. Strong decomposition stability but high output cost."
        ),
        "gemini-3-pro": ModelInfo(
            model_name="gemini-3-pro",
            provider=ModelProvider.GOOGLE,
            tier=ModelTier.FRONTIER,
            input_cost_per_token=1.25e-06,  # $1.25 per 1M tokens
            output_cost_per_token=1e-05,  # $10.0 per 1M tokens
            context_window=1000000,  # 1M tokens
            characteristics=ModelCharacteristics(
                reasoning=90,
                coding=85,
                agents=80,
                creative=82,
                speed=65
            ),
            best_for=["Long context", "Multimodal", "Google ecosystem"],
            agent_notes="1M context native. 100% AIME 2025 (with code exec). Charges for thinking tokens.",
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="Google's Gemini 3 Pro - Frontier model with 1M native context, strong in math reasoning (100% AIME 2025 with code exec). Charges for thinking tokens."
        ),
        "grok-4.1": ModelInfo(
            model_name="grok-4.1",
            provider=ModelProvider.XAI,
            tier=ModelTier.FRONTIER,
            input_cost_per_token=3e-06,  # $3.0 per 1M tokens
            output_cost_per_token=1.5e-05,  # $15.0 per 1M tokens
            context_window=2000000,  # 2M tokens
            characteristics=ModelCharacteristics(
                reasoning=94,
                coding=83,
                agents=75,
                creative=78,
                speed=62
            ),
            best_for=["Pure reasoning", "Real-time data (X)", "Low hallucination"],
            agent_notes="#1 LMArena Elo (1483). Hallucination rate ~4%. 2M context window.",
            supports_function_calling=True,
            supports_vision=False,
            supports_system_messages=True,
            supports_response_schema=False,
            description="xAI's Grok 4.1 - Frontier model for pure reasoning with 2M context window and ~4% hallucination rate. #1 LMArena Elo (1483)."
        ),
        
        # === Performance / Best Value Models ===
        "claude-4.6-sonnet": ModelInfo(
            model_name="claude-4.6-sonnet",
            provider=ModelProvider.ANTHROPIC,
            tier=ModelTier.PERFORMANCE,
            input_cost_per_token=3e-06,  # $3.0 per 1M tokens
            output_cost_per_token=1.5e-05,  # $15.0 per 1M tokens
            context_window=200000,  # 200K tokens (1M beta)
            characteristics=ModelCharacteristics(
                reasoning=78,
                coding=90,
                agents=95,
                creative=86,
                speed=72
            ),
            best_for=["Coding agents", "Computer use", "Office tasks", "Production default"],
            agent_notes="72.5% OSWorld (near Opus). 79.6% SWE-bench. 94% on real insurance workflows. Best value for agents.",
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="Anthropic's Claude Sonnet 4.6 - Best value for coding agents and production use. 72.5% OSWorld (near Opus), 79.6% SWE-bench, 94% on real insurance workflows."
        ),
        "gpt-5.1": ModelInfo(
            model_name="gpt-5.1",
            provider=ModelProvider.OPENAI,
            tier=ModelTier.PERFORMANCE,
            input_cost_per_token=1.25e-06,  # $1.25 per 1M tokens
            output_cost_per_token=1e-05,  # $10.0 per 1M tokens
            context_window=400000,  # 400K tokens
            characteristics=ModelCharacteristics(
                reasoning=88,
                coding=86,
                agents=82,
                creative=83,
                speed=68
            ),
            best_for=["Agentic workflows", "Configurable reasoning", "General purpose"],
            agent_notes="Configurable reasoning effort. 400K context. Good balance of speed/quality.",
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="OpenAI's GPT-5.1 - Configurable reasoning effort with good balance of speed/quality. Perfect for agentic workflows."
        ),
        "deepseek-r1": ModelInfo(
            model_name="deepseek-r1",
            provider=ModelProvider.DEEPSEEK,
            tier=ModelTier.PERFORMANCE,
            input_cost_per_token=5.5e-07,  # $0.55 per 1M tokens
            output_cost_per_token=2.19e-06,  # $2.19 per 1M tokens
            context_window=128000,  # 128K tokens
            characteristics=ModelCharacteristics(
                reasoning=87,
                coding=82,
                agents=72,
                creative=68,
                speed=60
            ),
            best_for=["Math reasoning", "Budget reasoning", "Self-hosted"],
            agent_notes="87.5% AIME. Strong reasoning at fraction of cost. Good for specialized reasoning agents.",
            supports_function_calling=True,
            supports_system_messages=True,
            description="DeepSeek's R1 - Strong reasoning at fraction of cost with 87.5% AIME score. Good for specialized reasoning agents."
        ),
        
        # === Budget / High-Volume Models ===
        "claude-4.5-haiku": ModelInfo(
            model_name="claude-4.5-haiku",
            provider=ModelProvider.ANTHROPIC,
            tier=ModelTier.BUDGET,
            input_cost_per_token=1e-06,  # $1.0 per 1M tokens
            output_cost_per_token=5e-06,  # $5.0 per 1M tokens
            context_window=200000,  # 200K tokens
            characteristics=ModelCharacteristics(
                reasoning=62,
                coding=68,
                agents=65,
                creative=60,
                speed=92
            ),
            best_for=["Classification", "Routing", "Extraction", "High-volume"],
            agent_notes="Ideal as router model in multi-agent systems. Fast classification for agent orchestration.",
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="Anthropic's Claude Haiku 4.5 - Fast classification for agent orchestration. Ideal as router model in multi-agent systems."
        ),
        "gpt-5-mini": ModelInfo(
            model_name="gpt-5-mini",
            provider=ModelProvider.OPENAI,
            tier=ModelTier.BUDGET,
            input_cost_per_token=2.5e-07,  # $0.25 per 1M tokens
            output_cost_per_token=2e-06,  # $2.0 per 1M tokens
            context_window=128000,  # 128K tokens
            characteristics=ModelCharacteristics(
                reasoning=65,
                coding=62,
                agents=60,
                creative=58,
                speed=90
            ),
            best_for=["Simple routing", "Classification", "Budget apps"],
            agent_notes="Budget option for simple agent tasks. Good for inner-loop routing decisions.",
            supports_function_calling=True,
            supports_system_messages=True,
            description="OpenAI's GPT-5 Mini - Budget option for simple agent tasks and inner-loop routing decisions."
        ),
        "gemini-2.5-flash": ModelInfo(
            model_name="gemini-2.5-flash",
            provider=ModelProvider.GOOGLE,
            tier=ModelTier.BUDGET,
            input_cost_per_token=1.5e-07,  # $0.15 per 1M tokens
            output_cost_per_token=6e-07,  # $0.60 per 1M tokens
            context_window=1000000,  # 1M tokens
            characteristics=ModelCharacteristics(
                reasoning=60,
                coding=58,
                agents=55,
                creative=55,
                speed=95
            ),
            best_for=["Ultra-cheap ops", "Prototyping", "High-volume simple tasks"],
            agent_notes="Cheapest option with 1M context. Great for summarization sub-agents.",
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="Google's Gemini 2.5 Flash - Cheapest option with 1M context. Great for summarization sub-agents and ultra-cheap operations."
        ),
        "deepseek-v3.2": ModelInfo(
            model_name="deepseek-v3.2",
            provider=ModelProvider.DEEPSEEK,
            tier=ModelTier.BUDGET,
            input_cost_per_token=1.4e-07,  # $0.14 per 1M tokens
            output_cost_per_token=2.8e-07,  # $0.28 per 1M tokens
            context_window=128000,  # 128K tokens
            characteristics=ModelCharacteristics(
                reasoning=58,
                coding=65,
                agents=55,
                creative=55,
                speed=88
            ),
            best_for=["Ultra-budget", "Batch processing", "Simple agents"],
            agent_notes="~100x cheaper than GPT-5.2 output. Quality score 79/100. Best $/quality ratio.",
            supports_function_calling=True,
            supports_system_messages=True,
            description="DeepSeek's V3.2 - Ultra-budget model (~100x cheaper than GPT-5.2 output) with quality score 79/100. Best $/quality ratio."
        ),
        
        # === Open Source Models ===
        "k2": ModelInfo(
            model_name="k2",
            provider=ModelProvider.HUGGINGFACE,
            tier=ModelTier.OPEN_SOURCE,
            input_cost_per_token=0.0,  # Free for open source
            output_cost_per_token=0.0,
            context_window=128000,  # 128K tokens
            characteristics=ModelCharacteristics(
                reasoning=78,
                coding=75,
                agents=82,
                creative=65,
                speed=70
            ),
            best_for=["Self-hosted", "Privacy-sensitive", "Budget-constrained"],
            agent_notes="Open source model with strong agent capabilities (82) and good reasoning (78).",
            supports_function_calling=True,
            supports_system_messages=True,
            description="K2 Open Source model - Community model with strong agent capabilities (82) and good reasoning (78)."
        ),
        
        # === Legacy models for backward compatibility ===
        "gpt-4o": ModelInfo(
            model_name="gpt-4o",
            provider=ModelProvider.OPENAI,
            tier=ModelTier.PERFORMANCE,
            input_cost_per_token=5e-06,
            output_cost_per_token=1.5e-05,
            context_window=128000,
            characteristics=ModelCharacteristics(
                reasoning=85,
                coding=82,
                agents=75,
                creative=80,
                speed=65
            ),
            best_for=["General purpose", "Multimodal tasks", "Code generation"],
            agent_notes="OpenAI's most advanced multimodal model with good balance of capabilities.",
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="OpenAI's most advanced multimodal model"
        ),
        "gpt-4o-mini": ModelInfo(
            model_name="gpt-4o-mini",
            provider=ModelProvider.OPENAI,
            tier=ModelTier.BUDGET,
            input_cost_per_token=1.5e-07,
            output_cost_per_token=6e-07,
            context_window=128000,
            characteristics=ModelCharacteristics(
                reasoning=70,
                coding=72,
                agents=65,
                creative=68,
                speed=85
            ),
            best_for=["Budget chat", "Documentation", "Lightweight tasks"],
            agent_notes="OpenAI's affordable multimodal model with good speed and reasonable capabilities.",
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="OpenAI's affordable multimodal model"
        ),
        "gpt-3.5-turbo": ModelInfo(
            model_name="gpt-3.5-turbo",
            provider=ModelProvider.OPENAI,
            tier=ModelTier.BUDGET,
            input_cost_per_token=5e-07,
            output_cost_per_token=1.5e-06,
            context_window=16385,
            characteristics=ModelCharacteristics(
                reasoning=60,
                coding=65,
                agents=55,
                creative=62,
                speed=80
            ),
            best_for=["Simple chat", "Basic code generation", "Fast responses"],
            agent_notes="OpenAI's efficient chat model for simple tasks.",
            supports_function_calling=True,
            supports_system_messages=True,
            description="OpenAI's efficient chat model"
        ),
        "claude-3-5-sonnet-20241022": ModelInfo(
            model_name="claude-3-5-sonnet-20241022",
            provider=ModelProvider.ANTHROPIC,
            tier=ModelTier.PERFORMANCE,
            input_cost_per_token=3e-06,
            output_cost_per_token=1.5e-05,
            context_window=200000,
            characteristics=ModelCharacteristics(
                reasoning=85,
                coding=88,
                agents=90,
                creative=82,
                speed=75
            ),
            best_for=["Code review", "Creative tasks", "Documentation"],
            agent_notes="Anthropic's most intelligent model with excellent coding and reasoning capabilities.",
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            description="Anthropic's most intelligent model"
        ),
        "gemini/gemini-1.5-pro": ModelInfo(
            model_name="gemini/gemini-1.5-pro",
            provider=ModelProvider.GOOGLE,
            tier=ModelTier.PERFORMANCE,
            input_cost_per_token=1.25e-06,
            output_cost_per_token=5e-06,
            context_window=2000000,
            characteristics=ModelCharacteristics(
                reasoning=80,
                coding=78,
                agents=75,
                creative=75,
                speed=70
            ),
            best_for=["Long context", "Multimodal analysis", "Research"],
            agent_notes="Google's most capable multimodal model with 2M context window.",
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="Google's most capable multimodal model"
        ),
        "gemini/gemini-1.5-flash": ModelInfo(
            model_name="gemini/gemini-1.5-flash",
            provider=ModelProvider.GOOGLE,
            tier=ModelTier.BUDGET,
            input_cost_per_token=7.5e-08,
            output_cost_per_token=3e-07,
            context_window=1000000,
            characteristics=ModelCharacteristics(
                reasoning=70,
                coding=68,
                agents=65,
                creative=65,
                speed=90
            ),
            best_for=["Fast responses", "Light multimodal tasks", "Budget operations"],
            agent_notes="Google's fast and efficient multimodal model with 1M context window.",
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="Google's fast and efficient multimodal model"
        ),
        # === OpenRouter Models ===
        "openrouter/auto": ModelInfo(
            model_name="openrouter/auto",
            provider=ModelProvider.OPENROUTER,
            tier=ModelTier.PERFORMANCE,
            input_cost_per_token=5e-06,
            output_cost_per_token=1.5e-05,
            context_window=2000000,
            characteristics=ModelCharacteristics(
                reasoning=85,
                coding=85,
                agents=85,
                creative=85,
                speed=75
            ),
            best_for=["Auto-routing", "Multi-provider fallback", "Simplified access"],
            agent_notes="Automatically selects the best model via NotDiamond routing.",
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="OpenRouter Auto - automatically selects the best model via NotDiamond"
        ),
        "openrouter/openai/gpt-4.1": ModelInfo(
            model_name="openrouter/openai/gpt-4.1",
            provider=ModelProvider.OPENROUTER,
            tier=ModelTier.PERFORMANCE,
            input_cost_per_token=2e-06,
            output_cost_per_token=8e-06,
            context_window=1047576,
            characteristics=ModelCharacteristics(
                reasoning=88,
                coding=86,
                agents=82,
                creative=83,
                speed=70
            ),
            best_for=["Coding", "Analysis", "Long-context tasks"],
            agent_notes="OpenAI's GPT-4.1 with 1M context via OpenRouter unified API.",
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="OpenAI GPT-4.1 via OpenRouter"
        ),
        "openrouter/openai/gpt-4.1-mini": ModelInfo(
            model_name="openrouter/openai/gpt-4.1-mini",
            provider=ModelProvider.OPENROUTER,
            tier=ModelTier.BUDGET,
            input_cost_per_token=4e-07,
            output_cost_per_token=1.6e-06,
            context_window=1047576,
            characteristics=ModelCharacteristics(
                reasoning=72,
                coding=74,
                agents=68,
                creative=70,
                speed=82
            ),
            best_for=["Budget coding", "Documentation", "Lightweight analysis"],
            agent_notes="Smaller, faster GPT-4.1 variant with full 1M context.",
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="OpenAI GPT-4.1 Mini via OpenRouter"
        ),
        "openrouter/openai/gpt-4o-mini": ModelInfo(
            model_name="openrouter/openai/gpt-4o-mini",
            provider=ModelProvider.OPENROUTER,
            tier=ModelTier.BUDGET,
            input_cost_per_token=1.5e-07,
            output_cost_per_token=6e-07,
            context_window=128000,
            characteristics=ModelCharacteristics(
                reasoning=70,
                coding=72,
                agents=65,
                creative=68,
                speed=85
            ),
            best_for=["Budget chat", "Documentation", "Lightweight tasks"],
            agent_notes="OpenAI's affordable multimodal model via OpenRouter.",
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="OpenAI GPT-4o Mini via OpenRouter"
        ),
        "openrouter/anthropic/claude-3.7-sonnet": ModelInfo(
            model_name="openrouter/anthropic/claude-3.7-sonnet",
            provider=ModelProvider.OPENROUTER,
            tier=ModelTier.PERFORMANCE,
            input_cost_per_token=3e-06,
            output_cost_per_token=1.5e-05,
            context_window=200000,
            characteristics=ModelCharacteristics(
                reasoning=87,
                coding=90,
                agents=92,
                creative=84,
                speed=74
            ),
            best_for=["Coding agents", "Code review", "Architecture"],
            agent_notes="Claude 3.7 Sonnet with extended thinking via OpenRouter.",
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="Anthropic Claude 3.7 Sonnet via OpenRouter"
        ),
        "openrouter/anthropic/claude-3.5-sonnet": ModelInfo(
            model_name="openrouter/anthropic/claude-3.5-sonnet",
            provider=ModelProvider.OPENROUTER,
            tier=ModelTier.PERFORMANCE,
            input_cost_per_token=3e-06,
            output_cost_per_token=1.5e-05,
            context_window=200000,
            characteristics=ModelCharacteristics(
                reasoning=85,
                coding=88,
                agents=90,
                creative=82,
                speed=75
            ),
            best_for=["Coding agents", "Code review", "Creative tasks"],
            agent_notes="Claude 3.5 Sonnet via OpenRouter unified API.",
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="Anthropic Claude 3.5 Sonnet via OpenRouter"
        ),
        "openrouter/anthropic/claude-opus-4.6": ModelInfo(
            model_name="openrouter/anthropic/claude-opus-4.6",
            provider=ModelProvider.OPENROUTER,
            tier=ModelTier.FRONTIER,
            input_cost_per_token=3e-05,
            output_cost_per_token=7.5e-05,
            context_window=1000000,
            characteristics=ModelCharacteristics(
                reasoning=95,
                coding=92,
                agents=97,
                creative=90,
                speed=55
            ),
            best_for=["Deep reasoning", "Agent teams", "Long-horizon tasks"],
            agent_notes="Claude Opus 4.6 via OpenRouter for maximum capability.",
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="Anthropic Claude Opus 4.6 via OpenRouter"
        ),
        "openrouter/google/gemini-2.5-pro": ModelInfo(
            model_name="openrouter/google/gemini-2.5-pro",
            provider=ModelProvider.OPENROUTER,
            tier=ModelTier.PERFORMANCE,
            input_cost_per_token=2.5e-06,
            output_cost_per_token=1e-05,
            context_window=1000000,
            characteristics=ModelCharacteristics(
                reasoning=88,
                coding=84,
                agents=80,
                creative=80,
                speed=68
            ),
            best_for=["Long context", "Multimodal", "Math reasoning"],
            agent_notes="Google Gemini 2.5 Pro with 1M context via OpenRouter.",
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="Google Gemini 2.5 Pro via OpenRouter"
        ),
        "openrouter/google/gemini-2.5-flash": ModelInfo(
            model_name="openrouter/google/gemini-2.5-flash",
            provider=ModelProvider.OPENROUTER,
            tier=ModelTier.BUDGET,
            input_cost_per_token=5e-08,
            output_cost_per_token=4e-07,
            context_window=1000000,
            characteristics=ModelCharacteristics(
                reasoning=62,
                coding=60,
                agents=57,
                creative=57,
                speed=96
            ),
            best_for=["Ultra-cheap ops", "Summarization", "High-volume"],
            agent_notes="Fastest and cheapest Gemini via OpenRouter with 1M context.",
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="Google Gemini 2.5 Flash via OpenRouter"
        ),
        "openrouter/deepseek/deepseek-chat-v3.1": ModelInfo(
            model_name="openrouter/deepseek/deepseek-chat-v3.1",
            provider=ModelProvider.OPENROUTER,
            tier=ModelTier.BUDGET,
            input_cost_per_token=1.5e-07,
            output_cost_per_token=7.5e-07,
            context_window=32768,
            characteristics=ModelCharacteristics(
                reasoning=68,
                coding=72,
                agents=60,
                creative=58,
                speed=85
            ),
            best_for=["Budget coding", "Debugging", "Analysis"],
            agent_notes="DeepSeek Chat V3.1 via OpenRouter - excellent value.",
            supports_function_calling=True,
            supports_system_messages=True,
            description="DeepSeek Chat V3.1 via OpenRouter"
        ),
        "openrouter/deepseek/deepseek-r1-0528": ModelInfo(
            model_name="openrouter/deepseek/deepseek-r1-0528",
            provider=ModelProvider.OPENROUTER,
            tier=ModelTier.PERFORMANCE,
            input_cost_per_token=5.5e-07,
            output_cost_per_token=2.19e-06,
            context_window=163840,
            characteristics=ModelCharacteristics(
                reasoning=87,
                coding=82,
                agents=72,
                creative=68,
                speed=60
            ),
            best_for=["Math reasoning", "Budget reasoning", "Complex analysis"],
            agent_notes="DeepSeek R1 reasoning model via OpenRouter.",
            supports_function_calling=True,
            supports_system_messages=True,
            description="DeepSeek R1 via OpenRouter"
        ),
        "openrouter/x-ai/grok-4.1-fast": ModelInfo(
            model_name="openrouter/x-ai/grok-4.1-fast",
            provider=ModelProvider.OPENROUTER,
            tier=ModelTier.PERFORMANCE,
            input_cost_per_token=2e-07,
            output_cost_per_token=5e-07,
            context_window=2000000,
            characteristics=ModelCharacteristics(
                reasoning=80,
                coding=78,
                agents=70,
                creative=72,
                speed=88
            ),
            best_for=["Low latency", "Chat", "Large context"],
            agent_notes="xAI Grok 4.1 Fast with 2M context via OpenRouter.",
            supports_function_calling=True,
            supports_system_messages=True,
            description="xAI Grok 4.1 Fast via OpenRouter"
        ),
        "openrouter/meta-llama/llama-4-maverick": ModelInfo(
            model_name="openrouter/meta-llama/llama-4-maverick",
            provider=ModelProvider.OPENROUTER,
            tier=ModelTier.PERFORMANCE,
            input_cost_per_token=1.5e-07,
            output_cost_per_token=6e-07,
            context_window=1048576,
            characteristics=ModelCharacteristics(
                reasoning=74,
                coding=76,
                agents=70,
                creative=68,
                speed=82
            ),
            best_for=["Open-weight", "Multi-modal", "Large context"],
            agent_notes="Meta Llama 4 Maverick via OpenRouter with 1M context.",
            supports_function_calling=True,
            supports_system_messages=True,
            description="Meta Llama 4 Maverick via OpenRouter"
        ),
        "openrouter/moonshotai/kimi-k2.5": ModelInfo(
            model_name="openrouter/moonshotai/kimi-k2.5",
            provider=ModelProvider.OPENROUTER,
            tier=ModelTier.PERFORMANCE,
            input_cost_per_token=2.5e-06,
            output_cost_per_token=1e-05,
            context_window=262144,
            characteristics=ModelCharacteristics(
                reasoning=84,
                coding=88,
                agents=86,
                creative=80,
                speed=72
            ),
            best_for=["Coding", "Architecture", "Code review"],
            agent_notes="Moonshot Kimi K2.5 via OpenRouter unified API.",
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="Moonshot Kimi K2.5 via OpenRouter"
        ),
    }


# Global model registry
MODEL_REGISTRY: Dict[str, ModelInfo] = _get_detailed_model_registry()


def get_model_info(model_name: str) -> Optional[ModelInfo]:
    """
    Get information about a specific model.
    
    Args:
        model_name: Name of the model to look up
        
    Returns:
        ModelInfo object if found, None otherwise
    """
    return MODEL_REGISTRY.get(model_name)


def get_models_by_provider(provider: ModelProvider) -> List[ModelInfo]:
    """
    Get all models for a specific provider.
    
    Args:
        provider: Provider to filter models by
        
    Returns:
        List of ModelInfo objects for the provider
    """
    return [model for model in MODEL_REGISTRY.values() if model.provider == provider]


def get_models_by_tier(tier: ModelTier) -> List[ModelInfo]:
    """
    Get all models for a specific tier.
    
    Args:
        tier: Tier to filter models by
        
    Returns:
        List of ModelInfo objects for the tier
    """
    return [model for model in MODEL_REGISTRY.values() if model.tier == tier]


def get_best_model_for_task(
    task_requirements: Dict[str, Any],
    budget_constraint: Optional[float] = None,
    provider_preference: Optional[ModelProvider] = None
) -> Optional[ModelInfo]:
    """
    Find the best model for a specific task based on requirements.
    
    Args:
        task_requirements: Dictionary with required capabilities
            - reasoning_power: Minimum reasoning score (0-100)
            - coding_ability: Minimum coding score (0-100)
            - agent_capability: Minimum agent score (0-100)
            - context_needed: Minimum context window needed
            - speed_requirement: Minimum speed score (0-100)
            - supports_vision: Whether vision support is required
            - supports_function_calling: Whether function calling is required
        budget_constraint: Maximum cost per 1k tokens allowed
        provider_preference: Preferred provider if available
        
    Returns:
        Best ModelInfo that meets requirements, or None if no model found
    """
    candidates = []
    
    for model in MODEL_REGISTRY.values():
        # Check budget constraint
        if budget_constraint and (model.input_cost_per_token + model.output_cost_per_token) * 1000 > budget_constraint:
            continue
            
        # Check provider preference (if specified, prioritize these)
        provider_score = 100 if provider_preference and model.provider == provider_preference else 0
        
        # Check task requirements
        meets_requirements = True
        
        # Check reasoning power
        if task_requirements.get("reasoning_power") and model.characteristics.reasoning < task_requirements["reasoning_power"]:
            meets_requirements = False
            
        # Check coding ability
        if task_requirements.get("coding_ability") and model.characteristics.coding < task_requirements["coding_ability"]:
            meets_requirements = False
            
        # Check agent capability
        if task_requirements.get("agent_capability") and model.characteristics.agents < task_requirements["agent_capability"]:
            meets_requirements = False
            
        # Check context window
        if task_requirements.get("context_needed") and model.context_window < task_requirements["context_needed"]:
            meets_requirements = False
            
        # Check vision support
        if task_requirements.get("supports_vision") and not model.supports_vision:
            meets_requirements = False
            
        # Check function calling support
        if task_requirements.get("supports_function_calling") and not model.supports_function_calling:
            meets_requirements = False
            
        # Check speed requirement
        if task_requirements.get("speed_requirement") and model.characteristics.speed < task_requirements["speed_requirement"]:
            meets_requirements = False
            
        if meets_requirements:
            # Calculate score based on how well the model matches requirements
            score = model.characteristics.get_average_score() + provider_score
            # Lower cost models get higher scores (when capabilities are similar)
            cost_penalty = (model.input_cost_per_token + model.output_cost_per_token) * 100000
            final_score = score - cost_penalty
            candidates.append((model, final_score))
    
    if not candidates:
        return None
    
    # Sort by score descending
    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[0][0]


def get_cheapest_model_for_task(
    input_tokens: int,
    output_tokens: int,
    providers: Optional[List[ModelProvider]] = None,
    required_capabilities: Optional[List[str]] = None
) -> Optional[ModelInfo]:
    """
    Find the cheapest model that meets the requirements for a specific task.

    Args:
        input_tokens: Expected number of input tokens
        output_tokens: Expected number of output tokens
        providers: Optional list of providers to consider
        required_capabilities: Optional list of required capabilities (function_calling, vision, etc.)

    Returns:
        Cheapest ModelInfo that meets requirements, or None if no model found
    """
    candidates = []

    for model in MODEL_REGISTRY.values():
        # Filter by provider if specified
        if providers and model.provider not in providers:
            continue

        # Check if model has required capabilities
        if required_capabilities:
            has_all_caps = True
            for cap in required_capabilities:
                if cap == "function_calling" and not model.supports_function_calling:
                    has_all_caps = False
                    break
                elif cap == "vision" and not model.supports_vision:
                    has_all_caps = False
                    break
                elif cap == "system_messages" and not model.supports_system_messages:
                    has_all_caps = False
                    break
                elif cap == "response_schema" and not model.supports_response_schema:
                    has_all_caps = False
                    break
                elif cap == "prompt_caching" and not model.supports_prompt_caching:
                    has_all_caps = False
                    break
                elif cap == "reasoning" and not model.supports_reasoning:
                    has_all_caps = False
                    break
            if not has_all_caps:
                continue

        # Check if model supports required token counts
        if input_tokens > model.context_window or output_tokens > (model.max_output_tokens or model.context_window):
            continue

        # Calculate cost for this task
        cost = model.calculate_cost(input_tokens, output_tokens)
        candidates.append((model, cost))

    if not candidates:
        return None

    # Return the model with the lowest cost
    candidates.sort(key=lambda x: x[1])
    return candidates[0][0]


def get_model_cost_info(model_name: str) -> Dict[str, float]:
    """
    Get cost information for a specific model.

    Args:
        model_name: Name of the model to look up

    Returns:
        Dictionary with input_cost_per_1k_tokens and output_cost_per_1k_tokens
    """
    model_info = get_model_info(model_name)
    if model_info:
        return {
            "input_cost_per_1k_tokens": model_info.input_cost_per_token * 1000,
            "output_cost_per_1k_tokens": model_info.output_cost_per_token * 1000
        }

    # Default values if model not found
    return {
        "input_cost_per_1k_tokens": 0.01,
        "output_cost_per_1k_tokens": 0.03
    }


def list_all_models() -> List[str]:
    """
    Get a list of all available model names.

    Returns:
        List of model names
    """
    return list(MODEL_REGISTRY.keys())


def list_all_providers() -> List[ModelProvider]:
    """
    Get a list of all supported providers.

    Returns:
        List of ModelProvider enums
    """
    return list(set(model.provider for model in MODEL_REGISTRY.values()))


def get_models_by_capability(capability: str) -> List[ModelInfo]:
    """
    Get all models that support a specific capability.
    
    Args:
        capability: Capability to filter by (function_calling, vision, etc.)
        
    Returns:
        List of ModelInfo objects that support the capability
    """
    models = []
    for model in MODEL_REGISTRY.values():
        if capability == "function_calling" and model.supports_function_calling:
            models.append(model)
        elif capability == "vision" and model.supports_vision:
            models.append(model)
        elif capability == "system_messages" and model.supports_system_messages:
            models.append(model)
        elif capability == "response_schema" and model.supports_response_schema:
            models.append(model)
        elif capability == "prompt_caching" and model.supports_prompt_caching:
            models.append(model)
        elif capability == "reasoning" and model.supports_reasoning:
            models.append(model)
    
    return models


def get_top_performing_models(task_type: str, limit: int = 5) -> List[ModelInfo]:
    """
    Get top performing models for a specific task type.
    
    Args:
        task_type: Type of task (coding, reasoning, agents, etc.)
        limit: Number of models to return
        
    Returns:
        List of top performing ModelInfo objects
    """
    if task_type == "coding":
        # Sort by coding ability
        sorted_models = sorted(
            MODEL_REGISTRY.values(),
            key=lambda m: m.characteristics.coding,
            reverse=True
        )
    elif task_type == "reasoning":
        # Sort by reasoning ability
        sorted_models = sorted(
            MODEL_REGISTRY.values(),
            key=lambda m: m.characteristics.reasoning,
            reverse=True
        )
    elif task_type == "agents":
        # Sort by agent capability
        sorted_models = sorted(
            MODEL_REGISTRY.values(),
            key=lambda m: m.characteristics.agents,
            reverse=True
        )
    elif task_type == "creative":
        # Sort by creative ability
        sorted_models = sorted(
            MODEL_REGISTRY.values(),
            key=lambda m: m.characteristics.creative,
            reverse=True
        )
    else:
        # Default: sort by average score
        sorted_models = sorted(
            MODEL_REGISTRY.values(),
            key=lambda m: m.characteristics.get_average_score(),
            reverse=True
        )
    
    return sorted_models[:limit]