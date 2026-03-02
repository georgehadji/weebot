# Multi-Agent Orchestration Framework

## Overview

Phase 1 introduces the **foundational building blocks** for multi-agent workflows in weebot. This enables creating specialized agent hierarchies with role-based tool access and inter-agent communication.

## Architecture

### Core Components

#### 1. **AgentContext** (`agent_context.py`)
Shared context passed between agents for data and event coordination.

**Features:**
- **Synchronous data sharing**: Dictionary-based key-value store (`shared_data`)
- **Asynchronous event signaling**: Pub/sub system via `EventBroker`
- **Nesting support**: 3-level maximum (orchestrator → children → grandchildren)
- **Activity logging**: Integrated with ActivityStream for audit trails

**Key Methods:**
```python
# Synchronous data access
await context.store_result("researcher.findings", data)
await context.get_result("researcher.findings")

# Asynchronous event signaling
await context.publish_event("analysis_complete", {"data": result})
async for event in context.subscribe_to_events("analysis_complete"):
    ...

# Checkpointing
await context.checkpoint("Awaiting approval before proceeding")
```

#### 2. **AgentFactory** (`agent_factory.py`)
Factory for creating specialized agent instances with role-based tool access.

**Features:**
- **Dynamic agent spawning**: Create agents with specific roles
- **Config inheritance**: Child agents inherit parent's basic settings
- **Tool isolation**: Role-based access control via RoleBasedToolRegistry
- **Nesting validation**: Prevents infinite spawning (max 3 levels)

**Example:**
```python
factory = AgentFactory()
orchestrator_ctx = AgentContext.create_orchestrator()

# Spawn single agent
researcher = await factory.spawn_agent(
    parent_agent_id="orchestrator_1",
    parent_context=orchestrator_ctx,
    role="researcher",
    description="Web research specialist"
)

# Spawn multiple agents
agents = await factory.spawn_orchestrator_agents(
    orchestrator_ctx,
    "orchestrator_1",
    [
        {"role": "researcher", "description": "Research specialist"},
        {"role": "analyst", "description": "Analysis specialist"},
        {"role": "automation", "description": "Automation specialist"}
    ]
)
```

#### 3. **RoleBasedToolRegistry** (`tool_registry.py`)
Manages role-to-tools mappings for access control.

**Predefined Roles:**
- `researcher`: web_search, advanced_browser, file_editor, knowledge_tool, video_ingest_tool, screen_tool
- `analyst`: python_tool, file_editor, knowledge_tool, bash_tool
- `automation`: bash_tool, computer_use, screen_tool, schedule_tool, file_editor, python_tool
- `documentation`: file_editor, knowledge_tool, web_search, product_tool
- `product_manager`: product_tool, file_editor, knowledge_tool, bash_tool
- `admin`: all tools

**Usage:**
```python
registry = RoleBasedToolRegistry()
tools = registry.get_tools_for_role("researcher")
assert registry.validate_tool_for_role("analyst", "python_tool") is True
assert registry.validate_tool_for_role("researcher", "python_tool") is False
```

## Design Patterns

### 1. Hybrid Settings Inheritance

Child agents **inherit basic settings** (timeout, budget, model fallback) from their parent, but can **override specialized settings** (tool access, model selection).

```python
# Parent config → Child inherits timeout/budget
# Child role → Determines tool access via RoleBasedToolRegistry
# Child config_overrides → Can select specific model
```

### 2. Hybrid Context Sharing

**Synchronous layer** (dictionary): Fast, direct access to shared data
**Asynchronous layer** (pub/sub): Event-driven coordination between agents

```python
# Synchronous: Research results immediately available
await orchestrator_ctx.store_result("research.findings", findings_dict)

# Asynchronous: Analyst reacts when research completes
await context.publish_event("research_complete")
async for event in analyst_context.subscribe_to_events("research_complete"):
    # Start analysis
    ...
```

### 3. 3-Level Nesting Hierarchy

```
Level 1: Orchestrator Agent
  ↓
Level 2: Specialist Agents (Research, Analysis, Automation)
  ↓
Level 3: Sub-agents (e.g., DocumentFetcher spawned by Researcher)
  ↓
Level 4+: BLOCKED (prevents resource exhaustion)
```

## Workflow Example

```python
import asyncio
from weebot.core.agent_context import AgentContext
from weebot.core.agent_factory import AgentFactory

async def research_analysis_workflow():
    # 1. Create orchestrator context
    root = AgentContext.create_orchestrator()

    # 2. Spawn specialized agents
    factory = AgentFactory()
    agents = await factory.spawn_orchestrator_agents(
        root, "orchestrator_1",
        [
            {"role": "researcher", "description": "Web researcher"},
            {"role": "analyst", "description": "Data analyst"}
        ]
    )

    # 3. Coordinate agents via shared context
    researcher = agents["researcher"]
    analyst = agents["analyst"]

    # Researcher finds data
    research_results = await researcher.run([
        {"name": "search_web", "prompt": "Find information about X"}
    ])
    await root.store_result("research.data", research_results)

    # Analyst accesses researcher's findings
    findings = await analyst._context.get_result("research.data")
    analysis = await analyst.run([
        {"name": "analyze_data", "prompt": f"Analyze: {findings}"}
    ])

    # Publish completion event
    await root.publish_event("analysis_complete", {"result": analysis})

    return analysis

# Run workflow
result = asyncio.run(research_analysis_workflow())
```

## Testing

20 tests verify all Phase 1 components:

### Agent Factory Tests (5)
- Agent spawning with roles
- Nesting level validation
- Tool access control
- Batch spawning
- Invalid role error handling

### Agent Context Tests (8)
- Orchestrator creation
- Child context creation
- Shared data storage/retrieval
- Event publishing and subscription
- Event filtering by agent
- Nesting validation

### Tool Registry Tests (7)
- Role-to-tools mapping
- Tool validation
- Role addition/removal
- Tool access validation
- Admin role access

**All tests passing:** 20/20 ✅

## Integration with Existing Components

### StateManager
AgentContext uses the existing StateManager for persistence:
- Shared state across agents
- Resume capability on failure
- Checkpoint support

### ActivityStream
All agent events logged to shared ActivityStream:
- 200-event ring buffer
- Per-orchestrator filtering
- Audit trail for debugging

### WeebotAgent
Added `spawn_child_agent()` method for programmatic spawning:
```python
agent = orchestrator.spawn_child_agent(
    role="analyst",
    context=orchestrator_context,
    description="Analysis specialist"
)
```

## Next Steps

### Phase 2: Workflow Orchestration
- **WorkflowOrchestrator**: Parallel/sequential execution, DAG support
- **CircuitBreaker**: Error recovery with exponential backoff
- **ToolResult enhancement**: Structured output (JSON/JSONL)

### Phase 3: Real-World Examples
- Research → Analysis → Report workflow
- Competitive analysis → Requirements → PRD pipeline
- Parallel data processing workflows

### Phase 4: Observability
- Structured logging (JSON events)
- Workflow tracing (Mermaid DAG export)
- Performance metrics per agent

## Files

| File | Purpose | LOC |
|------|---------|-----|
| `weebot/core/agent_context.py` | AgentContext + EventBroker | 280 |
| `weebot/core/agent_factory.py` | AgentFactory | 180 |
| `weebot/tools/tool_registry.py` | RoleBasedToolRegistry | 130 |
| `tests/unit/test_agent_context.py` | AgentContext tests | 190 |
| `tests/unit/test_agent_factory.py` | AgentFactory tests | 160 |
| `tests/unit/test_tool_registry.py` | RoleBasedToolRegistry tests | 110 |

**Total new code:** 630+ LOC, **20 passing tests**

## Dependencies

- `asyncio`: Async context and event handling
- `weebot.activity_stream.ActivityStream`: Event logging
- `weebot.state_manager.StateManager`: Persistence
- `weebot.agent_core_v2.WeebotAgent`: Base agent class
