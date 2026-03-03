# Phase 3 - Agent System Integration

Οδηγός σύνδεσης Template Engine με το Weebot Agent System

---

## 🎯 Επισκόπηση

Το Template Engine μπορεί πλέον να χρησιμοποιεί πραγματικά agents από το Weebot agent system για:
- **Εκτέλεση εργασιών** με εξειδικευμένους agents
- **Διαχείριση ρόλων** (researcher, analyst, developer, κλπ)
- **Caching agents** για επαναχρησιμοποίηση
- **Parallel execution** με πολλαπλά agents

---

## 📁 Αρχεία

```
weebot/templates/
├── agent_integration.py          # Κύριο integration module
├── integration.py                 # Υπάρχον integration (ενημερωμένο)
└── ...

tests/unit/test_templates/
├── test_agent_integration.py     # Tests
└── ...

examples/
├── agent_integration_example.py  # Παραδείγματα
└── ...
```

---

## 🚀 Quick Start

### 1. Βασική Χρήση με Agents

```python
from weebot.templates.agent_integration import create_agent_enabled_engine

# Δημιούργησε engine με agent support
engine, agent_manager = create_agent_enabled_engine(
    load_builtin=True  # Φόρτωσε όλα τα templates
)

# Εκτέλεσε template
result = engine.execute(
    "Research Analysis Workflow",
    {
        "topic": "Python asyncio",
        "depth": "comprehensive"
    }
)

# Τα tasks εκτελούνται από πραγματικά agents!
print(f"Success: {result.success}")
print(f"Results: {result.task_results}")
```

### 2. Προσαρμοσμένοι Agents

```python
from weebot.templates.agent_integration import TemplateAgentManager

# Δημιούργησε manager
manager = TemplateAgentManager()

# Πάρε ή δημιούργησε agent για συγκεκριμένο ρόλο
agent = manager.get_or_create_agent(
    role="researcher",
    task_description="Research Python patterns"
)

# Εκτέλεση task
import asyncio
result = asyncio.run(
    manager.execute_task("researcher", "Research async/await")
)
```

### 3. Χρήση με Υπάρχον Engine

```python
from weebot.templates import TemplateEngine
from weebot.templates.agent_integration import register_agent_handlers

# Υπάρχον engine
engine = TemplateEngine()
engine.registry.load_builtin_templates()

# Πρόσθεσε agent support
register_agent_handlers(engine)

# Τώρα υποστηρίζει agents!
result = engine.execute("Code Review Workflow", {...})
```

---

## 🎭 Διαθέσιμοι Ρόλοι Agents

| Ρόλος | Περιγραφή | Εργαλεία |
|-------|-----------|----------|
| **researcher** | Έρευνα & συλλογή πληροφοριών | web_search, browser, file_reader |
| **analyst** | Ανάλυση δεδομένων | calculator, data_processor |
| **writer** | Τεχνική συγγραφή | file_writer, markdown_formatter |
| **reviewer** | Έλεγχος ποιότητας | file_reader, comparator |
| **developer** | Ανάπτυξη λογισμικού | file_writer, bash, code_editor |
| **tester** | QA & testing | test_runner, bash |
| **default** | Γενικός σκοπός | web_search, file_reader, file_writer |

---

## 🔧 Προηγμένη Χρήση

### Custom Role Definition

```python
from weebot.templates.agent_integration import TemplateAgentManager

# Πρόσθεσε custom ρόλο
manager = TemplateAgentManager()
manager.ROLE_PROFILES["security_expert"] = {
    "description": "Security specialist for vulnerability analysis",
    "tools": ["security_scanner", "code_analyzer", "vuln_db"],
}

# Χρήση του custom ρόλου
agent = manager.get_or_create_agent("security_expert")
```

### Agent Caching

```python
# Ο manager cache-άρει agents ανά ρόλο
agent1 = manager.get_or_create_agent("researcher")  # Δημιουργεί
agent2 = manager.get_or_create_agent("researcher")  # Επιστρέφει cached

assert agent1 is agent2  # True!

# Καθαρισμός cache
manager.clear_cache()
```

### Async Execution

```python
import asyncio

async def run_multiple_tasks():
    tasks = [
        manager.execute_task("researcher", "Task 1"),
        manager.execute_task("analyst", "Task 2"),
        manager.execute_task("writer", "Task 3"),
    ]
    
    results = await asyncio.gather(*tasks)
    return results

results = asyncio.run(run_multiple_tasks())
```

---

## 🔄 Integration Modes

### 1. Full Mode (Πραγματικά Agents)

```python
# Όταν το agent system είναι διαθέσιμο
from weebot.agent_core_v2 import WeebotAgent
from weebot.core.agent_factory import AgentFactory

# Δημιούργησε manager
manager = TemplateAgentManager()
# → Χρησιμοποιεί πραγματικά WeebotAgents
```

### 2. Simulation Mode

```python
# Όταν το agent system δεν είναι διαθέσιμο
# (π.χ. για testing, development)

handler = TemplateAgentTaskHandler()
# → Επιστρέφει simulated results
# → Χρήσιμο για development χωρίς API keys
```

---

## 📋 Templates που Χρησιμοποιούν Agents

### Code Review Workflow

```yaml
workflow:
  initial_scan:
    agent_role: "code_analyzer"
    task: "Perform static analysis"
  
  security_review:
    agent_role: "security_reviewer"
    task: "Check for vulnerabilities"
```

### Research Analysis Workflow

```yaml
workflow:
  initial_research:
    agent_role: "researcher"
    task: "Gather information on {{topic}}"
  
  deep_analysis:
    agent_role: "analyst"
    task: "Analyze findings"
```

### Documentation Generation

```yaml
workflow:
  write_main_content:
    agent_role: "technical_writer"
    task: "Create documentation"
```

---

## 🧪 Testing

### Run Tests

```bash
# Agent integration tests
pytest tests/unit/test_templates/test_agent_integration.py -v

# Όλα τα template tests
pytest tests/unit/test_templates/ -v
```

### Manual Testing

```python
# Check if agent system available
from weebot.templates.agent_integration import HAS_AGENT_SYSTEM

print(f"Agent system: {'Available' if HAS_AGENT_SYSTEM else 'Simulation mode'}")

# Get agent info
from weebot.templates.agent_integration import TemplateAgentManager

manager = TemplateAgentManager()
info = manager.get_agent_info()
print(f"Roles: {info['available_roles']}")
```

---

## 🔌 Σύνδεση με Υπάρχοντα Components

### Με WorkflowOrchestrator

```python
from weebot.templates.integration import create_integrated_engine

integration = create_integrated_engine(
    load_builtin=True,
    use_orchestrator=True  # Ενεργοποίηση parallel execution
)

# Χρησιμοποιεί agents + orchestrator
result = integration.execute_workflow_template(
    "Research Analysis Workflow",
    {"topic": "AI"}
)
```

### Με Custom Agent Factory

```python
from weebot.core.agent_factory import AgentFactory
from weebot.templates.agent_integration import TemplateAgentManager

# Δικό σου factory
my_factory = AgentFactory()

# Δημιούργησε manager με custom factory
manager = TemplateAgentManager(agent_factory=my_factory)

# Δημιούργησε engine
from weebot.templates.agent_integration import create_agent_enabled_engine
engine, _ = create_agent_enabled_engine(agent_manager=manager)
```

---

## 📊 Παρακολούθηση & Logging

```python
import logging

# Ενεργοποίηση logging
logging.basicConfig(level=logging.INFO)

# Θα δεις:
# INFO: Created agent for role: researcher
# INFO: Executing agent task: researcher - Research Python...
# INFO: Agent task completed successfully
```

---

## 🛠️ Troubleshooting

### Πρόβλημα: "Agent system not available"

**Λύση:** Τρέχει σε simulation mode. Για πραγματικά agents:
```bash
# Εγκατάσταση εξαρτήσεων
pip install -r requirements.txt

# Έλεγξε ότι υπάρχει:
# - weebot/agent_core_v2.py
# - weebot/core/agent_factory.py
```

### Πρόβλημα: "Agent creation failed"

**Λύση:** Έλεγξε AgentConfig:
```python
from weebot.agent_core_v2 import AgentConfig

config = AgentConfig(
    name="my_agent",
    description="Test agent",
    system_prompt="You are a helpful assistant"
)
```

### Πρόβλημα: Tasks εκτελούνται sequentially

**Λύση:** Χρησιμοποίησε orchestrator για parallel execution:
```python
from weebot.templates.integration import TemplateOrchestratorIntegration

integration = TemplateOrchestratorIntegration(
    engine=engine,
    orchestrator=WorkflowOrchestrator()
)
```

---

## 🎯 Next Steps

1. **Προσθήκη Custom Roles**
   ```python
   manager.ROLE_PROFILES["my_role"] = {...}
   ```

2. **Custom Tool Integration**
   ```python
   from weebot.tools.tool_registry import ToolRegistry
   ToolRegistry.register("my_tool", MyTool())
   ```

3. **Agent Performance Monitoring**
   ```python
   # Πρόσθεσε metrics στο manager
   manager.execution_times = []
   ```

---

## ✅ Checklist

- [x] TemplateAgentManager δημιουργεί agents
- [x] Agent caching λειτουργεί
- [x] Role-based agent selection
- [x] Async execution υποστηρίζεται
- [x] Simulation mode για development
- [x] Integration με υπάρχον engine
- [x] 8 built-in templates με agent tasks
- [x] Tests για agent integration
- [x] Documentation & examples

---

**Το Template Engine είναι πλέον πλήρως ενσωματωμένο με το Agent System!** 🎉🚀
