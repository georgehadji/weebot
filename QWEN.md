# Weebot AI Agent Framework - Project Context

## Project Overview

Weebot is an advanced AI Agent Framework for Windows 11 that provides multi-model AI routing, secure code execution, browser automation, and multi-agent orchestration. The project is currently at version 2.3.0-harden with a focus on production-hardened security.

### Key Features

- **Multi-Model AI Routing**: Supports Kimi, DeepSeek, Claude, GPT with cost optimization
- **Secure Code Execution**: Sandboxed Bash/Python with multi-layer security
- **Browser Automation**: Playwright-based advanced browser control
- **Multi-Agent Orchestration**: DAG-based workflow execution with parallel agents
- **Persistent State**: SQLite-based resume capability
- **Notifications**: Telegram, Slack, Windows Toast
- **MCP Server**: Claude Desktop integration

### Phase 3: Template Engine (v2.1.0)
- YAML-based workflow templates allowing non-programmers to create workflows
- 8 built-in templates for research, code review, documentation, etc.
- Parameter validation system with type coercion
- Agent integration with role-based agents and caching

### Phase 6b: EXPAND Mode - Adaptive Suggestions (v2.3.0)
- Self-improving template system that learns optimal parameters
- Bayesian scoring with confidence-based suggestions
- Privacy-preserving collaborative learning

### HARDEN Mode Security (v2.3.0-harden)
- Privacy Audit Middleware with GDPR compliance
- Rate Limiter Bounds preventing memory exhaustion
- YAML Security Limits protecting against DoS attacks
- Circuit Breaker Jitter preventing thundering herd problems
- DB Pool Monitor preventing connection exhaustion

## Architecture

```
weebot/
├── core/                    # Multi-Agent Orchestration Engine
│   ├── circuit_breaker.py   # Fault tolerance (Phase 2)
│   ├── dependency_graph.py  # DAG validation (Phase 2)
│   ├── workflow_orchestrator.py  # Multi-agent execution (Phase 2)
│   ├── agent_context.py     # Shared agent context
│   └── agent_factory.py     # Agent spawning
├── templates/               # YAML Template Engine (Phase 3)
│   ├── parser.py            # YAML template parser
│   ├── parameters.py        # Parameter validation
│   ├── registry.py          # Template management
│   ├── engine.py            # Template execution
│   ├── integration.py       # System integration
│   ├── agent_integration.py # Agent system connection
│   ├── adaptive.py          # Adaptive suggestions (v2.3.0)
│   ├── production.py        # Production features (v2.3.0)
│   ├── privacy_audit.py     # Privacy middleware (v2.3.0-harden)
│   ├── db_monitor.py        # DB monitoring (v2.3.0-harden)
│   ├── metrics_exporter.py  # Prometheus metrics (v2.3.0-harden)
│   └── builtin/             # 8 built-in templates
├── tools/                   # Tool implementations
│   ├── bash_tool.py         # Secure shell execution
│   ├── python_tool.py       # Sandboxed Python
│   ├── advanced_browser.py  # Browser automation
│   └── base.py              # ToolResult with metadata
├── mcp/                     # MCP Server integration
├── sandbox/                 # Code execution sandbox
├── domain/                  # Business logic (models, ports)
├── config/                  # Settings & configuration
└── agents/                  # Agent implementations
```

## Building and Running

### Prerequisites
- Python 3.12
- Windows 11 (primary platform)

### Installation
```bash
# Clone repository
git clone <repository-url>
cd weebot

# Install dependencies
pip install -r requirements.txt

# Configure environment
copy .env.example .env
# Edit .env with your API keys
```

### Running the Application
```bash
# Run diagnostics
python run.py --diagnostic

# Interactive mode
python run.py --interactive

# CLI usage
python -m cli.main init
python -m cli.main doctor
python -m cli.main create my_project "Description"
python -m cli.main run my_project workflow.json
```

### MCP Server (Claude Desktop)
```bash
# Run MCP server
python run_mcp.py

# Or with SSE transport
python run_mcp.py --transport sse --port 8765
```

### Template Engine Usage
```python
from weebot.templates import TemplateEngine

# Create engine and load templates
engine = TemplateEngine()
engine.registry.load_builtin_templates()

# Execute a template
result = engine.execute(
    "Research Analysis Workflow",
    {
        "topic": "Artificial Intelligence",
        "depth": "comprehensive",
        "output_format": "markdown"
    }
)

print(f"Success: {result.success}")
print(f"Output: {result.output}")
```

## Testing

```bash
# Run all tests
pytest tests/unit/ -v

# Run specific component tests
pytest tests/unit/test_circuit_breaker.py -v
pytest tests/unit/test_dependency_graph.py -v
pytest tests/unit/test_workflow_orchestrator.py -v
pytest tests/unit/test_templates/ -v

# Run with coverage
pytest tests/unit/ --cov=weebot --cov-report=html
```

Current test count: 160+ tests, all passing

## Dependencies

Key dependencies include:
- langchain, langchain-openai for LLM framework
- playwright for browser automation
- pydantic for data validation
- aiohttp, requests for networking
- chromadb for vector storage
- click, rich for CLI
- pyyaml for YAML processing
- mcp for MCP server integration

## Development Conventions

- Follows semantic versioning
- Extensive test coverage (160+ tests)
- Type hints throughout the codebase
- Modular architecture with clear separation of concerns
- Security-first approach with multiple defense layers
- GDPR compliance for privacy features

## Project Status

The project is marked as "HARDENED Production Ready" with active development on advanced features and security hardening. Multiple phases have been completed including:
- Phase 1: Computer Use Tools
- Phase 2: Multi-Agent Orchestration Engine
- Phase 3: Template Engine with 8 built-in templates
- Phase 5: Advanced Features (Jinja2, Versioning, Marketplace)
- Phase 6: Production Hardening
- Phase 6b: EXPAND Mode - Adaptive Suggestions