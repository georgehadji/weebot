# LiteLLM Integration for Weebot

## Overview

The LiteLLM integration enhances the Weebot framework with advanced AI provider management capabilities. It leverages LiteLLM's extensive multi-provider support, intelligent routing, and cost optimization features to provide superior AI model selection and management.

## Key Features

### 1. Multi-Provider Support
- **100+ LLM providers** supported (OpenAI, Anthropic, Google, Azure, AWS Bedrock, Ollama, etc.)
- **Unified API interface** - same code works across all providers
- **Easy switching** between providers without code changes
- **Cost optimization** by selecting the most economical provider for each task

### 2. Intelligent Routing
- **Load balancing** across multiple deployments
- **Automatic fallback** to alternative providers/models when one fails
- **Latency-based routing** to select fastest responding provider
- **Circuit breaker pattern** to isolate failing providers
- **Retry logic** with exponential backoff

### 3. Enhanced Cost Management
- **Real-time cost tracking** for each request
- **Budget enforcement** with spending limits
- **Cost comparison** across different providers
- **Detailed usage analytics**

### 4. Advanced Reliability Features
- **Circuit breakers** to prevent cascade failures
- **Health checks** for provider availability
- **Automatic retries** with configurable policies
- **Timeout management** for requests

### 5. Proxy & Gateway Features
- **AI Gateway functionality** with authentication and authorization
- **Virtual API keys** for secure access control
- **Rate limiting** per user/key/project
- **Request/response logging** and monitoring
- **Caching** for faster repeated queries

## Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Weebot        │    │  LiteLLM        │    │  LLM Providers  │
│   Application   │───▶│  Integration    │───▶│  (100+ models)  │
│                 │    │                 │    │                 │
│  ┌─────────────┐│    │┌───────────────┐│    │┌───────────────┐│
│  │AI Router    ││───▶││LiteLLMRouter  ││───▶││Model Selection││
│  │             ││    ││               ││    ││               ││
│  │ModelRouter  ││    ││Intelligent    ││    ││Cost-Optimized ││
│  │             ││    ││Routing        ││    ││Selection      ││
│  └─────────────┘│    │└───────────────┘│    │└───────────────┘│
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

## Usage

### Basic Usage

```python
from weebot import ModelRouter, TaskType

# Initialize the router
router = ModelRouter(daily_budget=10.0)

# Generate response with intelligent routing
result = await router.generate_with_fallback(
    prompt="Write a Python function to calculate fibonacci numbers",
    task_type=TaskType.CODE_GENERATION
)

print(result["content"])
print(result["model"])  # Shows which model was used
```

### Advanced Usage with LiteLLM Features

```python
from weebot import get_litellm_router, TaskType

# Get direct access to LiteLLM router
litellm_router = get_litellm_router()

# Select model based on task type and budget
model_name = litellm_router.select_model(
    task_type=TaskType.CODE_GENERATION,
    budget_constraint=0.005  # Max $0.005 per 1k tokens
)

# Get provider for the selected model
provider = litellm_router.get_provider(model_name)

# Generate response with full LiteLLM capabilities
result = await provider.agenerate_response(
    messages=[
        {"role": "system", "content": "You are a helpful coding assistant."},
        {"role": "user", "content": "Write a Python function..."}
    ],
    task_type=TaskType.CODE_GENERATION,
    temperature=0.2,
    max_tokens=1000
)
```

### Configuration

The LiteLLM integration can be configured using environment variables:

```bash
# Required API Keys
export OPENAI_API_KEY="your-openai-api-key"
export ANTHROPIC_API_KEY="your-anthropic-api-key"
export GOOGLE_API_KEY="your-google-api-key"
export AZURE_API_KEY="your-azure-api-key"

# Optional Configuration
export DAILY_AI_BUDGET="10.0"  # Daily budget in USD
export LITELLM_ROUTING_STRATEGY="cost-performance"  # Options: cost-performance, latency, load-balance
```

## Benefits

### 1. Cost Optimization
- Automatic selection of most economical provider for each task
- Detailed cost tracking and budget enforcement
- Caching to reduce redundant API calls

### 2. Reliability
- Automatic fallback to alternative providers
- Circuit breakers to prevent cascade failures
- Health checks for provider availability

### 3. Scalability
- Load balancing across multiple deployments
- Support for 100+ LLM providers
- Intelligent routing based on performance metrics

### 4. Flexibility
- Easy switching between providers
- Unified interface across all providers
- Extensible architecture for new providers

## Integration Points

The LiteLLM integration is seamlessly integrated with existing Weebot components:

1. **AI Router**: Enhanced with LiteLLM's intelligent routing
2. **Cost Tracking**: Integrated with existing cost tracking system
3. **Caching**: Compatible with existing caching mechanisms
4. **Error Handling**: Enhanced with LiteLLM's reliability features

## Performance Considerations

- **Latency**: LiteLLM adds minimal overhead (typically <10ms)
- **Caching**: Enabled by default to reduce API calls
- **Concurrency**: Fully async-compatible for high-throughput scenarios

## Troubleshooting

### Common Issues

1. **API Key Not Found**: Ensure environment variables are set correctly
2. **Rate Limiting**: Check provider-specific rate limits
3. **Model Not Available**: Verify model name format and provider availability

### Debugging

Enable verbose logging to troubleshoot issues:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## Future Enhancements

- **Multi-modal support** for vision and audio models
- **Fine-tuning integration** for custom models
- **Advanced analytics** with usage patterns and cost optimization
- **Enterprise features** with team management and advanced security