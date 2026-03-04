# 🤖 Weebot — AI Agent Framework for Windows 11

[![Tests](https://img.shields.io/badge/tests-160%2B%20passing-success)](docs/PHASE2_IMPLEMENTATION_CHECKLIST.md)
[![Version](https://img.shields.io/badge/version-2.3.0--harden-blue)](CHANGELOG.md)
[![Status](https://img.shields.io/badge/status-HARDENED%20Production%20Ready-green)](PROJECT_FINAL_SUMMARY.md)
[![Security](https://img.shields.io/badge/security-HARDEN%20Mode-orange)](SECURITY_HARDENING_GUIDE.md)
[![Python](https://img.shields.io/badge/python-3.12-blue)](.python-version)
[![License](https://img.shields.io/badge/license-MIT-green)]()

**Advanced AI Agent Framework** with multi-model routing, secure code execution, browser automation, and multi-agent orchestration.

---

## ✨ Features

### Core Capabilities
- 🔀 **Multi-Model AI Routing** — Kimi, DeepSeek, Claude, GPT with cost optimization
- 🛡️ **Secure Code Execution** — Sandboxed Bash/Python with multi-layer security
- 🌐 **Browser Automation** — Playwright-based advanced browser control
- 📊 **Multi-Agent Orchestration** — DAG-based workflow execution with parallel agents
- 💾 **Persistent State** — SQLite-based resume capability
- 🔔 **Notifications** — Telegram, Slack, Windows Toast
- 🔌 **MCP Server** — Claude Desktop integration

### Phase 3: Template Engine (NEW in v2.1.0 ✅)
- **YAML Templates** — Define workflows without Python code
- **8 Built-in Templates** — Research, Code Review, Documentation, Bug Analysis, etc.
- **Parameter System** — Type validation & coercion (string, int, bool, enum, list, dict)
- **Agent Integration** — Role-based agents with caching (researcher, analyst, developer, etc.)
- **Adaptive Suggestions** — Self-improving parameter recommendations 🧠 (v2.3.0)
- **160+ Tests** — Full test coverage

### Phase 6: Production Features (v2.2.0+ ✅)
- **Rate Limiting** — Token bucket with Redis/memory backends
- **Authentication** — API key based with RBAC
- **PostgreSQL** — Persistent execution history
- **Redis Caching** — High-performance template cache
- **Health Checks** — System monitoring endpoints

### 🔒 HARDEN Mode (v2.3.0-harden) — NEW
Production hardening with defense-in-depth security:
- **Privacy Audit Middleware** — GDPR-compliant collaborative filtering with enforced minimum user counts
- **Rate Limiter Bounds** — Memory exhaustion prevention with LRU eviction (max 10K buckets)
- **YAML Security Limits** — DoS protection with depth/node/size constraints
- **Circuit Breaker Jitter** — Thundering herd prevention with randomized recovery delays
- **DB Pool Monitor** — Connection exhaustion prevention with saturation alerts
- **Metrics & Alerting** — Prometheus-compatible metrics with 11 alert rules

See [Security Hardening Guide](SECURITY_HARDENING_GUIDE.md) for details.

### Phase 2: Multi-Agent Orchestration (COMPLETE ✅)
- **CircuitBreaker** — Fault tolerance with CLOSED/OPEN/HALF_OPEN states (22 tests)
- **DependencyGraph** — DAG validation, cycle detection, topological sort (17+ tests)
- **WorkflowOrchestrator** — Multi-agent workflow execution with parallel control (15+ tests)
- **ToolResult Enhancement** — Structured metadata and execution tracking (15 tests)
- **BashTool Security** — Multi-layer defense against command injection (25+ tests)

---

## 🚀 Quick Start

### Installation

```bash
# Clone repository
git clone https://github.com/yourusername/weebot.git
cd weebot

# Install dependencies
pip install -r requirements.txt

# Configure environment
copy .env.example .env
# Edit .env with your API keys
```

### Run Diagnostics

```bash
python run.py --diagnostic
```

### Interactive Mode

```bash
python run.py --interactive
```

### CLI Usage

```bash
# Create project
python -m cli.main create my_project "Data analysis task"

# Check status
python -m cli.main status my_project

# Run workflow
python -m cli.main run my_project workflow.json
```

### MCP Server (Claude Desktop)

```bash
# Run MCP server
python run_mcp.py

# Or with SSE transport
python run_mcp.py --transport sse --port 8765
```

### Template Engine (v2.1.0)

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

See [Template Engine Guide](PHASE3_FINAL_SUMMARY.md) for details.

### Adaptive Suggestions (v2.3.0) 🧠

Self-improving template system that learns optimal parameters:

```python
from weebot.templates.production import ProductionTemplateEngine

# Create engine with adaptive learning
engine = ProductionTemplateEngine(
    database_url="postgresql+asyncpg://...",
    enable_adaptive=True,
)

# Get intelligent suggestions
suggestions = await engine.get_suggestions(
    "Research Analysis Workflow",
    current_input={"topic": "AI"}
)

# Execute (automatically learns from outcome)
result = await engine.execute(
    "Research Analysis Workflow",
    parameters={"topic": "AI", "depth": "comprehensive"}
)
```

See [Adaptive Suggestions Guide](PHASE6B_ADAPTIVE_SUGGESTIONS.md) for details.

---

## 📊 Architecture

```
weebot/
├── core/                    # Multi-Agent Orchestration Engine
│   ├── circuit_breaker.py   # Fault tolerance (Phase 2 ✅)
│   ├── dependency_graph.py  # DAG validation (Phase 2 ✅)
│   ├── workflow_orchestrator.py  # Multi-agent execution (Phase 2 ✅)
│   ├── agent_context.py     # Shared agent context (Phase 7 ✅)
│   └── agent_factory.py     # Agent spawning (Phase 7 ✅)
├── templates/               # YAML Template Engine (Phase 3 ✅)
│   ├── parser.py            # YAML template parser
│   ├── parameters.py        # Parameter validation
│   ├── registry.py          # Template management
│   ├── engine.py            # Template execution
│   ├── integration.py       # System integration
│   ├── agent_integration.py # Agent system connection
│   └── builtin/             # 8 built-in templates
├── tools/                   # Tool implementations
│   ├── bash_tool.py         # Secure shell execution
│   ├── python_tool.py       # Sandboxed Python
│   ├── advanced_browser.py  # Browser automation
│   ├── scheduler.py         # Job scheduling
│   └── base.py              # ToolResult with metadata
├── mcp/                     # MCP Server integration
│   └── server.py            # FastMCP server
├── sandbox/                 # Code execution sandbox
├── domain/                  # Business logic (models, ports)
└── config/                  # Settings & configuration
```

---

## 🧪 Testing

```bash
# Run all tests
pytest tests/unit/ -v

# Run specific component tests
pytest tests/unit/test_circuit_breaker.py -v
pytest tests/unit/test_dependency_graph.py -v
pytest tests/unit/test_workflow_orchestrator.py -v
pytest tests/unit/test_templates/ -v          # Template Engine tests

# Run with coverage
pytest tests/unit/ --cov=weebot --cov-report=html
```

**Test Coverage:** 160+ tests, all passing ✅

---

## 📚 Documentation

### Key Documents

| Document | Description |
|----------|-------------|
| [ROADMAP.md](docs/ROADMAP.md) | Development roadmap & phases |
| [PHASE3_FINAL_SUMMARY.md](PHASE3_FINAL_SUMMARY.md) | Phase 3: Template Engine |
| [PHASE3_AGENT_INTEGRATION.md](PHASE3_AGENT_INTEGRATION.md) | Agent integration guide |
| [PHASE2_IMPLEMENTATION_SUMMARY.md](docs/PHASE2_IMPLEMENTATION_SUMMARY.md) | Phase 2 deliverables |
| [PHASE3_FINAL_SUMMARY.md](PHASE3_FINAL_SUMMARY.md) | Phase 3 Template Engine |
| [PHASE5_ADVANCED_FEATURES.md](PHASE5_ADVANCED_FEATURES.md) | Phase 5 Advanced Features |
| [PHASE6_PRODUCTION_HARDENING.md](PHASE6_PRODUCTION_HARDENING.md) | Phase 6 Production |
| [PHASE6B_ADAPTIVE_SUGGESTIONS.md](PHASE6B_ADAPTIVE_SUGGESTIONS.md) | EXPAND Mode - Adaptive Suggestions |
| [PROJECT_FINAL_SUMMARY.md](PROJECT_FINAL_SUMMARY.md) | Complete Project Summary |
| [SYSTEM_KNOWLEDGE_MAP.md](docs/SYSTEM_KNOWLEDGE_MAP.md) | Architecture & data flows |
| [BASH_SECURITY_FIX_SUMMARY.md](docs/BASH_SECURITY_FIX_SUMMARY.md) | Security implementation |
| [RESILIENCE_AND_DEPLOYMENT.md](docs/RESILIENCE_AND_DEPLOYMENT.md) | Production deployment |

### Quick Links

- [Setup Instructions](docs/SETUP_INSTRUCTIONS.md)
- [Capabilities Guide](WEEBOT_CAPABILITIES_GUIDE.md)
- [Production Deployment](docs/PRODUCTION_DEPLOYMENT_GUIDE.md)

---

## 🛡️ Security

### Multi-Layer Defense (BashTool)

- **Layer 1:** Pattern matching for known attack vectors
- **Layer 2:** Behavioral analysis (download+execute detection)
- **Layer 3:** Entropy analysis (encoded payload detection)
- **Layer 4:** Semantic validation (command structure)

### Security Features

- Sandboxed code execution with timeout & memory limits
- Command approval policy (deny/ask/auto)
- Path traversal protection
- No pickle serialization (JSON only)
- Audit logging

---

## 📈 Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 1 | ✅ Complete | Computer Use Tools |
| Phase 2 | ✅ Complete | Multi-Agent Orchestration Engine |
| Phase 3 | ✅ Complete | Template Engine with 8 built-in templates |
| Phase 5 | ✅ Complete | Advanced Features (Jinja2, Versioning, Marketplace) |
| Phase 6 | ✅ Complete | Production Hardening |
| Phase 6b | ✅ Complete | EXPAND Mode - Adaptive Suggestions |
| Phase 7 | 🟢 Planned | Web Dashboard |

See [ROADMAP.md](docs/ROADMAP.md) for details.

---

## 🤝 Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

### Development Setup

```bash
# Install dev dependencies
pip install -r requirements-dev.txt

# Run pre-commit hooks
pre-commit run --all-files

# Run tests before commit
pytest tests/unit/ -q
```

---

## 📄 License

MIT License — see [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- [LangChain](https://langchain.com/) — LLM framework
- [Playwright](https://playwright.dev/) — Browser automation
- [FastMCP](https://github.com/modelcontextprotocol/python-sdk) — MCP server
- [Pydantic](https://docs.pydantic.dev/) — Data validation

---

**Author:** Georgios-Chrysovalantis Chatzivantsidis  
**Version:** 2.0.0  
**Last Updated:** 2026-03-03

---

*Built with ❤️ for AI agents on Windows 11*
