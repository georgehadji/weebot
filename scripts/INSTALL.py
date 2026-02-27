#!/usr/bin/env python3
"""
Manus-Win11 Agent Framework - Complete Installation Script
This script creates the folder structure and sets up the project.
"""
import os
import sys
from pathlib import Path

def create_structure():
    """Create the complete project structure"""
    base = Path(__file__).parent.absolute()
    print(f"Setting up in: {base}\n")
    
    # Define folder structure
    folders = {
        'manus_win11': [
            'config',
            'utils',
            'tools',
            'core',
            'domain',
            'application',
            'infrastructure',
            'di',
            'logs',
        ],
        'research_modules': [],
        'integrations': [],
        'cli': [],
        'templates': [],
        'cache': [],
        'experiments': [],
    }
    
    created = []
    
    # Create folders
    for main_folder, subfolders in folders.items():
        main_path = base / main_folder
        main_path.mkdir(exist_ok=True)
        created.append(main_folder + '/')
        
        for sub in subfolders:
            sub_path = main_path / sub
            sub_path.mkdir(exist_ok=True)
            created.append(f"  {sub}/")
    
    print("Created directories:")
    for c in created:
        print(f"  {c}")
    
    # Create __init__.py files
    packages = [
        'manus_win11',
        'manus_win11/config',
        'manus_win11/utils',
        'manus_win11/tools',
        'manus_win11/core',
        'manus_win11/domain',
        'manus_win11/application',
        'manus_win11/infrastructure',
        'manus_win11/di',
        'research_modules',
        'integrations',
        'cli',
    ]
    
    print("\nCreated package files:")
    for pkg in packages:
        init_file = base / pkg / '__init__.py'
        if not init_file.exists():
            init_file.write_text(f'"""{pkg.replace("/", ".")} package."""\n')
            print(f"  {pkg}/__init__.py")
    
    return base

def create_runner(base: Path):
    """Create the main runner script"""
    runner = base / 'run.py'
    runner_code = '''#!/usr/bin/env python3
"""Main runner for Manus-Win11 Agent"""
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from manus_win11.main import main
    import asyncio
    
    if __name__ == "__main__":
        asyncio.run(main())
except ImportError as e:
    print(f"Error importing modules: {e}")
    print("Make sure all dependencies are installed: pip install -r requirements.txt")
    sys.exit(1)
'''
    runner.write_text(runner_code)
    print(f"\nCreated: run.py")

def create_env_example(base: Path):
    """Create .env.example file"""
    env_file = base / '.env.example'
    env_content = '''# AI API Keys (required at least one)
KIMI_API_KEY=your_kimi_key_here
DEEPSEEK_API_KEY=your_deepseek_key_here
ANTHROPIC_API_KEY=your_claude_key_here
OPENAI_API_KEY=your_openai_key_here

# Notifications (optional)
TELEGRAM_BOT_TOKEN=your_telegram_token
TELEGRAM_CHAT_ID=your_chat_id
SLACK_WEBHOOK_URL=your_slack_webhook

# Settings
DAILY_AI_BUDGET=10.0
'''
    env_file.write_text(env_content)
    print(f"Created: .env.example")

def main():
    print("=" * 60)
    print("Manus-Win11 Agent Framework - Setup")
    print("=" * 60)
    print()
    
    base = create_structure()
    create_runner(base)
    create_env_example(base)
    
    print("\n" + "=" * 60)
    print("Setup Complete!")
    print("=" * 60)
    print("\nNext steps:")
    print("  1. Copy .env.example to .env and add your API keys")
    print("  2. Install dependencies: pip install -r requirements.txt")
    print("  3. Run: python run.py --diagnostic")
    print("  4. Run: python run.py --interactive")
    print()
    print("To organize Python files into folders, manually move them:")
    print("  - config_settings.py -> manus_win11/config/settings.py")
    print("  - utils_logger.py -> manus_win11/utils/logger.py")
    print("  - tools_*.py -> manus_win11/tools/")
    print("  - core_*.py -> manus_win11/core/")
    print("  - main_agent.py -> manus_win11/main.py")
    print("  - research_*.py -> research_modules/")
    print("  - integrations_*.py -> integrations/")
    print("  - cli_main.py -> cli/main.py")

if __name__ == '__main__':
    main()
    
    if sys.platform == 'win32':
        input('\n\nPress Enter to exit...')
