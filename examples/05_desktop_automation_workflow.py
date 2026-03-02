"""Example 05 — Desktop Automation Workflow
===========================================
Demonstrates a complete desktop automation pipeline:

  Step 1  BashTool            → query system info (PowerShell)
  Step 2  StrReplaceEditorTool → create backup structure
  Step 3  BashTool            → organize files (copy operations)
  Step 4  BashTool            → verify integrity (checksums)
  Step 5  StrReplaceEditorTool → save automation report

Requirements: Windows 11 + PowerShell (BashTool steps gracefully skipped
              if PowerShell is unavailable).

Usage:
    python examples/05_desktop_automation_workflow.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from weebot.activity_stream import ActivityStream
from weebot.tools.bash_tool import BashTool
from weebot.tools.file_editor import StrReplaceEditorTool

# All backup files land inside examples/output/backup/
BACKUP_DIR = str(Path(__file__).parent / "output" / "backup")
REPORT_PATH = str(Path(__file__).parent / "output" / "automation_report.json")


async def step_system_info(bash: BashTool, stream: ActivityStream) -> dict:
    """Query system information via PowerShell."""
    print("🖥️   Step 1: Querying system info …")

    cmd = (
        "[PSCustomObject]@{ "
        "  ComputerName = $env:COMPUTERNAME; "
        "  Username = $env:USERNAME; "
        "  OSVersion = [System.Environment]::OSVersion.VersionString; "
        "  ProcessorCount = (Get-CimInstance Win32_ComputerSystem).NumberOfLogicalProcessors; "
        "  TotalMemoryGB = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 2); "
        "  Timestamp = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss') "
        "} | ConvertTo-Json"
    )

    try:
        result = await bash.execute(command=cmd, timeout=15)
    except Exception as exc:
        print(f"  ⚠️   Skipped (PowerShell unavailable): {exc}")
        return {}

    if result.is_error:
        print(f"  ⚠️   Skipped: {result.error}")
        return {}

    try:
        sys_info = json.loads(result.output.strip())
        stream.push("example-05", "tool", "bash: system info query")
        print(f"  ✅  Computer: {sys_info.get('ComputerName', 'N/A')}")
        print(f"  ✅  User: {sys_info.get('Username', 'N/A')}")
        print(f"  ✅  OS: {sys_info.get('OSVersion', 'N/A')}")
        print(f"  ✅  Memory: {sys_info.get('TotalMemoryGB', 'N/A')} GB")
        return sys_info
    except (json.JSONDecodeError, ValueError):
        print(f"  ⚠️   Could not parse system info")
        return {}
    finally:
        print()


async def step_create_backup_structure(editor: StrReplaceEditorTool, stream: ActivityStream) -> None:
    """Create a backup directory structure."""
    print("📁  Step 2: Creating backup structure …")

    os.makedirs(BACKUP_DIR, exist_ok=True)

    # Create backup manifest file
    manifest = {
        "backup_timestamp": datetime.now().isoformat(),
        "backup_version": "1.0",
        "files_backed_up": 0,
        "total_size_bytes": 0,
        "status": "in_progress",
    }

    manifest_path = f"{BACKUP_DIR}/MANIFEST.json"
    result = await editor.execute(
        command="create",
        path=manifest_path,
        file_text=json.dumps(manifest, indent=2),
    )

    if result.is_error:
        print(f"  ❌  Manifest creation failed: {result.error}")
    else:
        print(f"  ✅  Backup manifest created")
        stream.push("example-05", "tool", "file_editor: create backup manifest")

    # Create backup subdirectories
    subdirs = ["documents", "config", "logs"]
    for subdir in subdirs:
        subdir_path = f"{BACKUP_DIR}/{subdir}"
        os.makedirs(subdir_path, exist_ok=True)
        print(f"  ✅  Created subdirectory: {subdir}")

    stream.push("example-05", "tool", "file_editor: backup structure")
    print()


async def step_copy_files(bash: BashTool, stream: ActivityStream) -> int:
    """Copy sample files to backup (using PowerShell copy)."""
    print("📋  Step 3: Organizing files (copying samples) …")

    # Create source files to backup
    examples_dir = str(Path(__file__).parent)

    cmd = (
        f"Copy-Item '{examples_dir}\\01_web_research.py' "
        f"'{BACKUP_DIR}\\documents\\' -Force 2>$null; "
        f"Copy-Item '{examples_dir}\\02_data_analysis.py' "
        f"'{BACKUP_DIR}\\documents\\' -Force 2>$null; "
        f"Copy-Item '{examples_dir}\\README.md' "
        f"'{BACKUP_DIR}\\documents\\' -Force 2>$null; "
        f"(Get-ChildItem -Path '{BACKUP_DIR}\\documents\\' | Measure-Object).Count"
    )

    try:
        result = await bash.execute(command=cmd, timeout=10)
    except Exception as exc:
        print(f"  ⚠️   Copy skipped (PowerShell unavailable): {exc}")
        return 0

    if result.is_error:
        print(f"  ⚠️   Copy skipped: {result.error}")
        return 0

    try:
        file_count = int(result.output.strip().split('\n')[-1])
        print(f"  ✅  Copied {file_count} files to backup")
        stream.push("example-05", "tool", f"bash: copy {file_count} files")
        return file_count
    except (ValueError, IndexError):
        print(f"  ⚠️   Could not parse copy result")
        return 0
    finally:
        print()


async def step_verify_integrity(bash: BashTool, stream: ActivityStream) -> dict:
    """Verify backup integrity using file hashes."""
    print("🔍  Step 4: Verifying backup integrity …")

    cmd = (
        f"Get-ChildItem -Path '{BACKUP_DIR}\\documents\\' -File | "
        f"ForEach-Object {{ "
        f"  $hash = (Get-FileHash $_.FullName -Algorithm SHA256).Hash; "
        f"  [PSCustomObject]@{{ Name = $_.Name; Hash = $hash.Substring(0,16); Size = $_.Length }} "
        f"}} | ConvertTo-Json"
    )

    try:
        result = await bash.execute(command=cmd, timeout=10)
    except Exception as exc:
        print(f"  ⚠️   Verify skipped (PowerShell unavailable): {exc}")
        return {}

    if result.is_error:
        print(f"  ⚠️   Verify skipped: {result.error}")
        return {}

    try:
        # Handle single object vs array
        file_data = json.loads(result.output.strip())
        if not isinstance(file_data, list):
            file_data = [file_data] if file_data else []

        for fdata in file_data:
            print(f"  ✅  {fdata.get('Name', '?'):<25} SHA256: {fdata.get('Hash', '?')} ({fdata.get('Size', 0)} bytes)")

        stream.push("example-05", "tool", f"bash: verify {len(file_data)} files")
        return {"files_verified": len(file_data), "file_details": file_data}
    except (json.JSONDecodeError, ValueError):
        print(f"  ⚠️   Could not parse verification results")
        return {}
    finally:
        print()


async def step_save_report(
    editor: StrReplaceEditorTool,
    stream: ActivityStream,
    sys_info: dict,
    file_count: int,
    verify_info: dict,
) -> None:
    """Save automation report as JSON."""
    print("📄  Step 5: Saving automation report …")

    report = {
        "automation_type": "desktop_backup",
        "timestamp": datetime.now().isoformat(),
        "system_info": sys_info,
        "backup_summary": {
            "backup_directory": BACKUP_DIR,
            "files_backed_up": file_count,
            "verification": verify_info,
        },
        "status": "completed",
    }

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    result = await editor.execute(
        command="create",
        path=REPORT_PATH,
        file_text=json.dumps(report, indent=2),
    )

    if result.is_error:
        print(f"  ❌  Report save failed: {result.error}")
    else:
        stream.push("example-05", "tool", f"file_editor: create {REPORT_PATH}")
        print(f"  ✅  Report saved → {REPORT_PATH}")

    print()


async def main() -> None:
    stream = ActivityStream()
    bash = BashTool()
    editor = StrReplaceEditorTool()

    print("🚀  Desktop Automation Workflow\n")

    sys_info = await step_system_info(bash, stream)
    await step_create_backup_structure(editor, stream)
    file_count = await step_copy_files(bash, stream)
    verify_info = await step_verify_integrity(bash, stream)
    await step_save_report(editor, stream, sys_info, file_count, verify_info)

    print(f"📋  Activity log ({len(stream.recent())} events):")
    for event in stream.recent():
        print(f"    [{event.kind}] {event.message}")


if __name__ == "__main__":
    asyncio.run(main())
