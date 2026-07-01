"""
Model Registry for Weebot - AI Model Characteristics & Pricing Information

This module provides a registry of AI models with their characteristics, 
pricing information, and capabilities for intelligent model selection.
"""
import json
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional
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
    MINIMAX = "minimax"
    MOONSHOT = "moonshot"
    XAI = "xai"
    RECRAFT = "recraft"
    SOURCEFUL = "sourceful"
    BLACK_FOREST_LABS = "black_forest_labs"
    BYTEDANCE = "bytedance"
    MICROSOFT = "microsoft"
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

    @classmethod
    def from_model_name(cls, model_name: str) -> "ModelProvider":
        """Infer provider from a model name string."""
        return _infer_provider_from_model_name(model_name)


@dataclass
class ModelInfo:
    """Information about a specific AI model."""
    model_name: str
    provider: ModelProvider
    input_cost_per_token: float
    output_cost_per_token: float
    max_input_tokens: int
    max_output_tokens: int
    supports_function_calling: bool = False
    supports_vision: bool = False
    supports_audio_input: bool = False
    supports_audio_output: bool = False
    supports_system_messages: bool = True
    supports_response_schema: bool = False
    supports_prompt_caching: bool = False
    description: str = ""
    
    def calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Calculate the cost for a specific usage."""
        return (input_tokens * self.input_cost_per_token) + (output_tokens * self.output_cost_per_token)

    def calculate_cost_per_1k_tokens(self) -> float:
        """Get the average cost per 1k tokens (assuming equal input/output)."""
        return (self.input_cost_per_token + self.output_cost_per_token) * 1000


def _load_model_registry() -> Dict[str, ModelInfo]:
    """Load model registry from built-in defaults."""
    return _get_default_model_registry()


def _infer_provider_from_model_name(model_name: str) -> ModelProvider:
    """Infer provider from model name pattern.

    Covers both prefixed names (``openrouter/auto``) and bare names
    (``deepseek-chat``, ``claude-3.5-sonnet``, ``kimi-k2-0905``).
    """
    name = model_name.lower()
    # Known direct-provider prefixes (checked BEFORE the generic OpenRouter catch-all).
    # These have direct API adapters with provider-specific API keys.
    if name.startswith("deepseek/"):
        return ModelProvider.DEEPSEEK
    if name.startswith("moonshotai/") or name.startswith("moonshot/"):
        return ModelProvider.MOONSHOT
    if name.startswith("minimax/"):
        return ModelProvider.MINIMAX
    if name.startswith("recraft/"):
        return ModelProvider.RECRAFT
    if name.startswith("sourceful/"):
        return ModelProvider.SOURCEFUL
    if name.startswith("black-forest-labs/"):
        return ModelProvider.BLACK_FOREST_LABS
    if name.startswith("bytedance-seed/"):
        return ModelProvider.BYTEDANCE
    if name.startswith("microsoft/"):
        return ModelProvider.MICROSOFT
    if name.startswith("x-ai/"):
        return ModelProvider.XAI
    if name.startswith("claude/"):
        return ModelProvider.ANTHROPIC
    if name.startswith("gemini/") or name.startswith("google/"):
        return ModelProvider.GOOGLE
    if name.startswith("azure/"):
        return ModelProvider.AZURE
    if name.startswith("bedrock/"):
        return ModelProvider.AWS_BEDROCK
    # Remaining prefixed names → OpenRouter
    if name.startswith("openrouter/") or "/" in name:
        return ModelProvider.OPENROUTER
    # Bare names (direct provider model IDs)
    if name.startswith("gpt-"):
        return ModelProvider.OPENAI
    if name.startswith("claude-") or name.startswith("claude"):
        return ModelProvider.ANTHROPIC
    if name.startswith("deepseek"):
        return ModelProvider.DEEPSEEK
    if name.startswith("kimi-") or name.startswith("moonshot"):
        return ModelProvider.MOONSHOT
    if name.startswith("grok"):
        return ModelProvider.XAI
    if name.startswith("gemini") or name.startswith("google-"):
        return ModelProvider.GEMINI
    if name.startswith("mistral"):
        return ModelProvider.MISTRAL
    if name.startswith("llama") or name.startswith("qwen") or name.startswith("phi"):
        return ModelProvider.OLLAMA
    # Default to OpenAI for unknown models
    return ModelProvider.OPENAI


def _get_default_model_registry() -> Dict[str, ModelInfo]:
    """Get a default model registry with common models."""
    return {
        # Frontier/Reasoning Models
        "minimax/minimax-m3": ModelInfo(
            model_name="minimax/minimax-m3",
            provider=ModelProvider.MINIMAX,
            input_cost_per_token=0.0,          # FREE via OpenRouter
            output_cost_per_token=0.0,         # FREE via OpenRouter
            max_input_tokens=1_000_000,        # 1M context (MSA architecture)
            max_output_tokens=32768,
            supports_function_calling=True,
            supports_vision=True,              # native multimodal (image + video)
            supports_system_messages=True,
            supports_response_schema=True,
            description=(
                "MiniMax M3 — open-weight frontier model, FREE via OpenRouter. "
                "1M context via MSA (MiniMax Sparse Attention), 59% SWE-Bench Pro "
                "(beats GPT-5.5), native multimodal (image/video), interleaved "
                "thinking between tool calls, 24h+ autonomous execution. "
                "Direct API: MINIMAX_API_KEY + https://api.minimax.io (OpenAI SDK) "
                "or /anthropic (Anthropic SDK), native model 'MiniMax-M3'. "
                "MCP: minimax-coding-plan-mcp (web_search). "
                "Docs: https://platform.minimax.io/docs/guides/text-m3-function-call"
            ),
        ),
        "claude-4.6-opus": ModelInfo(
            model_name="claude-4.6-opus",
            provider=ModelProvider.ANTHROPIC,
            input_cost_per_token=5e-06,  # $5.0 per 1M tokens
            output_cost_per_token=2.5e-05,  # $25.0 per 1M tokens
            max_input_tokens=1000000,  # 1M context
            max_output_tokens=4096,
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="Anthropic's Claude Opus 4.6 - Frontier model for deep reasoning, agent teams, and long-horizon tasks. Native multi-agent collaboration with 14.5h autonomous task horizon."
        ),
        "gpt-5.2": ModelInfo(
            model_name="gpt-5.2",
            provider=ModelProvider.OPENAI,
            input_cost_per_token=1.75e-06,  # $1.75 per 1M tokens
            output_cost_per_token=3e-05,  # $30.0 per 1M tokens
            max_input_tokens=400000,  # 400K context
            max_output_tokens=4096,
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="OpenAI's GPT-5.2 - Frontier model for multi-step reasoning, math, and multimodal tasks. Strong decomposition stability but high output cost."
        ),
        "gemini-3-pro": ModelInfo(
            model_name="gemini-3-pro",
            provider=ModelProvider.GOOGLE,
            input_cost_per_token=1.25e-06,  # $1.25 per 1M tokens
            output_cost_per_token=1e-05,  # $10.0 per 1M tokens
            max_input_tokens=1000000,  # 1M context
            max_output_tokens=8192,
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="Google's Gemini 3 Pro - Frontier model with 1M native context, strong in math reasoning (100% AIME 2025 with code exec). Charges for thinking tokens."
        ),
        "grok-4.1": ModelInfo(
            model_name="grok-4.1",
            provider=ModelProvider.XAI,
            input_cost_per_token=3e-06,  # $3.0 per 1M tokens
            output_cost_per_token=1.5e-05,  # $15.0 per 1M tokens
            max_input_tokens=2000000,  # 2M context
            max_output_tokens=8192,
            supports_function_calling=True,
            supports_vision=False,
            supports_system_messages=True,
            supports_response_schema=False,
            description="xAI's Grok 4.1 - Frontier model for pure reasoning with 2M context window and ~4% hallucination rate. #1 LMArena Elo (1483)."
        ),
        "grok-build-0.1": ModelInfo(
            model_name="grok-build-0.1",
            provider=ModelProvider.XAI,
            input_cost_per_token=0.0,       # pricing TBD
            output_cost_per_token=0.0,      # pricing TBD
            max_input_tokens=131072,        # 128K context
            max_output_tokens=16384,
            supports_function_calling=True,
            supports_vision=False,
            supports_system_messages=True,
            supports_response_schema=False,
            description="xAI Grok Build 0.1 — fast coding model for agentic SWE workflows. Direct API: XAI_API_KEY + https://api.x.ai/v1."
        ),
        
        # Performance/Best Value Models
        "claude-4.6-sonnet": ModelInfo(  # Map to Sonnet 5 — drop-in replacement
            model_name="openrouter/anthropic/claude-sonnet-5",
            provider=ModelProvider.ANTHROPIC,
            input_cost_per_token=3e-06,  # $3.0 per 1M tokens
            output_cost_per_token=1.5e-05,  # $15.0 per 1M tokens
            max_input_tokens=200000,  # 200K context
            max_output_tokens=8192,
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="Anthropic's Claude Sonnet 5 via OpenRouter — drop-in upgrade from Sonnet 4.6. Best value for coding agents and production use."
        ),
        "gpt-5.1": ModelInfo(
            model_name="gpt-5.1",
            provider=ModelProvider.OPENAI,
            input_cost_per_token=1.25e-06,  # $1.25 per 1M tokens
            output_cost_per_token=1e-05,  # $10.0 per 1M tokens
            max_input_tokens=400000,  # 400K context
            max_output_tokens=4096,
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="OpenAI's GPT-5.1 - Configurable reasoning effort with good balance of speed/quality. Perfect for agentic workflows."
        ),
        "deepseek-r1": ModelInfo(
            model_name="deepseek-r1",
            provider=ModelProvider.DEEPSEEK,
            input_cost_per_token=5.5e-07,  # $0.55 per 1M tokens
            output_cost_per_token=2.19e-06,  # $2.19 per 1M tokens
            max_input_tokens=128000,  # 128K context
            max_output_tokens=4096,
            supports_function_calling=True,
            supports_vision=False,
            supports_system_messages=True,
            supports_response_schema=False,
            description="DeepSeek's R1 - Strong reasoning at fraction of cost with 87.5% AIME score. Good for specialized reasoning agents."
        ),
        
        # Budget/High-Volume Models
        "claude-4.5-haiku": ModelInfo(
            model_name="claude-4.5-haiku",
            provider=ModelProvider.ANTHROPIC,
            input_cost_per_token=1e-06,  # $1.0 per 1M tokens
            output_cost_per_token=5e-06,  # $5.0 per 1M tokens
            max_input_tokens=200000,  # 200K context
            max_output_tokens=4096,
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="Anthropic's Claude Haiku 4.5 - Fast classification for agent orchestration. Ideal as router model in multi-agent systems."
        ),
        "gpt-5-mini": ModelInfo(
            model_name="gpt-5-mini",
            provider=ModelProvider.OPENAI,
            input_cost_per_token=2.5e-07,  # $0.25 per 1M tokens
            output_cost_per_token=2e-06,  # $2.0 per 1M tokens
            max_input_tokens=128000,  # 128K context
            max_output_tokens=4096,
            supports_function_calling=True,
            supports_vision=False,
            supports_system_messages=True,
            supports_response_schema=False,
            description="OpenAI's GPT-5 Mini - Budget option for simple agent tasks and inner-loop routing decisions."
        ),
        "gemini-2.5-flash": ModelInfo(
            model_name="gemini-2.5-flash",
            provider=ModelProvider.GEMINI,
            input_cost_per_token=1.5e-07,  # $0.15 per 1M tokens
            output_cost_per_token=6e-07,  # $0.60 per 1M tokens
            max_input_tokens=1000000,  # 1M context
            max_output_tokens=8192,
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="Google's Gemini 2.5 Flash - Cheapest option with 1M context. Great for summarization sub-agents and ultra-cheap operations."
        ),
        "deepseek-v3.2": ModelInfo(
            model_name="deepseek-v3.2",
            provider=ModelProvider.DEEPSEEK,
            input_cost_per_token=1.4e-07,  # $0.14 per 1M tokens
            output_cost_per_token=2.8e-07,  # $0.28 per 1M tokens
            max_input_tokens=128000,  # 128K context
            max_output_tokens=4096,
            supports_function_calling=True,
            supports_vision=False,
            supports_system_messages=True,
            supports_response_schema=False,
            description="DeepSeek's V3.2 - Ultra-budget model (~100x cheaper than GPT-5.2 output) with quality score 79/100. Best $/quality ratio."
        ),
        
        # Open Source Models
        "k2": ModelInfo(
            model_name="k2",
            provider=ModelProvider.HUGGINGFACE,  # Assuming this is hosted on HuggingFace
            input_cost_per_token=0.0,  # Free for open source
            output_cost_per_token=0.0,
            max_input_tokens=128000,  # 128K context
            max_output_tokens=4096,
            supports_function_calling=True,
            supports_vision=False,
            supports_system_messages=True,
            supports_response_schema=False,
            description="K2 Open Source model - Community model with strong agent capabilities (82) and good reasoning (78)."
        ),
        
        # Legacy models for backward compatibility
        "gpt-4o": ModelInfo(
            model_name="gpt-4o",
            provider=ModelProvider.OPENAI,
            input_cost_per_token=5e-06,
            output_cost_per_token=1.5e-05,
            max_input_tokens=128000,
            max_output_tokens=4096,
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="OpenAI's most advanced multimodal model"
        ),
        "gpt-4o-mini": ModelInfo(
            model_name="gpt-4o-mini",
            provider=ModelProvider.OPENAI,
            input_cost_per_token=1.5e-07,
            output_cost_per_token=6e-07,
            max_input_tokens=128000,
            max_output_tokens=16384,
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="OpenAI's affordable multimodal model"
        ),
        "gpt-3.5-turbo": ModelInfo(
            model_name="gpt-3.5-turbo",
            provider=ModelProvider.OPENAI,
            input_cost_per_token=5e-07,
            output_cost_per_token=1.5e-06,
            max_input_tokens=16385,
            max_output_tokens=4096,
            supports_function_calling=True,
            supports_system_messages=True,
            description="OpenAI's efficient chat model"
        ),
        
        # Anthropic Models
        "claude-3-5-sonnet-20241022": ModelInfo(
            model_name="claude-3-5-sonnet-20241022",
            provider=ModelProvider.ANTHROPIC,
            input_cost_per_token=3e-06,
            output_cost_per_token=1.5e-05,
            max_input_tokens=200000,
            max_output_tokens=8192,
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            description="Anthropic's most intelligent model"
        ),
        "claude-3-opus-20240229": ModelInfo(
            model_name="claude-3-opus-20240229",
            provider=ModelProvider.ANTHROPIC,
            input_cost_per_token=1.5e-05,
            output_cost_per_token=7.5e-05,
            max_input_tokens=200000,
            max_output_tokens=4096,
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            description="Anthropic's most powerful model"
        ),
        "claude-3-haiku-20240307": ModelInfo(
            model_name="claude-3-haiku-20240307",
            provider=ModelProvider.ANTHROPIC,
            input_cost_per_token=2.5e-07,
            output_cost_per_token=1.25e-06,
            max_input_tokens=200000,
            max_output_tokens=4096,
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            description="Anthropic's fastest model"
        ),
        
        # Google Models
        "gemini/gemini-1.5-pro": ModelInfo(
            model_name="gemini/gemini-1.5-pro",
            provider=ModelProvider.GEMINI,
            input_cost_per_token=1.25e-06,
            output_cost_per_token=5e-06,
            max_input_tokens=2000000,
            max_output_tokens=8192,
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="Google's most capable multimodal model"
        ),
        "gemini/gemini-1.5-flash": ModelInfo(
            model_name="gemini/gemini-1.5-flash",
            provider=ModelProvider.GEMINI,
            input_cost_per_token=7.5e-08,
            output_cost_per_token=3e-07,
            max_input_tokens=1000000,
            max_output_tokens=8192,
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="Google's fast and efficient multimodal model"
        ),
        
        # Mistral Models
        "mistral-large-latest": ModelInfo(
            model_name="mistral-large-latest",
            provider=ModelProvider.MISTRAL,
            input_cost_per_token=2e-06,
            output_cost_per_token=6e-06,
            max_input_tokens=32768,
            max_output_tokens=32768,
            supports_function_calling=True,
            supports_system_messages=True,
            description="Mistral's most capable model"
        ),
        "mistral-medium-latest": ModelInfo(
            model_name="mistral-medium-latest",
            provider=ModelProvider.MISTRAL,
            input_cost_per_token=2.7e-07,
            output_cost_per_token=8.1e-07,
            max_input_tokens=32768,
            max_output_tokens=32768,
            supports_function_calling=True,
            supports_system_messages=True,
            description="Mistral's balanced performance model"
        ),
        
        # Groq Models
        "groq/llama3-70b-8192": ModelInfo(
            model_name="groq/llama3-70b-8192",
            provider=ModelProvider.GROQ,
            input_cost_per_token=5.9e-07,
            output_cost_per_token=7.9e-07,
            max_input_tokens=8192,
            max_output_tokens=8192,
            supports_function_calling=True,
            supports_system_messages=True,
            description="Groq's fast Llama 3 70B model"
        ),
        "groq/llama-3.1-8b-instant": ModelInfo(
            model_name="groq/llama-3.1-8b-instant",
            provider=ModelProvider.GROQ,
            input_cost_per_token=5e-08,
            output_cost_per_token=8e-08,
            max_input_tokens=8192,
            max_output_tokens=8192,
            supports_function_calling=True,
            supports_system_messages=True,
            description="Groq's instant Llama 3.1 8B model"
        ),
        
        # Ollama Models (Local)
        "llama3": ModelInfo(
            model_name="llama3",
            provider=ModelProvider.OLLAMA,
            input_cost_per_token=0.0,
            output_cost_per_token=0.0,
            max_input_tokens=8192,
            max_output_tokens=8192,
            supports_function_calling=True,
            supports_system_messages=True,
            description="Meta's Llama 3 model (local)"
        ),
        "phi3": ModelInfo(
            model_name="phi3",
            provider=ModelProvider.OLLAMA,
            input_cost_per_token=0.0,
            output_cost_per_token=0.0,
            max_input_tokens=4096,
            max_output_tokens=4096,
            supports_function_calling=True,
            supports_system_messages=True,
            description="Microsoft's Phi-3 model (local)"
        ),
        
        # DeepSeek Models
        "deepseek-chat": ModelInfo(
            model_name="deepseek-chat",
            provider=ModelProvider.DEEPSEEK,
            input_cost_per_token=1.4e-07,
            output_cost_per_token=2.8e-07,
            max_input_tokens=128000,
            max_output_tokens=4096,
            supports_function_calling=True,
            supports_system_messages=True,
            description="DeepSeek's efficient chat model (legacy)"
        ),
        "deepseek-coder": ModelInfo(
            model_name="deepseek-coder",
            provider=ModelProvider.DEEPSEEK,
            input_cost_per_token=1.4e-07,
            output_cost_per_token=2.8e-07,
            max_input_tokens=128000,
            max_output_tokens=4096,
            supports_function_calling=True,
            supports_system_messages=True,
            description="DeepSeek's code generation model (legacy)"
        ),
        "deepseek-v4-pro": ModelInfo(
            model_name="deepseek-v4-pro",
            provider=ModelProvider.DEEPSEEK,
            input_cost_per_token=5.5e-07,     # $0.55/M input
            output_cost_per_token=2.19e-06,   # $2.19/M output
            max_input_tokens=163840,           # 160K context (per OpenRouter listing)
            max_output_tokens=8192,
            supports_function_calling=True,    # confirmed: tool-calls docs
            supports_system_messages=True,
            supports_response_schema=True,     # confirmed: json_mode docs
            description=(
                "DeepSeek V4 Pro — strongest reasoning model with chain-of-thought "
                "thinking mode (thinking parameter via extra_body, reasoning_effort: "
                "high/max).  Supports tool calls in thinking mode (≥V3.2), strict "
                "function calling (beta), JSON mode, and KV-cache for >1MB prefixes. "
                "Note: temperature/top_p have no effect in thinking mode. "
                "Docs: https://api-docs.deepseek.com/"
            ),
        ),
        "deepseek-v4-flash": ModelInfo(
            model_name="deepseek-v4-flash",
            provider=ModelProvider.DEEPSEEK,
            input_cost_per_token=2.7e-07,     # $0.27/M input
            output_cost_per_token=1.1e-06,    # $1.10/M output
            max_input_tokens=163840,           # 160K context
            max_output_tokens=8192,
            supports_function_calling=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description=(
                "DeepSeek V4 Flash — fast, cost-efficient variant of V4 Pro. "
                "Supports thinking mode, tool calls, JSON mode. "
                "Docs: https://api-docs.deepseek.com/"
            ),
        ),
        
        # Moonshot / Kimi Models
        "moonshot-v1-8k": ModelInfo(
            model_name="moonshot-v1-8k",
            provider=ModelProvider.MOONSHOT,
            input_cost_per_token=1.2e-06,
            output_cost_per_token=1.2e-06,
            max_input_tokens=8192,
            max_output_tokens=8192,
            supports_function_calling=True,
            supports_system_messages=True,
            description="Moonshot's 8K context model (legacy)"
        ),
        "moonshot-v1-32k": ModelInfo(
            model_name="moonshot-v1-32k",
            provider=ModelProvider.MOONSHOT,
            input_cost_per_token=2.4e-06,
            output_cost_per_token=2.4e-06,
            max_input_tokens=32768,
            max_output_tokens=32768,
            supports_function_calling=True,
            supports_system_messages=True,
            description="Moonshot's 32K context model (legacy)"
        ),
        "kimi-k2.6": ModelInfo(
            model_name="kimi-k2.6",
            provider=ModelProvider.MOONSHOT,
            input_cost_per_token=1.0e-06,   # $1.0/M input (approximate — check pricing page)
            output_cost_per_token=4.0e-06,  # $4.0/M output
            max_input_tokens=262144,         # 256K context
            max_output_tokens=32768,         # 32K output (1024*32 from docs example)
            supports_function_calling=True,  # confirmed: tool-use docs
            supports_vision=True,            # confirmed: model comparison shows vision support
            supports_system_messages=True,
            supports_response_schema=True,
            description=(
                "Kimi K2.6 — Moonshot's flagship model with improved long-context "
                "coding stability, tool use, vision, and optional deep-thinking mode "
                "(thinking parameter via extra_body). 256K context, 32K output. "
                "Docs: https://platform.kimi.ai/docs/api/"
            ),
        ),
        
        # XAI Models
        "grok/grok-2-1212": ModelInfo(
            model_name="grok/grok-2-1212",
            provider=ModelProvider.XAI,
            input_cost_per_token=5e-07,
            output_cost_per_token=1.5e-06,
            max_input_tokens=8192,
            max_output_tokens=8192,
            supports_function_calling=True,
            supports_system_messages=True,
            description="XAI's Grok 2 model"
        ),
        
        # OpenRouter Models
        "qwen/qwen3.7-plus": ModelInfo(
            model_name="qwen/qwen3.7-plus",
            provider=ModelProvider.OPENROUTER,
            input_cost_per_token=1.5e-06,
            output_cost_per_token=6e-06,
            max_input_tokens=131072,
            max_output_tokens=32768,
            supports_function_calling=True,
            supports_vision=False,
            supports_system_messages=True,
            supports_response_schema=True,
            description="Qwen 3.7 Plus — powerful reasoning model via OpenRouter (weebot default)"
        ),
        "openrouter/google/gemini-2.5-flash": ModelInfo(
            model_name="openrouter/google/gemini-2.5-flash",
            provider=ModelProvider.OPENROUTER,
            input_cost_per_token=7.5e-08,
            output_cost_per_token=3e-07,
            max_input_tokens=1000000,
            max_output_tokens=8192,
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="Google Gemini 2.5 Flash via OpenRouter"
        ),
        "openrouter/anthropic/claude-3.5-sonnet": ModelInfo(
            model_name="openrouter/anthropic/claude-3.5-sonnet",
            provider=ModelProvider.OPENROUTER,
            input_cost_per_token=3e-06,
            output_cost_per_token=1.5e-05,
            max_input_tokens=200000,
            max_output_tokens=8192,
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="Anthropic Claude 3.5 Sonnet via OpenRouter"
        ),
        "openrouter/openai/gpt-4o-mini": ModelInfo(
            model_name="openrouter/openai/gpt-4o-mini",
            provider=ModelProvider.OPENROUTER,
            input_cost_per_token=1.5e-07,
            output_cost_per_token=6e-07,
            max_input_tokens=128000,
            max_output_tokens=16384,
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="OpenAI GPT-4o Mini via OpenRouter"
        ),
        "openrouter/auto": ModelInfo(
            model_name="openrouter/auto",
            provider=ModelProvider.OPENROUTER,
            input_cost_per_token=5e-06,
            output_cost_per_token=1.5e-05,
            max_input_tokens=2000000,
            max_output_tokens=8192,
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="OpenRouter Auto - automatically selects the best model via NotDiamond"
        ),
        "openrouter/openai/gpt-4.1": ModelInfo(
            model_name="openrouter/openai/gpt-4.1",
            provider=ModelProvider.OPENROUTER,
            input_cost_per_token=2e-06,
            output_cost_per_token=8e-06,
            max_input_tokens=1047576,
            max_output_tokens=32768,
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="OpenAI GPT-4.1 via OpenRouter"
        ),
        "openrouter/openai/gpt-4.1-mini": ModelInfo(
            model_name="openrouter/openai/gpt-4.1-mini",
            provider=ModelProvider.OPENROUTER,
            input_cost_per_token=4e-07,
            output_cost_per_token=1.6e-06,
            max_input_tokens=1047576,
            max_output_tokens=32768,
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="OpenAI GPT-4.1 Mini via OpenRouter"
        ),
        "openrouter/anthropic/claude-3.7-sonnet": ModelInfo(
            model_name="openrouter/anthropic/claude-3.7-sonnet",
            provider=ModelProvider.OPENROUTER,
            input_cost_per_token=3e-06,
            output_cost_per_token=1.5e-05,
            max_input_tokens=200000,
            max_output_tokens=8192,
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="Anthropic Claude 3.7 Sonnet via OpenRouter"
        ),
        "openrouter/anthropic/claude-opus-4.6": ModelInfo(
            model_name="openrouter/anthropic/claude-opus-4.6",
            provider=ModelProvider.OPENROUTER,
            input_cost_per_token=3e-05,
            output_cost_per_token=7.5e-05,
            max_input_tokens=1000000,
            max_output_tokens=8192,
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="Anthropic Claude Opus 4.6 via OpenRouter"
        ),
        "openrouter/google/gemini-2.5-pro": ModelInfo(
            model_name="openrouter/google/gemini-2.5-pro",
            provider=ModelProvider.OPENROUTER,
            input_cost_per_token=2.5e-06,
            output_cost_per_token=1e-05,
            max_input_tokens=1000000,
            max_output_tokens=8192,
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="Google Gemini 2.5 Pro via OpenRouter"
        ),
        "openrouter/deepseek/deepseek-chat-v3.1": ModelInfo(
            model_name="openrouter/deepseek/deepseek-chat-v3.1",
            provider=ModelProvider.OPENROUTER,
            input_cost_per_token=1.5e-07,
            output_cost_per_token=7.5e-07,
            max_input_tokens=32768,
            max_output_tokens=4096,
            supports_function_calling=True,
            supports_system_messages=True,
            description="DeepSeek Chat V3.1 via OpenRouter"
        ),
        "openrouter/deepseek/deepseek-r1-0528": ModelInfo(
            model_name="openrouter/deepseek/deepseek-r1-0528",
            provider=ModelProvider.OPENROUTER,
            input_cost_per_token=5.5e-07,
            output_cost_per_token=2.19e-06,
            max_input_tokens=163840,
            max_output_tokens=8192,
            supports_function_calling=True,
            supports_system_messages=True,
            description="DeepSeek R1 reasoning model via OpenRouter"
        ),
        "openrouter/x-ai/grok-4.1-fast": ModelInfo(
            model_name="openrouter/x-ai/grok-4.1-fast",
            provider=ModelProvider.OPENROUTER,
            input_cost_per_token=2e-07,
            output_cost_per_token=5e-07,
            max_input_tokens=2000000,
            max_output_tokens=8192,
            supports_function_calling=True,
            supports_system_messages=True,
            description="xAI Grok 4.1 Fast via OpenRouter"
        ),
        "openrouter/meta-llama/llama-4-maverick": ModelInfo(
            model_name="openrouter/meta-llama/llama-4-maverick",
            provider=ModelProvider.OPENROUTER,
            input_cost_per_token=1.5e-07,
            output_cost_per_token=6e-07,
            max_input_tokens=1048576,
            max_output_tokens=8192,
            supports_function_calling=True,
            supports_system_messages=True,
            description="Meta Llama 4 Maverick via OpenRouter"
        ),
        "openrouter/moonshotai/kimi-k2.5": ModelInfo(
            model_name="openrouter/moonshotai/kimi-k2.5",
            provider=ModelProvider.OPENROUTER,
            input_cost_per_token=2.5e-06,
            output_cost_per_token=1e-05,
            max_input_tokens=262144,
            max_output_tokens=8192,
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="Moonshot Kimi K2.5 via OpenRouter"
        ),

        # ═══════════════════════════════════════════════════════════════
        # Image Generation Models (text → image, via OpenRouter)
        # ═══════════════════════════════════════════════════════════════

        # ── Sourceful Riverflow (FREE tier) ──────────────────────────
        "sourceful/riverflow-v2.5-pro:free": ModelInfo(
            model_name="sourceful/riverflow-v2.5-pro:free",
            provider=ModelProvider.SOURCEFUL,
            input_cost_per_token=0.0, output_cost_per_token=0.0,
            max_input_tokens=4096, max_output_tokens=1,
            supports_function_calling=False, supports_vision=False,
            supports_system_messages=True,
            description="Sourceful Riverflow V2.5 Pro (FREE) — high-quality text-to-image. Best free image gen on OpenRouter."
        ),
        "sourceful/riverflow-v2.5-fast:free": ModelInfo(
            model_name="sourceful/riverflow-v2.5-fast:free",
            provider=ModelProvider.SOURCEFUL,
            input_cost_per_token=0.0, output_cost_per_token=0.0,
            max_input_tokens=4096, max_output_tokens=1,
            supports_function_calling=False, supports_vision=False,
            supports_system_messages=True,
            description="Sourceful Riverflow V2.5 Fast (FREE) — fast text-to-image generation. Lower quality than Pro, 2-3x faster."
        ),

        # ── Sourceful Riverflow (Paid) ───────────────────────────────
        "sourceful/riverflow-v2-pro": ModelInfo(
            model_name="sourceful/riverflow-v2-pro",
            provider=ModelProvider.SOURCEFUL,
            input_cost_per_token=8e-06, output_cost_per_token=0.0,
            max_input_tokens=4096, max_output_tokens=1,
            supports_function_calling=False, supports_vision=False,
            supports_system_messages=True,
            description="Sourceful Riverflow V2 Pro — premium text-to-image generation, max quality."
        ),
        "sourceful/riverflow-v2-fast": ModelInfo(
            model_name="sourceful/riverflow-v2-fast",
            provider=ModelProvider.SOURCEFUL,
            input_cost_per_token=4e-06, output_cost_per_token=0.0,
            max_input_tokens=4096, max_output_tokens=1,
            supports_function_calling=False, supports_vision=False,
            supports_system_messages=True,
            description="Sourceful Riverflow V2 Fast — fast, cost-effective text-to-image."
        ),
        "sourceful/riverflow-v2-max-preview": ModelInfo(
            model_name="sourceful/riverflow-v2-max-preview",
            provider=ModelProvider.SOURCEFUL,
            input_cost_per_token=0.0, output_cost_per_token=0.0,
            max_input_tokens=4096, max_output_tokens=1,
            supports_function_calling=False, supports_vision=False,
            supports_system_messages=True,
            description="Sourceful Riverflow V2 Max Preview (FREE) — max resolution preview."
        ),
        "sourceful/riverflow-v2-standard-preview": ModelInfo(
            model_name="sourceful/riverflow-v2-standard-preview",
            provider=ModelProvider.SOURCEFUL,
            input_cost_per_token=0.0, output_cost_per_token=0.0,
            max_input_tokens=4096, max_output_tokens=1,
            supports_function_calling=False, supports_vision=False,
            supports_system_messages=True,
            description="Sourceful Riverflow V2 Standard Preview (FREE) — standard quality preview."
        ),
        "sourceful/riverflow-v2-fast-preview": ModelInfo(
            model_name="sourceful/riverflow-v2-fast-preview",
            provider=ModelProvider.SOURCEFUL,
            input_cost_per_token=0.0, output_cost_per_token=0.0,
            max_input_tokens=4096, max_output_tokens=1,
            supports_function_calling=False, supports_vision=False,
            supports_system_messages=True,
            description="Sourceful Riverflow V2 Fast Preview (FREE) — fastest preview generation."
        ),

        # ── Recraft (professional design, vector + raster) ───────────
        "recraft/recraft-v4.1-pro-vector": ModelInfo(
            model_name="recraft/recraft-v4.1-pro-vector",
            provider=ModelProvider.RECRAFT,
            input_cost_per_token=1e-05, output_cost_per_token=0.0,
            max_input_tokens=4096, max_output_tokens=1,
            supports_function_calling=False, supports_vision=False,
            supports_system_messages=True,
            description="Recraft V4.1 Pro Vector — professional SVG/vector design generation. Best for logos, icons, brand assets."
        ),
        "recraft/recraft-v4.1-vector": ModelInfo(
            model_name="recraft/recraft-v4.1-vector",
            provider=ModelProvider.RECRAFT,
            input_cost_per_token=8e-06, output_cost_per_token=0.0,
            max_input_tokens=4096, max_output_tokens=1,
            supports_function_calling=False, supports_vision=False,
            supports_system_messages=True,
            description="Recraft V4.1 Vector — standard vector design generation."
        ),
        "recraft/recraft-v4.1-utility-pro": ModelInfo(
            model_name="recraft/recraft-v4.1-utility-pro",
            provider=ModelProvider.RECRAFT,
            input_cost_per_token=1e-05, output_cost_per_token=0.0,
            max_input_tokens=4096, max_output_tokens=1,
            supports_function_calling=False, supports_vision=False,
            supports_system_messages=True,
            description="Recraft V4.1 Utility Pro — image editing, upscaling, background removal, style transfer."
        ),
        "recraft/recraft-v4.1-utility": ModelInfo(
            model_name="recraft/recraft-v4.1-utility",
            provider=ModelProvider.RECRAFT,
            input_cost_per_token=8e-06, output_cost_per_token=0.0,
            max_input_tokens=4096, max_output_tokens=1,
            supports_function_calling=False, supports_vision=False,
            supports_system_messages=True,
            description="Recraft V4.1 Utility — standard image editing and manipulation."
        ),
        "recraft/recraft-v4.1-pro": ModelInfo(
            model_name="recraft/recraft-v4.1-pro",
            provider=ModelProvider.RECRAFT,
            input_cost_per_token=1e-05, output_cost_per_token=0.0,
            max_input_tokens=4096, max_output_tokens=1,
            supports_function_calling=False, supports_vision=False,
            supports_system_messages=True,
            description="Recraft V4.1 Pro — premium raster image generation, highest quality."
        ),
        "recraft/recraft-v4.1": ModelInfo(
            model_name="recraft/recraft-v4.1",
            provider=ModelProvider.RECRAFT,
            input_cost_per_token=8e-06, output_cost_per_token=0.0,
            max_input_tokens=4096, max_output_tokens=1,
            supports_function_calling=False, supports_vision=False,
            supports_system_messages=True,
            description="Recraft V4.1 — standard raster image generation."
        ),
        "recraft/recraft-v4-pro-vector": ModelInfo(
            model_name="recraft/recraft-v4-pro-vector",
            provider=ModelProvider.RECRAFT,
            input_cost_per_token=1e-05, output_cost_per_token=0.0,
            max_input_tokens=4096, max_output_tokens=1,
            supports_function_calling=False, supports_vision=False,
            supports_system_messages=True,
            description="Recraft V4 Pro Vector — premium vector generation (previous generation)."
        ),
        "recraft/recraft-v4-vector": ModelInfo(
            model_name="recraft/recraft-v4-vector",
            provider=ModelProvider.RECRAFT,
            input_cost_per_token=8e-06, output_cost_per_token=0.0,
            max_input_tokens=4096, max_output_tokens=1,
            supports_function_calling=False, supports_vision=False,
            supports_system_messages=True,
            description="Recraft V4 Vector — standard vector generation (previous generation)."
        ),
        "recraft/recraft-v4-pro": ModelInfo(
            model_name="recraft/recraft-v4-pro",
            provider=ModelProvider.RECRAFT,
            input_cost_per_token=1e-05, output_cost_per_token=0.0,
            max_input_tokens=4096, max_output_tokens=1,
            supports_function_calling=False, supports_vision=False,
            supports_system_messages=True,
            description="Recraft V4 Pro — premium raster (previous generation)."
        ),
        "recraft/recraft-v4": ModelInfo(
            model_name="recraft/recraft-v4",
            provider=ModelProvider.RECRAFT,
            input_cost_per_token=8e-06, output_cost_per_token=0.0,
            max_input_tokens=4096, max_output_tokens=1,
            supports_function_calling=False, supports_vision=False,
            supports_system_messages=True,
            description="Recraft V4 — standard raster (previous generation)."
        ),
        "recraft/recraft-v3": ModelInfo(
            model_name="recraft/recraft-v3",
            provider=ModelProvider.RECRAFT,
            input_cost_per_token=8e-06, output_cost_per_token=0.0,
            max_input_tokens=4096, max_output_tokens=1,
            supports_function_calling=False, supports_vision=False,
            supports_system_messages=True,
            description="Recraft V3 — legacy image generation model."
        ),

        # ── Black Forest Labs Flux ──────────────────────────────────
        "black-forest-labs/flux.2-pro": ModelInfo(
            model_name="black-forest-labs/flux.2-pro",
            provider=ModelProvider.BLACK_FOREST_LABS,
            input_cost_per_token=5e-06, output_cost_per_token=0.0,
            max_input_tokens=4096, max_output_tokens=1,
            supports_function_calling=False, supports_vision=False,
            supports_system_messages=True,
            description="Flux.2 Pro — Black Forest Labs' highest-quality text-to-image. Photorealistic output, excellent prompt adherence."
        ),
        "black-forest-labs/flux.2-max": ModelInfo(
            model_name="black-forest-labs/flux.2-max",
            provider=ModelProvider.BLACK_FOREST_LABS,
            input_cost_per_token=8e-06, output_cost_per_token=0.0,
            max_input_tokens=4096, max_output_tokens=1,
            supports_function_calling=False, supports_vision=False,
            supports_system_messages=True,
            description="Flux.2 Max — maximum resolution and detail. For print-ready, high-DPI outputs."
        ),
        "black-forest-labs/flux.2-flex": ModelInfo(
            model_name="black-forest-labs/flux.2-flex",
            provider=ModelProvider.BLACK_FOREST_LABS,
            input_cost_per_token=3e-06, output_cost_per_token=0.0,
            max_input_tokens=4096, max_output_tokens=1,
            supports_function_calling=False, supports_vision=False,
            supports_system_messages=True,
            description="Flux.2 Flex — balanced quality/speed for batch generation and iterations."
        ),
        "black-forest-labs/flux.2-klein-4b": ModelInfo(
            model_name="black-forest-labs/flux.2-klein-4b",
            provider=ModelProvider.BLACK_FOREST_LABS,
            input_cost_per_token=1e-06, output_cost_per_token=0.0,
            max_input_tokens=4096, max_output_tokens=1,
            supports_function_calling=False, supports_vision=False,
            supports_system_messages=True,
            description="Flux.2 Klein 4B — lightweight 4B-param variant. Fast, cheap, good for thumbnails and icons."
        ),

        # ── Google Gemini Image ─────────────────────────────────────
        "google/gemini-2.5-flash-image": ModelInfo(
            model_name="google/gemini-2.5-flash-image",
            provider=ModelProvider.GEMINI,
            input_cost_per_token=1e-06, output_cost_per_token=0.0,
            max_input_tokens=4096, max_output_tokens=1,
            supports_function_calling=False, supports_vision=False,
            supports_system_messages=True,
            description="Gemini 2.5 Flash Image — Google's fast text-to-image via Gemini. Good for diagrams, UI mockups, illustrations."
        ),
        "google/gemini-3.1-flash-image-preview": ModelInfo(
            model_name="google/gemini-3.1-flash-image-preview",
            provider=ModelProvider.GEMINI,
            input_cost_per_token=0.0, output_cost_per_token=0.0,
            max_input_tokens=4096, max_output_tokens=1,
            supports_function_calling=False, supports_vision=False,
            supports_system_messages=True,
            description="Gemini 3.1 Flash Image Preview (FREE) — next-gen Gemini image generation. Experimental."
        ),

        # ── xAI Grok Imagine ────────────────────────────────────────
        "x-ai/grok-imagine-image-quality": ModelInfo(
            model_name="x-ai/grok-imagine-image-quality",
            provider=ModelProvider.XAI,
            input_cost_per_token=5e-06, output_cost_per_token=0.0,
            max_input_tokens=4096, max_output_tokens=1,
            supports_function_calling=False, supports_vision=False,
            supports_system_messages=True,
            description="Grok Imagine (Quality) — xAI's text-to-image model with photorealism focus. High prompt adherence."
        ),
        "x-ai/grok-voice-latest": ModelInfo(
            model_name="x-ai/grok-voice-latest",
            provider=ModelProvider.XAI,
            input_cost_per_token=1.5e-05, output_cost_per_token=1.5e-05,
            max_input_tokens=131072, max_output_tokens=16384,
            supports_function_calling=True, supports_vision=False,
            supports_audio_input=True, supports_audio_output=True,
            supports_system_messages=True,
            description="Grok Voice Agent (Latest) — xAI's real-time bidirectional audio and voice assistant model."
        ),
        "x-ai/grok-voice-think-fast-1.0": ModelInfo(
            model_name="x-ai/grok-voice-think-fast-1.0",
            provider=ModelProvider.XAI,
            input_cost_per_token=2e-05, output_cost_per_token=2e-05,
            max_input_tokens=131072, max_output_tokens=16384,
            supports_function_calling=True, supports_vision=False,
            supports_audio_input=True, supports_audio_output=True,
            supports_system_messages=True,
            description="Grok Voice Agent (Think Fast 1.0) — flagship voice model with native real-time reasoning and deep analysis capabilities."
        ),
        "x-ai/grok-imagine-video-1.5": ModelInfo(
            model_name="x-ai/grok-imagine-video-1.5",
            provider=ModelProvider.XAI,
            input_cost_per_token=0.0005, output_cost_per_token=0.0,
            max_input_tokens=4096, max_output_tokens=1,
            supports_function_calling=False, supports_vision=True,
            supports_system_messages=True,
            description="Grok Imagine Video 1.5 — high-fidelity image-to-video and cinematic animation model. $0.50 per generation."
        ),
        "x-ai/grok-4.3": ModelInfo(
            model_name="x-ai/grok-4.3",
            provider=ModelProvider.XAI,
            input_cost_per_token=2e-06, output_cost_per_token=1e-05,
            max_input_tokens=131072, max_output_tokens=16384,
            supports_function_calling=True, supports_vision=True,
            supports_system_messages=True, supports_response_schema=True,
            description="Grok 4.3 — xAI's flagship text generation, reasoning, and structured output model."
        ),
        "x-ai/grok-4.20-multi-agent": ModelInfo(
            model_name="x-ai/grok-4.20-multi-agent",
            provider=ModelProvider.XAI,
            input_cost_per_token=5e-06, output_cost_per_token=2.5e-05,
            max_input_tokens=131072, max_output_tokens=16384,
            supports_function_calling=True, supports_vision=True,
            supports_system_messages=True, supports_response_schema=True,
            description="Grok 4.20 Multi-Agent — specialized real-time multi-agent orchestrator model for deep multi-step tasks."
        ),

        # ── ByteDance Seedream ──────────────────────────────────────
        "bytedance-seed/seedream-4.5": ModelInfo(
            model_name="bytedance-seed/seedream-4.5",
            provider=ModelProvider.BYTEDANCE,
            input_cost_per_token=4e-06, output_cost_per_token=0.0,
            max_input_tokens=4096, max_output_tokens=1,
            supports_function_calling=False, supports_vision=False,
            supports_system_messages=True,
            description="Seedream 4.5 — ByteDance's text-to-image model. Strong in Asian aesthetics, text rendering, and character consistency."
        ),

        # ── Microsoft MAI Image ──────────────────────────────────────
        "microsoft/mai-image-2.5": ModelInfo(
            model_name="microsoft/mai-image-2.5",
            provider=ModelProvider.MICROSOFT,
            input_cost_per_token=5e-06, output_cost_per_token=0.0,
            max_input_tokens=4096, max_output_tokens=1,
            supports_function_calling=False, supports_vision=False,
            supports_system_messages=True,
            description="Microsoft MAI Image 2.5 — enterprise-grade text-to-image. Strong in safety, branding, and consistency."
        ),
        "nvidia/llama-nemotron-rerank-vl-1b-v2:free": ModelInfo(
            model_name="nvidia/llama-nemotron-rerank-vl-1b-v2:free",
            provider=ModelProvider.NVIDIA,
            input_cost_per_token=0.0,
            output_cost_per_token=0.0,
            max_input_tokens=4096,
            max_output_tokens=1,
            supports_function_calling=False,
            supports_vision=True,
            supports_system_messages=False,
            description="NVIDIA Nemotron Rerank VL 1B — free-tier rerank model via OpenRouter."
        ),
        "z-ai/glm-5v-turbo": ModelInfo(
            model_name="z-ai/glm-5v-turbo",
            provider=ModelProvider.OPENROUTER,
            input_cost_per_token=2.6e-06,
            output_cost_per_token=2.6e-06,
            max_input_tokens=202752,
            max_output_tokens=16384,
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="Z.AI's GLM-5V-Turbo. Strong VLM coding model, excels in GUI agent tasks and pixel-level replication."
        ),
        "z-ai/glm-4.6v": ModelInfo(
            model_name="z-ai/glm-4.6v",
            provider=ModelProvider.OPENROUTER,
            input_cost_per_token=6e-07,
            output_cost_per_token=6e-07,
            max_input_tokens=131072,
            max_output_tokens=4096,
            supports_function_calling=True,
            supports_vision=True,
            supports_system_messages=True,
            supports_response_schema=True,
            description="Z.AI's GLM-4.6V - Native multimodal model with support for mixed inputs and visual tool use."
        ),
        "z-ai/glm-ocr": ModelInfo(
            model_name="z-ai/glm-ocr",
            provider=ModelProvider.OPENROUTER,
            input_cost_per_token=1e-07,
            output_cost_per_token=1e-07,
            max_input_tokens=131072,
            max_output_tokens=16384,
            supports_function_calling=False,
            supports_vision=True,
            supports_system_messages=True,
            description="Z.AI's GLM-OCR - Lightweight 0.9B layout parsing and high-accuracy text extraction model."
        ),
        "z-ai/glm-image": ModelInfo(
            model_name="z-ai/glm-image",
            provider=ModelProvider.OPENROUTER,
            input_cost_per_token=4e-06,
            output_cost_per_token=0.0,
            max_input_tokens=4096,
            max_output_tokens=1,
            supports_function_calling=False,
            supports_vision=False,
            supports_system_messages=True,
            description="Z.AI's GLM-Image - Autoregressive-diffusion model for high-fidelity text-to-image generation."
        ),
        "z-ai/cogview-4": ModelInfo(
            model_name="z-ai/cogview-4",
            provider=ModelProvider.OPENROUTER,
            input_cost_per_token=5e-06,
            output_cost_per_token=0.0,
            max_input_tokens=4096,
            max_output_tokens=1,
            supports_function_calling=False,
            supports_vision=False,
            supports_system_messages=True,
            description="Z.AI's CogView-4 - High-performance bilingual image generator with strong prompt adherence."
        ),
        "z-ai/cogvideox-3": ModelInfo(
            model_name="z-ai/cogvideox-3",
            provider=ModelProvider.OPENROUTER,
            input_cost_per_token=0.0002,
            output_cost_per_token=0.0,
            max_input_tokens=4096,
            max_output_tokens=1,
            supports_function_calling=False,
            supports_vision=False,
            supports_system_messages=True,
            description="Z.AI's CogVideoX-3 - Video generation model featuring new frame generation capabilities for high stability and clarity. $0.20 per video."
        ),
        "z-ai/vidu-q1": ModelInfo(
            model_name="z-ai/vidu-q1",
            provider=ModelProvider.OPENROUTER,
            input_cost_per_token=0.0004,
            output_cost_per_token=0.0,
            max_input_tokens=4096,
            max_output_tokens=1,
            supports_function_calling=False,
            supports_vision=False,
            supports_system_messages=True,
            description="Z.AI's Vidu Q1 - Next-generation high-quality video generation model, delivering photorealistic 1080P video clips. $0.40 per video."
        ),
        "z-ai/vidu-2": ModelInfo(
            model_name="z-ai/vidu-2",
            provider=ModelProvider.OPENROUTER,
            input_cost_per_token=0.0002,
            output_cost_per_token=0.0,
            max_input_tokens=4096,
            max_output_tokens=1,
            supports_function_calling=False,
            supports_vision=False,
            supports_system_messages=True,
            description="Z.AI's Vidu 2 - Next-generation fast and efficient video generation model, optimized for pan-entertainment and e-commerce. $0.20 per video."
        ),
        "z-ai/glm-asr-2512": ModelInfo(
            model_name="z-ai/glm-asr-2512",
            provider=ModelProvider.OPENROUTER,
            input_cost_per_token=1e-07,
            output_cost_per_token=1e-07,
            max_input_tokens=131072,
            max_output_tokens=16384,
            supports_function_calling=False,
            supports_vision=False,
            supports_audio_input=True,
            supports_system_messages=True,
            description="Z.AI's GLM-ASR-2512 - Next-generation speech recognition model enabling real-time audio transcription with extremely low character error rate (CER 0.0717)."
        ),
        "z-ai/glm-agent-slide": ModelInfo(
            model_name="z-ai/glm-agent-slide",
            provider=ModelProvider.OPENROUTER,
            input_cost_per_token=7e-07,
            output_cost_per_token=7e-07,
            max_input_tokens=131072,
            max_output_tokens=16384,
            supports_function_calling=False,
            supports_vision=False,
            supports_system_messages=True,
            description="Z.AI's GLM Slide/Poster Agent - Natural language visual generation, smart search synthesis, and layout design. $0.70 per million tokens."
        ),
        "z-ai/glm-agent-translation": ModelInfo(
            model_name="z-ai/glm-agent-translation",
            provider=ModelProvider.OPENROUTER,
            input_cost_per_token=3e-06,
            output_cost_per_token=3e-06,
            max_input_tokens=131072,
            max_output_tokens=16384,
            supports_function_calling=False,
            supports_vision=False,
            supports_system_messages=True,
            description="Z.AI's Translation Agent - Expert-level multilingual translation with terminology/glossary support and reflective optimization modes. $3.00 per million tokens."
        ),
        "z-ai/glm-agent-video-template": ModelInfo(
            model_name="z-ai/glm-agent-video-template",
            provider=ModelProvider.OPENROUTER,
            input_cost_per_token=0.0002,
            output_cost_per_token=0.0,
            max_input_tokens=4096,
            max_output_tokens=1,
            supports_function_calling=False,
            supports_vision=False,
            supports_system_messages=True,
            description="Z.AI's Video Effect Template Agent - Single-image professional video generation using pre-defined templates (French Kiss, Bodyshake, etc.). $0.20 per video."
        ),
    }


# Global model registry
MODEL_REGISTRY: Dict[str, ModelInfo] = _load_model_registry()


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
            if not has_all_caps:
                continue
        
        # Check if model supports required token counts
        if input_tokens > model.max_input_tokens or output_tokens > model.max_output_tokens:
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