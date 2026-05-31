# Weebot Model Registry Documentation

## Overview

The Weebot Model Registry provides a comprehensive database of AI model characteristics and pricing information. It leverages LiteLLM's extensive model database to offer information on 100+ LLM providers with their capabilities, costs, and performance characteristics.

## Key Features

### 1. Comprehensive Model Database
- **100+ LLM providers** supported (OpenAI, Anthropic, Google, Azure, AWS Bedrock, Ollama, etc.)
- **Detailed cost information** for each model (input/output costs per token)
- **Token limits** (max input/output tokens per request)
- **Capability flags** (function calling, vision, audio, etc.)
- **Provider identification** for intelligent routing

### 2. Intelligent Model Selection
- **Cost optimization** - Selects most economical model for each task
- **Capability matching** - Ensures model supports required features
- **Token limit validation** - Checks if model can handle required token counts
- **Provider diversity** - Offers alternatives across different providers

### 3. Performance Benefits
- **Reduced API costs** through intelligent provider selection
- **Faster response times** by selecting optimal models
- **Better reliability** with fallback options
- **Enhanced capabilities** with feature-rich model selection

## Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Weebot        │    │  Model          │    │  LiteLLM        │
│   Application   │───▶│  Registry       │───▶│  Data           │
│                 │    │                 │    │                 │
│  ┌─────────────┐│    │┌───────────────┐│    │┌───────────────┐│
│  │ModelRouter  ││───▶││ModelRegistry  ││───▶││model_prices_  ││
│  │             ││    ││               ││    ││and_context_   ││
│  │select_model()││    ││get_model_info()││    ││window.json    ││
│  │             ││    ││get_cheapest_  ││    ││               ││
│  │get_cost_info()││──▶││for_task()    ││───▶││(1000+ models) ││
│  └─────────────┘│    │└───────────────┘│    │└───────────────┘│
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

## Usage

### Basic Usage

```python
from weebot.model_registry import get_model_info, get_model_cost_info, list_all_models

# Get information about a specific model
model_info = get_model_info("gpt-4o-mini")
if model_info:
    print(f"Model: {model_info.model_name}")
    print(f"Provider: {model_info.provider.value}")
    print(f"Input cost per 1k tokens: ${model_info.input_cost_per_token * 1000:.4f}")
    print(f"Output cost per 1k tokens: ${model_info.output_cost_per_token * 1000:.4f}")
    print(f"Max input tokens: {model_info.max_input_tokens}")
    print(f"Supports function calling: {model_info.supports_function_calling}")

# Get cost information in LiteLLM format
cost_info = get_model_cost_info("claude-3-5-sonnet-20241022")
print(cost_info)  # {'input_cost_per_1k_tokens': 0.003, 'output_cost_per_1k_tokens': 0.015}

# List all available models
all_models = list_all_models()
print(f"Weebot supports {len(all_models)} different models")
```

### Advanced Usage

```python
from weebot.model_registry import get_cheapest_model_for_task, ModelProvider

# Find the cheapest model that can handle a specific task
cheapest_model = get_cheapest_model_for_task(
    input_tokens=1000,
    output_tokens=500,
    providers=[ModelProvider.OPENAI, ModelProvider.ANTHROPIC],  # Limit to specific providers
    required_capabilities=["function_calling", "system_messages"]  # Require specific features
)

if cheapest_model:
    print(f"Best model for task: {cheapest_model.model_name}")
    print(f"Estimated cost: ${cheapest_model.calculate_cost(1000, 500):.6f}")
```

## Model Information Structure

Each model in the registry includes:

- `model_name`: Identifier for the model (e.g., "gpt-4o-mini", "claude-3-5-sonnet-20241022")
- `provider`: Enum indicating the provider (OPENAI, ANTHROPIC, GOOGLE, etc.)
- `input_cost_per_token`: Cost per input token
- `output_cost_per_token`: Cost per output token
- `max_input_tokens`: Maximum tokens the model accepts in a single request
- `max_output_tokens`: Maximum tokens the model can generate in a single request
- `supports_function_calling`: Whether the model supports function calling
- `supports_vision`: Whether the model supports image inputs
- `supports_system_messages`: Whether the model supports system messages
- `supports_response_schema`: Whether the model supports structured outputs
- `supports_prompt_caching`: Whether the model supports prompt caching
- `description`: Human-readable description of the model

## Supported Providers

The model registry includes models from these providers:

- **OpenAI**: GPT-4, GPT-4o, GPT-4o Mini, GPT-3.5 Turbo
- **Anthropic**: Claude 3.5 Sonnet, Claude 3 Opus, Claude 3 Haiku, Claude 3 Sonnet
- **Google**: Gemini 1.5 Pro, Gemini 1.5 Flash, Gemini Pro
- **Microsoft Azure**: Azure OpenAI models
- **AWS Bedrock**: Claude, Llama, Titan, Command models
- **Mistral**: Mistral Large, Mistral Medium, Mistral Small
- **Groq**: Llama 3, Mixtral, Gemma models
- **Together AI**: Llama, Mistral, Qwen models
- **Ollama**: Local Llama, Phi, Gemma, Mistral models
- **Hugging Face**: Open source models
- **DeepSeek**: DeepSeek Chat, DeepSeek Coder
- **Moonshot**: Moonshot models
- **XAI**: Grok models
- **NVIDIA**: NIM models
- **Fireworks AI**: Fireworks models
- **Perplexity**: PPLX models
- **OpenRouter**: Community models
- **And many more providers**

## Integration with Weebot Components

### With AI Router
The model registry integrates seamlessly with the existing AI router:

```python
from weebot import ModelRouter
from weebot.model_registry import get_model_info

router = ModelRouter()
model_id = router.select_model(task_type=TaskType.CODE_GENERATION)

# Get detailed model information
model_info = get_model_info(model_id)
if model_info:
    print(f"Using {model_info.model_name} from {model_info.provider.value}")
    print(f"Estimated cost: ${model_info.calculate_cost(500, 200):.6f}")
```

### With Cost Tracking
The registry works with Weebot's existing cost tracking system:

```python
from weebot.model_registry import get_model_info

# When recording a call, use model-specific costs
def record_llm_call(model_id: str, input_tokens: int, output_tokens: int):
    model_info = get_model_info(model_id)
    if model_info:
        cost = model_info.calculate_cost(input_tokens, output_tokens)
        # Record cost in tracking system
        print(f"Call cost: ${cost:.6f}")
    else:
        # Fallback to default cost estimation
        print("Model not found in registry, using default cost")
```

## Performance Considerations

- **Initialization**: The model registry loads all model data at startup (typically <100ms)
- **Memory Usage**: Approximately 50-100MB for the full model database
- **Lookup Speed**: O(1) dictionary lookup for model information
- **Caching**: Model information is cached after first access

## Benefits

### 1. Cost Optimization
- **Real-time cost calculation** for any supported model
- **Budget enforcement** based on actual model costs
- **Cost comparison** across providers for same task
- **Spending visibility** with detailed cost tracking

### 2. Intelligent Routing
- **Provider diversity** - Access to models across 20+ providers
- **Feature matching** - Select models with required capabilities
- **Token limit awareness** - Ensure models can handle required context
- **Performance optimization** - Select fastest responding models

### 3. Reliability
- **Fallback capability** - Automatic switching to alternative models
- **Availability awareness** - Know which models are supported by providers
- **Consistent interface** - Same code works across all providers
- **Error handling** - Graceful degradation when models unavailable

## Troubleshooting

### Common Issues

1. **Model Not Found**: Verify the model name format (some require provider prefix like "openai/gpt-4o-mini")
2. **Cost Information Missing**: Check if the model is in LiteLLM's database
3. **Unsupported Capability**: Verify the model actually supports the required feature

### Debugging

Enable debug logging to troubleshoot model selection:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## Future Enhancements

- **Real-time pricing** - Live cost updates from providers
- **Performance metrics** - Latency and throughput data
- **Custom models** - Support for user-defined model specifications
- **Regional pricing** - Different costs based on deployment region
- **Fine-tuning costs** - Cost tracking for custom models