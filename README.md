# 🤖 Weebot — AI Agent Framework for Windows 11

[![Tests](https://img.shields.io/badge/tests-94%2B%20passing-success)](docs/PHASE2_IMPLEMENTATION_CHECKLIST.md)
[![Phase 2](https://img.shields.io/badge/Phase%202-Complete-blue)](docs/ROADMAP.md)
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

# Run with coverage
pytest tests/unit/ --cov=weebot --cov-report=html
```

**Test Coverage:** 94+ tests, all passing ✅

---

## 📚 Documentation

### Key Documents

| Document | Description |
|----------|-------------|
| [ROADMAP.md](docs/ROADMAP.md) | Development roadmap & phases |
| [PHASE2_IMPLEMENTATION_SUMMARY.md](docs/PHASE2_IMPLEMENTATION_SUMMARY.md) | Phase 2 deliverables |
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
| Phase 3 | 🟡 Ready | Workflow Templates |
| Phase 4 | 🟢 Planned | Observability & Monitoring |

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
