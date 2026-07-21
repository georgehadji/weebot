import ast
import json
import os
from pathlib import Path

# Configuration
TOOLS_DIR = Path("weebot/tools")
OUTPUT_FILE = Path("weebot-ui/public/schemas/tool_registry.json")

def get_base_tool_classes(tree):
    """Finds classes inheriting from BaseTool."""
    classes = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                if isinstance(base, ast.Name) and base.id == 'BaseTool':
                    classes.append(node)
                # Handle cases where BaseTool might be aliased (though unlikely here)
    return classes

def extract_metadata(class_node):
    """Extracts name, description, parameters from class fields."""
    metadata = {}
    
    # We need to look at assignments in the class body to find name/description/parameters
    # This is simplified and assumes they are class-level attributes
    for node in class_node.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    if target.id in ['name', 'description']:
                        if isinstance(node.value, ast.Constant):
                            metadata[target.id] = node.value.value
                    elif target.id == 'parameters':
                        # This is harder as it could be a complex dictionary
                        # For now, let's just mark it as found
                        metadata[target.id] = "Complex structure - see source"
    
    return metadata

def generate_schema():
    registry = {}
    
    for tool_file in TOOLS_DIR.glob("*.py"):
        if tool_file.name in ['__init__.py', 'base.py']:
            continue
            
        print(f"Analyzing {tool_file.name}...")
        try:
            with open(tool_file, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read())
            
            tool_classes = get_base_tool_classes(tree)
            for tool_class in tool_classes:
                metadata = extract_metadata(tool_class)
                if 'name' in metadata:
                    registry[metadata['name']] = {
                        "file": tool_file.name,
                        "description": metadata.get('description', ''),
                        "has_parameters": 'parameters' in metadata
                    }
        except Exception as e:
            print(f"Error parsing {tool_file.name}: {e}")
            
    # Ensure directory exists
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2)
    
    print(f"\n✅ Schema generated at {OUTPUT_FILE}")

if __name__ == "__main__":
    generate_schema()
