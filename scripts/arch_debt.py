"""Architecture debt: find core→infra deferred imports."""
import ast, sys, re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from weebot.core.layer_classifier import layer_for_module

core_dir = Path("weebot/core")
results = []

for fp in sorted(core_dir.rglob("*.py")):
    content = fp.read_text(encoding="utf-8")
    tree = ast.parse(content)
    rel = str(fp).replace("\\", "/")
    
    for node in ast.walk(tree):
        imported = None
        if isinstance(node, ast.ImportFrom) and node.module:
            imported = node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported = alias.name
        
        if imported and (imported.startswith("weebot.tools") or imported.startswith("weebot.infrastructure")):
            tgt_layer = layer_for_module(imported.replace(".", "/") + ".py")
            # Check if it's a module-level import or inside a function
            is_module_level = True
            for ancestor in ast.walk(tree):
                if isinstance(ancestor, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if hasattr(ancestor, 'body'):
                        for child in ast.walk(ancestor):
                            if child is node:
                                is_module_level = False
                                break
            
            # Suggest abstraction
            if "tools.base" in imported or "ToolCollection" in imported:
                suggestion = "AgentTool Protocol (weebot/core/tool_interfaces.py)"
            elif "tools.tool_registry" in imported or "RoleBasedToolRegistry" in imported:
                suggestion = "ToolRegistryPort (new port in weebot/core/ports/)"
            elif "tools.browser_tool" in imported:
                suggestion = "BrowserPort (weebot/application/ports/browser_port.py)"
            elif "tools.powershell_tool" in imported:
                suggestion = "ShellPort (new port in weebot/core/ports/)"
            elif "tools.heuristic_router" in imported:
                suggestion = "RouterPort (new port in weebot/core/ports/)"
            elif "agent_core_v2" in imported:
                suggestion = "Remove — deprecated, migrate callers to Container.build_agent_runner()"
            else:
                suggestion = "Extract interface to weebot/core/ports/"
            
            results.append({
                "file": rel,
                "import": imported,
                "module_level": is_module_level,
                "suggestion": suggestion,
                "src_layer": layer_for_module(rel),
                "tgt_layer": tgt_layer,
            })

out = Path("Output/arch-debt")
out.mkdir(exist_ok=True)

md = ["# Core → Infrastructure Import Debt", "",
      f"**Files analyzed:** {len(list(core_dir.rglob('*.py')))} Python files in weebot/core/",
      f"**Deferred imports found:** {len(results)}", "",
      "These are remaining imports from core to infrastructure/application that",
      "were moved to function bodies (lazy) but still exist in the static",
      "dependency graph. Each entry suggests a proper abstraction.", "",
      "| File | Import | Level | Suggestion |",
      "|------|--------|-------|------------|"]
for r in sorted(results, key=lambda x: x["file"]):
    level = "module" if r["module_level"] else "func-body"
    md.append(f"| {r['file']} | `{r['import']}` | {level} | {r['suggestion']} |")
md.append("")
md.append(f"**Module-level imports (actionable):** {sum(1 for r in results if r['module_level'])}")
md.append(f"**Function-body imports (deferred, low risk):** {sum(1 for r in results if not r['module_level'])}")

(out / "core-infra-imports.md").write_text("\n".join(md))
print(f"Found {len(results)} core→infra imports across {len(set(r['file'] for r in results))} files")
print(f"  Module-level: {sum(1 for r in results if r['module_level'])}")
print(f"  Func-body (deferred): {sum(1 for r in results if not r['module_level'])}")
