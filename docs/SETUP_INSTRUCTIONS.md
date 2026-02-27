# Setup Instructions for Manus-Win11 Agent Framework

## Step 1: Create Folder Structure

Run the folder creation script:

```bash
python create_folders.py
```

This will create:
```
manus_win11/
├── config/
├── utils/
├── tools/
├── core/
├── domain/
├── application/
├── infrastructure/
├── di/
└── logs/

research_modules/
integrations/
cli/
templates/
cache/
```

## Step 2: Organize Python Files

Run the file organization script:

```bash
python organize_files.py
```

This copies files to their proper locations.

## Step 3: Manual File Organization (Alternative)

If the script doesn't work, manually move files:

| Source File | Destination |
|-------------|-------------|
| `config_settings.py` | `manus_win11/config/settings.py` |
| `utils_logger.py` | `manus_win11/utils/logger.py` |
| `tools_powershell.py` | `manus_win11/tools/powershell_tool.py` |
| `tools_browser.py` | `manus_win11/tools/browser_tool.py` |
| `tools_heuristic_router.py` | `manus_win11/tools/heuristic_router.py` |
| `core_safety.py` | `manus_win11/core/safety.py` |
| `core_agent.py` | `manus_win11/core/agent.py` |
| `main_agent.py` | `manus_win11/main.py` |
| `ai_router.py` | `manus_win11/ai_router.py` |
| `notifications.py` | `manus_win11/notifications.py` |
| `state_manager.py` | `manus_win11/state_manager.py` |
| `agent_core_v2.py` | `manus_win11/agent_core_v2.py` |
| `research_reproducibility.py` | `research_modules/reproducibility.py` |
| `research_data_validator.py` | `research_modules/data_validator.py` |
| `research_literature.py` | `research_modules/literature.py` |
| `integrations_obsidian.py` | `integrations/obsidian.py` |
| `integrations_zotero.py` | `integrations/zotero.py` |
| `cli_main.py` | `cli/main.py` |

## Step 4: Update Imports

After moving files, update the import statements in each file:

**Example changes:**
```python
# Old (in config_settings.py)
# (no import needed)

# New (in manus_win11/config/settings.py)
# Same code, just in new location

# Old (in files that imported config_settings)
from config_settings import WORKSPACE_ROOT

# New
from manus_win11.config.settings import WORKSPACE_ROOT
```

## Step 5: Install Dependencies

```bash
pip install -r requirements.txt
```

## Step 6: Run the Agent

```bash
# Interactive mode
python -m manus_win11.main --interactive

# Or run diagnostics
python -m manus_win11.main --diagnostic

# Or use CLI
python -m cli.main create my_project "Test"
```

## Environment Variables

Create a `.env` file:

```env
KIMI_API_KEY=your_key
DEEPSEEK_API_KEY=your_key
ANTHROPIC_API_KEY=your_key
OPENAI_API_KEY=your_key
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHAT_ID=your_chat_id
SLACK_WEBHOOK_URL=your_webhook
DAILY_AI_BUDGET=10.0
```

## Final Structure

After setup, your project should look like:

```
weebot/
├── manus_win11/
│   ├── __init__.py
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py
│   ├── utils/
│   │   ├── __init__.py
│   │   └── logger.py
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── powershell_tool.py
│   │   ├── browser_tool.py
│   │   └── heuristic_router.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── safety.py
│   │   └── agent.py
│   ├── main.py
│   └── ...
├── research_modules/
│   └── ...
├── integrations/
│   └── ...
├── cli/
│   └── main.py
├── requirements.txt
└── README_PROJECT.md
```
