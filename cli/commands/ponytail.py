"""Ponytail lazy-senior-dev CLI commands.

Provides slash-command-style access to Ponytail modes and review/audit tools:

    python -m cli.main ponytail [lite|full|ultra|off]
    python -m cli.main ponytail-review
    python -m cli.main ponytail-audit [--path PATH]
    python -m cli.main ponytail-help
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.panel import Panel

console = Console()
logger = logging.getLogger(__name__)

# ── persistence helpers ──────────────────────────────────────────────────────

_PONYTAIL_MODE_FILE = Path.cwd() / ".weebot" / "ponytail_mode.json"
_ALLOWED_MODES = {"off", "lite", "full", "ultra"}


def _mode_file() -> Path:
    """Return the per-project Ponytail mode file, creating parent if needed."""
    _PONYTAIL_MODE_FILE.parent.mkdir(parents=True, exist_ok=True)
    return _PONYTAIL_MODE_FILE


def read_ponytail_mode() -> str:
    """Read the persisted Ponytail mode, falling back to settings/env."""
    # 1. Project-local JSON file (highest runtime priority)
    mode_file = _mode_file()
    if mode_file.exists():
        try:
            data = json.loads(mode_file.read_text(encoding="utf-8"))
            mode = str(data.get("mode", "")).strip().lower()
            if mode in _ALLOWED_MODES:
                return mode
        except Exception as exc:
            logger.debug("Could not read ponytail mode file: %s", exc)

    # 2. WeebotSettings / environment
    try:
        from weebot.config.settings import WeebotSettings

        settings = WeebotSettings()
        if settings.ponytail_mode in _ALLOWED_MODES:
            return settings.ponytail_mode
    except Exception as exc:
        logger.debug("Could not read WeebotSettings for ponytail mode: %s", exc)

    return "off"


def write_ponytail_mode(mode: str) -> None:
    """Persist *mode* to the project-local JSON file."""
    mode_file = _mode_file()
    mode_file.write_text(json.dumps({"mode": mode}, indent=2), encoding="utf-8")


# ── shared helpers ───────────────────────────────────────────────────────────


def _load_skill(name: str) -> str:
    """Load a built-in skill's raw content by name."""
    from weebot.application.skills.skill_registry import SkillRegistry

    registry = SkillRegistry()
    registry.load_all()
    skill = registry.get(name)
    if skill is None:
        raise click.ClickException(f"Skill '{name}' not found. Did the builtin skills load?")
    return skill.content


def _get_llm() -> Any:
    """Resolve LLMPort from the shared DI container."""
    from weebot.application.di import Container
    from weebot.application.ports.llm_port import LLMPort

    container = Container()
    container.configure_defaults()
    return container.get(LLMPort)


# ── commands ─────────────────────────────────────────────────────────────────


@click.command(name="ponytail")
@click.argument("level", required=False, default="full")
def cmd_ponytail(level: str) -> None:
    """Activate/deactivate Ponytail mode: lite | full | ultra | off."""
    normalized = level.strip().lower()
    if normalized not in _ALLOWED_MODES:
        raise click.ClickException(
            f"Invalid level {level!r}. Choose one of: off, lite, full, ultra."
        )

    write_ponytail_mode(normalized)

    if normalized == "off":
        console.print("[dim]Ponytail deactivated.[/dim]")
        return

    messages = {
        "lite": "Ponytail lite: will name the lazier alternative.",
        "full": "Ponytail full: The Ladder is enforced.",
        "ultra": "Ponytail ultra: YAGNI extremist mode. Requirements will be challenged.",
    }
    console.print(Panel(messages[normalized], title="🐴 Ponytail", style="green"))


@click.command(name="ponytail-review")
@click.option("--staged", is_flag=True, help="Review staged changes instead of unstaged changes.")
def cmd_ponytail_review(staged: bool) -> None:
    """Review current git changes for over-engineering."""
    cmd = ["git", "diff", "--cached"] if staged else ["git", "diff", "HEAD"]
    try:
        diff = subprocess.check_output(
            cmd, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace"
        )
    except subprocess.CalledProcessError as exc:
        if isinstance(exc.output, str):
            output = exc.output
        else:
            output = exc.output.decode("utf-8", errors="replace")
        raise click.ClickException(f"Could not read git diff: {output}") from exc
    except FileNotFoundError as exc:
        raise click.ClickException("git executable not found on PATH.") from exc

    if not diff.strip():
        console.print("[dim]No changes to review.[/dim]")
        return

    skill_text = _load_skill("ponytail-review")
    prompt = (
        f"{skill_text}\n\n"
        "Review the following diff for over-engineering only, not correctness.\n\n"
        f"```diff\n{diff}\n```"
    )

    llm = _get_llm()
    try:
        response = llm.complete(prompt)
        console.print(response)
    except Exception as exc:
        logger.exception("ponytail-review LLM call failed")
        raise click.ClickException(f"LLM review failed: {exc}") from exc


@click.command(name="ponytail-audit")
@click.option("--path", default=".", help="Path to audit (default: current directory).")
@click.option(
    "--max-files", default=200, help="Maximum number of files to include in the audit catalog."
)
def cmd_ponytail_audit(path: str, max_files: int) -> None:
    """Audit the workspace for over-engineering and bloat."""
    root = Path(path).resolve()
    if not root.exists():
        raise click.ClickException(f"Path does not exist: {root}")

    files: list[Path] = []
    for p in root.rglob("*"):
        if p.is_file() and ".git" not in p.parts:
            files.append(p)
        if len(files) >= max_files:
            break

    if not files:
        console.print("[dim]No files found to audit.[/dim]")
        return

    catalog = "\n".join(
        f"{f.relative_to(root).as_posix()} ({f.stat().st_size} bytes)" for f in sorted(files)
    )

    skill_text = _load_skill("ponytail-audit")
    prompt = (
        f"{skill_text}\n\n"
        "Audit the following file catalog for over-engineering. "
        "Focus on likely bloat: wrappers, single-implementation interfaces, "
        "hand-rolled stdlib, dead config, and unneeded dependencies.\n\n"
        f"```\n{catalog}\n```"
    )

    llm = _get_llm()
    try:
        response = llm.complete(prompt)
        console.print(response)
    except Exception as exc:
        logger.exception("ponytail-audit LLM call failed")
        raise click.ClickException(f"LLM audit failed: {exc}") from exc


@click.command(name="ponytail-help")
def cmd_ponytail_help() -> None:
    """Show the Ponytail quick-reference card."""
    try:
        text = _load_skill("ponytail-help")
        console.print(text)
    except click.ClickException:
        console.print(
            "[yellow]ponytail-help skill not found.[/yellow] " "Builtin skills may not be loaded."
        )
