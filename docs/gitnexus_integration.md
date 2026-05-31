# GitNexus Integration for Weebot

## Overview

The GitNexus integration enhances the Weebot framework with advanced codebase intelligence capabilities. It leverages GitNexus's knowledge graph technology to provide deep understanding of code structure, dependencies, execution flows, and architectural relationships to AI agents.

## Key Features

### 1. Knowledge Graph Analysis
- **Complete codebase indexing** - Every dependency, call chain, cluster, and execution flow
- **Multi-language support** - TypeScript, JavaScript, Python, Java, C/C++, C#, Go, Rust, PHP, Swift
- **Intelligent clustering** - Auto-detection of functional areas using Leiden algorithm
- **Process tracing** - Execution flow tracing from entry points through call chains

### 2. Smart Tool Integration
- **7 MCP tools** exposed to AI agents:
  - `list_repos` - Discover all indexed repositories
  - `query` - Process-grouped hybrid search (BM25 + semantic + RRF)
  - `context` - 360-degree symbol view with categorized refs
  - `impact` - Blast radius analysis with depth grouping
  - `detect_changes` - Git-diff impact mapping
  - `rename` - Multi-file coordinated rename
  - `cypher` - Raw Cypher graph queries

### 3. Intelligent Routing
- **Task-based model selection** - Automatic selection of optimal analysis mode
- **Cost optimization** - Selects most economical provider for each task
- **Performance optimization** - Routes to fastest responding provider
- **Reliability** - Automatic fallback to alternative providers/models

### 4. Context Enhancement
- **Automatic context injection** - Enhances prompts with relevant code context
- **Symbol-level context** - Detailed information about specific functions/classes
- **Impact analysis** - Understand consequences of code changes
- **Change detection** - Identify and analyze repository changes

## Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Weebot        │    │  GitNexus        │    │  Codebase       │
│   Application   │───▶│  Integration     │───▶│  Knowledge      │
│                 │    │                 │    │  Graph          │
│  ┌─────────────┐│    │┌───────────────┐│    │┌───────────────┐│
│  │AI Router    ││───▶││GitNexusRouter ││───▶││KnowledgeGraph ││
│  │             ││    ││               ││    ││               ││
│  │ModelRouter  ││    ││Intelligent    ││    ││Indexed code   ││
│  │             ││    ││Analysis       ││    ││structure,     ││
│  └─────────────┘│    │└───────────────┘│    ││dependencies,  ││
└─────────────────┘    └──────────────────┘    ││processes      ││
                                               └───────────────┘┘
```

## Usage

### Basic Usage

```python
from weebot import get_gitnexus_provider, get_gitnexus_router

# Get the GitNexus provider
provider = get_gitnexus_provider()

# Check if GitNexus is available
if await provider.is_available():
    # Analyze the current repository
    success = await provider.analyze_repository()
    
    # Query the codebase
    results = await provider.query_codebase("authentication flow")
    print(results)
```

### Intelligent Analysis with Router

```python
from weebot import get_gitnexus_router, TaskType

# Get the GitNexus router
router = get_gitnexus_router()

# Perform intelligent analysis based on task type
results = await router.analyze_codebase(
    query="Find all authentication-related code",
    task_type=TaskType.ARCHITECTURE,
    complexity="high"
)

print(results)
```

### Context Enhancement

```python
from weebot import enhance_prompt_with_code_context

# Enhance a prompt with code context
enhanced_prompt = await enhance_prompt_with_code_context(
    prompt="Review this authentication implementation",
    task_context="security review",
    target_symbol="AuthService"
)

print(enhanced_prompt)
```

### Impact Analysis

```python
from weebot import analyze_code_impact

# Analyze the impact of changing a specific function
impact_results = await analyze_code_impact(
    target="UserService.validate",
    direction="upstream"  # Who depends on this?
)

print(impact_results)
```

## Configuration

The GitNexus integration can be configured using environment variables:

```bash
# GitNexus executable settings
export GITNEXUS_PATH="npx"  # Path to GitNexus executable
export GITNEXUS_ARGS="--y gitnexus@latest"  # Additional arguments

# Analysis settings
export GITNEXUS_SKIP_EMBEDDINGS="false"  # Skip embedding generation (faster)
export GITNEXUS_FORCE_REINDEX="false"    # Force full re-index
export GITNEXUS_MAX_DEPTH="3"            # Maximum impact analysis depth
export GITNEXUS_MIN_CONFIDENCE="0.7"     # Minimum confidence threshold

# Performance settings
export GITNEXUS_TIMEOUT="300"            # Request timeout in seconds
export GITNEXUS_MAX_RETRIES="3"          # Maximum retry attempts

# Caching settings
export GITNEXUS_ENABLE_CACHING="true"    # Enable response caching
export GITNEXUS_CACHE_TTL="3600"         # Cache TTL in seconds

# Repository settings
export GITNEXUS_DEFAULT_REPO_PATH="."    # Default repository path
export GITNEXUS_AUTO_ANALYZE="true"      # Auto-analyze on startup
```

## Analysis Modes

GitNexus supports different analysis modes optimized for different task types:

- **QUICK**: Fast analysis for chat and creative tasks
- **DEEP**: Thorough analysis for architecture and analysis tasks
- **IMPACT**: Impact-focused analysis for debugging tasks
- **STRUCTURAL**: Structure-focused analysis for code review tasks
- **SEARCH**: Search-focused analysis for code generation tasks

The router automatically selects the appropriate mode based on the task type and complexity.

## Integration Points

### With AI Router
The GitNexus integration works seamlessly with the existing AI router:

```python
from weebot import ModelRouter, TaskType, get_gitnexus_router

# Use GitNexus-enhanced analysis in your AI workflows
async def intelligent_code_analysis(prompt: str, task_type: TaskType):
    router = get_gitnexus_router()
    
    # Get intelligent analysis based on task type
    analysis = await router.analyze_codebase(
        query=prompt,
        task_type=task_type
    )
    
    # Use the analysis results in your AI workflow
    return analysis
```

### With State Management
GitNexus results can be integrated with the state management system:

```python
from weebot import StateManager

# Store GitNexus analysis results in state
async def store_analysis_results(state_manager: StateManager, results: dict):
    await state_manager.update_state({
        "gitnexus_analysis": results,
        "analysis_timestamp": time.time()
    })
```

## Benefits

### 1. Enhanced Code Understanding
- **Deep structural insight** - Understand code relationships beyond surface level
- **Execution flow tracing** - See how functions interact across the codebase
- **Dependency mapping** - Identify all dependencies and their impact

### 2. Improved AI Accuracy
- **Reduced hallucinations** - AI agents have access to actual code structure
- **Better context** - More relevant information for decision making
- **Accurate suggestions** - Recommendations based on real code patterns

### 3. Cost Optimization
- **Reduced token usage** - Compressed, relevant context instead of full files
- **Efficient queries** - Targeted analysis reduces unnecessary processing
- **Caching benefits** - Repeated queries served from cache

### 4. Reliability
- **Consistent results** - Same analysis methodology across all queries
- **Error handling** - Graceful fallback when GitNexus is unavailable
- **Performance** - Optimized for fast response times

## Troubleshooting

### Common Issues

1. **GitNexus Not Available**: Ensure GitNexus is installed and accessible:
   ```bash
   npx gitnexus --version
   ```

2. **Repository Not Indexed**: Run analysis to index the repository:
   ```bash
   npx gitnexus analyze
   ```

3. **Slow Performance**: Consider using `--skip-embeddings` flag for faster indexing:
   ```bash
   npx gitnexus analyze --skip-embeddings
   ```

### Debugging

Enable debug logging to troubleshoot issues:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## Performance Considerations

- **Indexing Time**: Initial analysis may take several minutes for large repositories
- **Memory Usage**: Knowledge graph requires memory proportional to codebase size
- **Query Performance**: Cached queries respond in milliseconds
- **Network**: All analysis happens locally, no network required after installation

## Security & Privacy

- **Local Processing**: All code analysis happens on your local machine
- **No Data Upload**: Code never leaves your system
- **API Key Security**: GitNexus only uses local indexing, no external API keys required
- **Access Control**: Respects your repository's access permissions

## Future Enhancements

- **Multi-repository support** - Analyze relationships across multiple repositories
- **Real-time indexing** - Incremental updates as code changes
- **Advanced visualizations** - Interactive code structure visualizations
- **Custom analysis plugins** - Extend with domain-specific analysis rules