# Manus-Win11 Project Structure

## Overview

This document describes the complete folder structure and organization of the Manus-Win11 project.

## Directory Layout

```
E:\Documents\Vibe-Coding\weebot/
├── manus_win11/                  # Main Python package
│   ├── __init__.py
│   ├── main.py                   # Entry point
│   ├── config/                   # Configuration module
│   │   ├── __init__.py
│   │   └── settings.py           # Constants & settings
│   ├── utils/                    # Utility modules
│   │   ├── __init__.py
│   │   └── logger.py             # Logging utilities
│   ├── tools/                    # Automation tools
│   │   ├── __init__.py
│   │   ├── powershell_tool.py    # PowerShell execution
│   │   ├── browser_tool.py       # Browser automation
│   │   └── heuristic_router.py   # Tool selection logic
│   ├── core/                     # Core agent functionality
│   │   ├── __init__.py
│   │   ├── safety.py             # Safety mechanisms
│   │   └── agent.py              # Main agent logic
│   ├── ai_router.py              # AI model routing
│   ├── notifications.py          # Notification system
│   ├── state_manager.py          # State persistence
│   └── agent_core_v2.py          # Enhanced agent core
│
├── research_modules/             # Research-specific tools
│   ├── __init__.py
│   ├── reproducibility.py        # Reproducible research
│   ├── data_validator.py         # Data validation
│   └── literature.py             # Literature management
│
├── integrations/                 # External integrations
│   ├── __init__.py
│   ├── obsidian.py               # Obsidian vault sync
│   └── zotero.py                 # Zotero integration
│
├── cli/                          # Command-line interface
│   ├── __init__.py
│   └── main.py                   # CLI entry point
│
├── templates/                    # Template files
├── cache/                        # Cache directory
├── logs/                         # Log files
├── run.py                        # Main runner script
├── INSTALL.py                    # Setup script
└── PROJECT_STRUCTURE.md          # This file
```

## Source File Mapping

| Source File | Destination | Description |
|-------------|-------------|-------------|
| `config_settings.py` | `manus_win11/config/settings.py` | Configuration constants |
| `utils_logger.py` | `manus_win11/utils/logger.py` | Logging utilities |
| `tools_powershell.py` | `manus_win11/tools/powershell_tool.py` | PowerShell tool |
| `tools_browser.py` | `manus_win11/tools/browser_tool.py` | Browser automation |
| `tools_heuristic_router.py` | `manus_win11/tools/heuristic_router.py` | Tool routing |
| `core_safety.py` | `manus_win11/core/safety.py` | Safety mechanisms |
| `core_agent.py` | `manus_win11/core/agent.py` | Agent core |
| `ai_router.py` | `manus_win11/ai_router.py` | AI routing |
| `notifications.py` | `manus_win11/notifications.py` | Notifications |
| `state_manager.py` | `manus_win11/state_manager.py` | State management |
| `agent_core_v2.py` | `manus_win11/agent_core_v2.py` | Enhanced agent |
| `research_reproducibility.py` | `research_modules/reproducibility.py` | Reproducibility |
| `research_data_validator.py` | `research_modules/data_validator.py` | Data validation |
| `research_literature.py` | `research_modules/literature.py` | Literature |
| `integrations_obsidian.py` | `integrations/obsidian.py` | Obsidian |
| `integrations_zotero.py` | `integrations/zotero.py` | Zotero |
| `cli_main.py` | `cli/main.py` | CLI interface |

## Import Changes

### Old Imports (flat structure)
```python
from config_settings import WORKSPACE_ROOT
from tools_powershell import PowerShellTool
from core_safety import SafetyChecker
```

### New Imports (package structure)
```python
# Absolute imports
from manus_win11.config.settings import WORKSPACE_ROOT
from manus_win11.tools.powershell_tool import PowerShellTool
from manus_win11.core.safety import SafetyChecker

# Relative imports (within package)
from ..config.settings import WORKSPACE_ROOT
from ..tools.powershell_tool import PowerShellTool
```

## Usage

### Running the Agent
```bash
python run.py
```

### Using CLI
```bash
python -m cli.main --help
python -m cli.main create my_project "Description"
```

### Importing in Python
```python
from manus_win11 import ManusAgent, AgentConfig
from manus_win11.core.agent import RecursiveManusAgent
```

## Setup Instructions

1. Run the setup script:
   ```bash
   python INSTALL.py
   ```

2. Finalize file organization:
   ```bash
   python finalize_setup.py
   ```

3. Run the agent:
   ```bash
   python run.py
   ```

## Module Dependencies

```
manus_win11/
├── config/          (no internal deps)
├── utils/           (no internal deps)
├── tools/           -> config, utils
├── core/            -> config, utils, tools
├── ai_router.py     (standalone)
├── notifications.py (standalone)
├── state_manager.py (standalone)
└── agent_core_v2.py -> ai_router, notifications, state_manager

research_modules/    (standalone)
integrations/        (standalone)
cli/                 -> manus_win11, research_modules, integrations
```
