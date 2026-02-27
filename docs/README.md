# Manus-Win11 Agent Framework

Προηγμένο AI Agent Framework για Windows 11 με intelligent model routing, persistent state management, και human-in-the-loop capabilities.

## 🚀 Χαρακτηριστικά

- **Intelligent AI Routing**: Αυτόματη επιλογή βέλτιστου μοντέλου (Kimi, DeepSeek, Claude, GPT)
- **Cost Optimization**: Caching, budget tracking, και smart model selection
- **Persistent State**: SQLite-based storage με pause/resume capability
- **Multi-Channel Notifications**: Telegram & Slack integration
- **Human-in-the-Loop**: Checkpoints για user approval σε κρίσιμα σημεία
- **CLI Interface**: Πλήρες command line interface για διαχείριση

## 🔬 Επιστημονική Έρευνα

- **Reproducibility Engine**: Environment capture, provenance tracking
- **Data Validation**: Statistical validation, unit consistency
- **Literature Management**: Citation extraction, bibliography generation
- **Obsidian Integration**: Knowledge base sync, research dashboard
- **Zotero Sync**: Two-way reference management

## 📁 Project Structure

```
manus-win11/
├── config_settings.py          # Configuration & constants
├── utils_logger.py             # Logging utilities
├── tools_powershell.py         # PowerShell Windows Sandbox
├── tools_browser.py            # Browser automation
├── tools_heuristic_router.py   # Tool selection logic
├── core_safety.py              # Safety & counterfactual simulation
├── core_agent.py               # Recursive OEAR agent
├── agent_core_v2.py            # Enhanced agent v2
├── main_agent.py               # Main entry point
├── ai_router.py                # AI model selection
├── notifications.py            # Telegram/Slack notifications
├── state_manager.py            # SQLite persistence
├── research_reproducibility.py # Reproducibility framework
├── research_data_validator.py  # Scientific data validation
├── research_literature.py      # Citation management
├── integrations_obsidian.py    # Obsidian vault integration
├── integrations_zotero.py      # Zotero sync
├── cli_main.py                 # CLI interface
└── requirements.txt            # Dependencies
```

## 📋 Απαιτήσεις

- Python 3.8+
- Windows 11 (ή Linux/macOS με compatible paths)
- API Keys για τουλάχιστον ένα AI provider

## ⚙️ Εγκατάσταση

### 1. Clone & Setup

```bash
cd manus-win11
python -m venv venv
venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

### 2. Configuration

Δημιούργησε `.env` file:

```env
# AI API Keys
KIMI_API_KEY=your_kimi_key_here
DEEPSEEK_API_KEY=your_deepseek_key_here
ANTHROPIC_API_KEY=your_claude_key_here
OPENAI_API_KEY=your_openai_key_here

# Notifications
TELEGRAM_BOT_TOKEN=your_telegram_token
TELEGRAM_CHAT_ID=your_chat_id
SLACK_WEBHOOK_URL=your_slack_webhook

# Budget & Settings
DAILY_AI_BUDGET=10.0
```

## 🎯 Γρήγορο Ξεκίνημα

### Επιλογή 1: CLI (Προτείνεται)

```bash
# Δημιούργησε project
python cli_main.py create my_project "Analyze sales data" --budget 5.0

# Δες status
python cli_main.py status my_project

# Τρέξε plan
python cli_main.py run my_project my_plan.json
```

### Επιλογή 2: Python API

```python
import asyncio
from agent_core_v2 import ManusAgent, AgentConfig
from ai_router import TaskType

async def main():
    config = AgentConfig(
        project_id="data_analysis_001",
        description="Customer churn analysis",
        daily_budget=10.0
    )
    
    agent = ManusAgent(config)
    
    plan = [
        {
            "name": "analyze_data",
            "type": TaskType.ANALYSIS,
            "description": "Understand data structure",
            "prompt": "Analyze this dataset for patterns..."
        }
    ]
    
    await agent.run(plan)
    print(agent.get_status())

asyncio.run(main())
```

## 🧪 Επιστημονική Έρευνα

### Δημιουργία Experiment

```bash
python cli_main.py research init-experiment "Quantum Analysis" --field physics
```

### Data Validation

```bash
python cli_main.py research validate-data data.csv --rules rules.json
```

### Obsidian Sync

```bash
python cli_main.py research obsidian-sync ~/Documents/Obsidian/Research
```

## 📖 Task Configuration

Κάθε task υποστηρίζει:

```json
{
    "name": "unique_task_name",
    "type": "code_generation",
    "description": "What this does",
    "prompt": "AI prompt here...",
    "system_prompt": "You are an expert...",
    "depends_on": ["task1", "task2"],
    "checkpoint": true,
    "checkpoint_desc": "Review needed",
    "input_prompt": "Approve? (yes/no)",
    "tool": "save_file",
    "temperature": 0.7,
    "max_tokens": 2000,
    "use_cache": true
}
```

## 🔧 Environment Variables

| Variable | Description |
|----------|-------------|
| `KIMI_API_KEY` | Moonshot AI API key |
| `DEEPSEEK_API_KEY` | DeepSeek API key |
| `ANTHROPIC_API_KEY` | Claude API key |
| `OPENAI_API_KEY` | OpenAI API key |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token |
| `TELEGRAM_CHAT_ID` | Telegram chat ID |
| `SLACK_WEBHOOK_URL` | Slack webhook URL |
| `DAILY_AI_BUDGET` | Daily spending limit |

## 🐛 Troubleshooting

### Project stuck in RUNNING status

```bash
python cli_main.py status my_project
```

### API Key errors

```bash
python -c "from ai_router import ModelRouter; print('OK')"
```

## 📄 License

MIT License
