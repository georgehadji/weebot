#!/usr/bin/env python3
"""
Organize Python files into the proper folder structure
Updates imports to work with the new package structure
"""
import shutil
from pathlib import Path

def main():
    base = Path(__file__).parent.absolute()
    
    # Mapping: (source_file, dest_folder, new_filename)
    files_to_move = [
        # Core framework
        ('config_settings.py', 'manus_win11/config', 'settings.py'),
        ('utils_logger.py', 'manus_win11/utils', 'logger.py'),
        ('tools_powershell.py', 'manus_win11/tools', 'powershell_tool.py'),
        ('tools_browser.py', 'manus_win11/tools', 'browser_tool.py'),
        ('tools_heuristic_router.py', 'manus_win11/tools', 'heuristic_router.py'),
        ('core_safety.py', 'manus_win11/core', 'safety.py'),
        ('core_agent.py', 'manus_win11/core', 'agent.py'),
        ('main_agent.py', 'manus_win11', 'main.py'),
        
        # Agent management  
        ('ai_router.py', 'manus_win11', 'ai_router.py'),
        ('notifications.py', 'manus_win11', 'notifications.py'),
        ('state_manager.py', 'manus_win11', 'state_manager.py'),
        ('agent_core_v2.py', 'manus_win11', 'agent_core_v2.py'),
        
        # Research
        ('research_reproducibility.py', 'research_modules', 'reproducibility.py'),
        ('research_data_validator.py', 'research_modules', 'data_validator.py'),
        ('research_literature.py', 'research_modules', 'literature.py'),
        
        # Integrations
        ('integrations_obsidian.py', 'integrations', 'obsidian.py'),
        ('integrations_zotero.py', 'integrations', 'zotero.py'),
        
        # CLI
        ('cli_main.py', 'cli', 'main.py'),
    ]
    
    print("=" * 60)
    print("Organizing Python Files")
    print("=" * 60)
    print()
    
    moved = 0
    skipped = 0
    errors = []
    
    for src_name, dest_folder, new_name in files_to_move:
        src = base / src_name
        dest = base / dest_folder / new_name
        
        if src.exists():
            try:
                # Ensure destination folder exists
                dest.parent.mkdir(parents=True, exist_ok=True)
                
                # Read content
                content = src.read_text(encoding='utf-8')
                
                # Update imports for files inside packages
                if dest_folder.startswith('manus_win11/'):
                    # Convert flat imports to package imports
                    import_updates = [
                        ('from config_settings ', 'from manus_win11.config.settings '),
                        ('from utils_logger ', 'from manus_win11.utils.logger '),
                        ('from tools_powershell ', 'from manus_win11.tools.powershell_tool '),
                        ('from tools_browser ', 'from manus_win11.tools.browser_tool '),
                        ('from tools_heuristic_router ', 'from manus_win11.tools.heuristic_router '),
                        ('from core_safety ', 'from manus_win11.core.safety '),
                        ('from core_agent ', 'from manus_win11.core.agent '),
                        ('import config_settings', 'import manus_win11.config.settings as config_settings'),
                        ('import utils_logger', 'import manus_win11.utils.logger as utils_logger'),
                    ]
                    
                    for old, new in import_updates:
                        content = content.replace(old, new)
                
                # Write to destination
                dest.write_text(content, encoding='utf-8')
                
                # Remove source file
                src.unlink()
                
                print(f"  [OK] {src_name} -> {dest_folder}/{new_name}")
                moved += 1
                
            except Exception as e:
                print(f"  [ERR] {src_name}: {e}")
                errors.append((src_name, str(e)))
        else:
            print(f"  [SKIP] {src_name} (not found)")
            skipped += 1
    
    print()
    print("=" * 60)
    print(f"Done! Moved: {moved}, Skipped: {skipped}, Errors: {len(errors)}")
    print("=" * 60)
    
    if errors:
        print("\nErrors encountered:")
        for fname, err in errors:
            print(f"  - {fname}: {err}")
    
    print("\nNext steps:")
    print("  1. Review the files in their new locations")
    print("  2. Test imports: python -c \"import manus_win11\"")
    print("  3. Run: python run.py --diagnostic")

if __name__ == '__main__':
    main()
    
    import sys
    if sys.platform == 'win32':
        input('\n\nPress Enter to exit...')
