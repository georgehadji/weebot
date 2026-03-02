# weebot — E2E Examples

Standalone runnable scripts that demonstrate weebot's tool stack end-to-end.

## Prerequisites

```bash
pip install mcp>=1.5 aiohttp playwright apscheduler psutil
python -m playwright install chromium
```

## Examples

| File | Tools used | Requires |
|------|-----------|----------|
| `01_web_research.py` | WebSearchTool, PythonExecuteTool, StrReplaceEditorTool | Network |
| `02_data_analysis.py` | PythonExecuteTool | — |
| `03_file_automation.py` | BashTool, StrReplaceEditorTool | Windows/PowerShell |
| `04_mcp_server_demo.py` | WeebotMCPServer, ActivityStream | — |

## Running

```bash
# From the project root
python examples/01_web_research.py
python examples/02_data_analysis.py
python examples/03_file_automation.py
python examples/04_mcp_server_demo.py
```

Output files (when generated) are written to `examples/output/`.
