"""CLI support utilities for init/doctor/hooks/upgrade/implement flows."""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from weebot.config.settings import WeebotSettings, WORKSPACE_ROOT, LOGS_DIR
from weebot.templates.parser import TemplateParser
from weebot.templates.marketplace import TemplateMarketplace


# ---------------------------------------------------------------------------
# Platform detection / init
# ---------------------------------------------------------------------------


def detect_platform(root: Path, override: Optional[str] = None) -> Tuple[str, str, List[str]]:
    """Detect platform and tier based on repo signals."""
    if override:
        platform = override
        tier = "full"
        return platform, tier, [f"override:{override}"]

    signals: List[str] = []
    platform = "generic"

    if (root / "AGENTS.md").exists():
        platform = "codex"
        signals.append("AGENTS.md")
    elif (root / "CLAUDE.md").exists() or (root / ".claude").exists():
        platform = "claude"
        signals.append("CLAUDE.md/.claude")
    elif (root / ".cursor").exists() or (root / "CURSOR.md").exists():
        platform = "cursor"
        signals.append(".cursor/CURSOR.md")

    tier = "instructions-only" if os.getenv("WEEBOT_INSTRUCTIONS_ONLY") == "1" else "full"
    return platform, tier, signals


def init_project(
    root: Path,
    platform: Optional[str] = None,
    tier: Optional[str] = None,
    force: bool = False,
    create_env: bool = True,
) -> Path:
    """Initialize project config in .weebot/config.json."""
    root = root.resolve()
    config_dir = root / ".weebot"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.json"

    if config_path.exists() and not force:
        return config_path

    detected_platform, detected_tier, signals = detect_platform(root, override=platform)
    final_tier = tier or detected_tier

    config = {
        "created_at": datetime.now().isoformat(),
        "platform": detected_platform,
        "tier": final_tier,
        "signals": signals,
        "workspace_root": str(WORKSPACE_ROOT),
        "logs_dir": str(LOGS_DIR),
        "version": "1.0",
    }

    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

    if create_env:
        env_path = root / ".env"
        example_path = root / ".env.example"
        if not env_path.exists() and example_path.exists():
            shutil.copyfile(example_path, env_path)

    return config_path


# ---------------------------------------------------------------------------
# Hooks
# ---------------------------------------------------------------------------


def init_hooks(root: Path) -> List[Path]:
    """Create local hooks directory with example configs."""
    root = root.resolve()
    hooks_dir = root / ".weebot" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    created: List[Path] = []

    readme = hooks_dir / "README.md"
    if not readme.exists():
        readme.write_text(
            "weebot hooks directory.\n"
            "Store platform hook configs here and use `weebot hooks install` "
            "to copy into a target path.\n",
            encoding="utf-8",
        )
        created.append(readme)

    example = root / "claude_desktop_config.json.example"
    claude_cfg = hooks_dir / "claude_desktop_config.json"
    if example.exists() and not claude_cfg.exists():
        shutil.copyfile(example, claude_cfg)
        created.append(claude_cfg)

    manifest = hooks_dir / "hook_manifest.json"
    if not manifest.exists():
        manifest.write_text(
            json.dumps(
                {
                    "created_at": datetime.now().isoformat(),
                    "files": [p.name for p in hooks_dir.glob("*") if p.is_file()],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        created.append(manifest)

    return created


def install_hooks(
    root: Path,
    target: Path,
    force: bool = False,
    allow_outside: bool = False,
) -> List[Path]:
    """Install hooks into a target directory inside the project by default."""
    root = root.resolve()
    target = target.resolve()
    hooks_dir = root / ".weebot" / "hooks"

    if not hooks_dir.exists():
        raise FileNotFoundError("Hooks not initialized. Run `weebot hooks init` first.")

    if not allow_outside and not str(target).startswith(str(root)):
        raise ValueError("Refusing to install hooks outside project root. Use --allow-outside to override.")

    target.mkdir(parents=True, exist_ok=True)
    installed: List[Path] = []

    for item in hooks_dir.iterdir():
        if not item.is_file():
            continue
        dest = target / item.name
        if dest.exists() and not force:
            continue
        shutil.copyfile(item, dest)
        installed.append(dest)

    return installed


# ---------------------------------------------------------------------------
# Doctor diagnostics
# ---------------------------------------------------------------------------


@dataclass
class DoctorCheck:
    name: str
    status: str  # ok | warn | error
    details: str
    data: Dict[str, Any] | None = None


@dataclass
class RepairResult:
    """Result of an auto-repair attempt."""
    check_name: str
    repaired: bool
    message: str


@dataclass
class DoctorReport:
    checks: List[DoctorCheck]
    repairs: List[RepairResult] | None = None

    @property
    def summary(self) -> Dict[str, int]:
        counts = {"ok": 0, "warn": 0, "error": 0}
        for c in self.checks:
            if c.status in counts:
                counts[c.status] += 1
        return counts

    @property
    def ok(self) -> bool:
        return self.summary.get("error", 0) == 0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "summary": self.summary,
            "checks": [asdict(c) for c in self.checks],
        }


def run_doctor(root: Path, fix: bool = False) -> DoctorReport:
    """Run diagnostics and return a structured report.

    Args:
        root: Project root directory.
        fix: When True, attempt to auto-repair warnings (e.g. create missing
             directories, initialize missing databases).
    """
    checks: List[DoctorCheck] = []
    root = root.resolve()

    # API keys / settings
    try:
        settings = WeebotSettings()
        providers = settings.available_providers()
        if providers:
            checks.append(
                DoctorCheck(
                    name="ai_providers",
                    status="ok",
                    details=f"Providers configured: {', '.join(providers)}",
                    data={"providers": providers},
                )
            )
        else:
            checks.append(
                DoctorCheck(
                    name="ai_providers",
                    status="error",
                    details="No AI API keys configured",
                )
            )
    except Exception as exc:
        checks.append(
            DoctorCheck(
                name="ai_providers",
                status="error",
                details=f"Settings error: {exc}",
            )
        )

    # Workspace & logs
    checks.append(
        DoctorCheck(
            name="workspace_root",
            status="ok" if WORKSPACE_ROOT.exists() else "warn",
            details=str(WORKSPACE_ROOT),
        )
    )
    checks.append(
        DoctorCheck(
            name="logs_dir",
            status="ok" if (root / LOGS_DIR).exists() else "warn",
            details=str(root / LOGS_DIR),
        )
    )

    # Database health (projects.db)
    db_path = root / "projects.db"
    if not db_path.exists():
        checks.append(
            DoctorCheck(
                name="projects_db",
                status="warn",
                details="projects.db not found",
            )
        )
    else:
        try:
            with sqlite3.connect(db_path) as conn:
                conn.execute("SELECT name FROM sqlite_master LIMIT 1")
            checks.append(
                DoctorCheck(
                    name="projects_db",
                    status="ok",
                    details=str(db_path),
                )
            )
        except Exception as exc:
            checks.append(
                DoctorCheck(
                    name="projects_db",
                    status="error",
                    details=f"DB open failed: {exc}",
                )
            )

    # Templates validation
    parser = TemplateParser()
    builtin_dir = root / "weebot" / "templates" / "builtin"
    template_errors: List[str] = []
    template_count = 0
    if builtin_dir.exists():
        for tmpl in builtin_dir.glob("*.yaml"):
            try:
                parser.parse_file(tmpl)
                template_count += 1
            except Exception as exc:
                template_errors.append(f"{tmpl.name}: {exc}")
    if template_errors:
        checks.append(
            DoctorCheck(
                name="templates",
                status="warn",
                details=f"{len(template_errors)} template errors",
                data={"errors": template_errors, "count": template_count},
            )
        )
    else:
        checks.append(
            DoctorCheck(
                name="templates",
                status="ok",
                details=f"{template_count} templates validated",
            )
        )

    # Tool availability
    def _has_module(name: str) -> bool:
        try:
            __import__(name)
            return True
        except Exception:
            return False

    checks.append(
        DoctorCheck(
            name="browser_use",
            status="ok" if _has_module("browser_use") else "warn",
            details="browser_use available" if _has_module("browser_use") else "browser_use not installed",
        )
    )
    checks.append(
        DoctorCheck(
            name="playwright",
            status="ok" if _has_module("playwright") else "warn",
            details="playwright available" if _has_module("playwright") else "playwright not installed",
        )
    )
    checks.append(
        DoctorCheck(
            name="mcp",
            status="ok" if _has_module("mcp") else "warn",
            details="mcp available" if _has_module("mcp") else "mcp not installed",
        )
    )

    repairs: list[RepairResult] = []

    if fix:
        for check in checks:
            if check.status != "warn":
                continue

            if check.name == "workspace_root":
                try:
                    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
                    check.status = "ok"
                    check.details = f"{WORKSPACE_ROOT} (created)"
                    repairs.append(RepairResult(check.name, True, "Created workspace directory"))
                except OSError as exc:
                    repairs.append(RepairResult(check.name, False, str(exc)))

            elif check.name == "logs_dir":
                logs_path = root / LOGS_DIR
                try:
                    logs_path.mkdir(parents=True, exist_ok=True)
                    check.status = "ok"
                    check.details = f"{logs_path} (created)"
                    repairs.append(RepairResult(check.name, True, "Created logs directory"))
                except OSError as exc:
                    repairs.append(RepairResult(check.name, False, str(exc)))

            elif check.name == "projects_db":
                db_path_fix = root / "projects.db"
                try:
                    # Create a minimal projects.db with the expected schema
                    with sqlite3.connect(str(db_path_fix)) as conn:
                        conn.execute(
                            "CREATE TABLE IF NOT EXISTS projects ("
                            "  id TEXT PRIMARY KEY,"
                            "  name TEXT NOT NULL,"
                            "  description TEXT DEFAULT '',"
                            "  status TEXT DEFAULT 'active',"
                            "  created_at TEXT DEFAULT (datetime('now')),"
                            "  updated_at TEXT DEFAULT (datetime('now'))"
                            ")"
                        )
                        conn.commit()
                    check.status = "ok"
                    check.details = f"{db_path_fix} (created)"
                    repairs.append(RepairResult(check.name, True, "Created projects.db with schema"))
                except Exception as exc:
                    repairs.append(RepairResult(check.name, False, str(exc)))

            elif check.name == "browser_use":
                repairs.append(
                    RepairResult(
                        check.name,
                        False,
                        "Run: pip install browser-use",
                    )
                )

            elif check.name == "playwright":
                repairs.append(
                    RepairResult(
                        check.name,
                        False,
                        "Run: pip install playwright && playwright install",
                    )
                )

            elif check.name == "mcp":
                repairs.append(
                    RepairResult(
                        check.name,
                        False,
                        "Run: pip install 'mcp>=1.5'",
                    )
                )

    return DoctorReport(checks=checks, repairs=repairs if repairs else None)


# ---------------------------------------------------------------------------
# Plan -> Implement
# ---------------------------------------------------------------------------


_BULLET_RE = re.compile(r"^\s*(?:-|\*|\d+\.)\s+(.*)$")
_HEADING_RE = re.compile(r"^\s*#{1,6}\s+(.*)$")


def extract_steps(text: str) -> List[str]:
    """Extract task steps from markdown-ish text."""
    steps: List[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _BULLET_RE.match(line)
        if m:
            steps.append(m.group(1).strip())
            continue
    if steps:
        return steps
    for line in text.splitlines():
        m = _HEADING_RE.match(line)
        if m:
            steps.append(m.group(1).strip())
    return steps


def _slugify(text: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text.strip().lower()).strip("_")
    return text[:40] if text else ""


def build_plan_from_spec(spec_text: str, task_type: str = "chat") -> List[Dict[str, Any]]:
    """Build a JSON plan list from spec content."""
    steps = extract_steps(spec_text)
    if not steps:
        snippet = spec_text.strip().splitlines()[0][:120] if spec_text.strip() else "spec_task"
        steps = [snippet]

    plan: List[Dict[str, Any]] = []
    seen_names: set[str] = set()
    for i, step in enumerate(steps, start=1):
        base = _slugify(step) or f"step_{i}"
        name = base
        suffix = 1
        while name in seen_names:
            suffix += 1
            name = f"{base}_{suffix}"
        seen_names.add(name)
        plan.append(
            {
                "name": name,
                "type": task_type,
                "description": step,
                "prompt": step,
            }
        )
    return plan


# ---------------------------------------------------------------------------
# Template updates / upgrade
# ---------------------------------------------------------------------------


def compare_versions(a: str, b: str) -> int:
    """Compare semantic versions without external dependencies."""
    def _normalize(v: str) -> Tuple[int, int, int, str]:
        main, *_ = v.split("-", 1)
        parts = main.split(".")
        nums = [int(p) if p.isdigit() else 0 for p in parts[:3]]
        while len(nums) < 3:
            nums.append(0)
        return nums[0], nums[1], nums[2], v

    na = _normalize(a)
    nb = _normalize(b)
    if na[:3] < nb[:3]:
        return -1
    if na[:3] > nb[:3]:
        return 1
    return 0


def _local_templates(builtin_dir: Path) -> List[Dict[str, str]]:
    parser = TemplateParser()
    templates: List[Dict[str, str]] = []
    for yaml_file in builtin_dir.glob("*.yaml"):
        try:
            template = parser.parse_file(yaml_file)
            templates.append(
                {
                    "id": template.name.replace(" ", "-").lower(),
                    "name": template.name,
                    "version": template.version,
                    "path": str(yaml_file),
                }
            )
        except Exception:
            continue
    return templates


def check_template_updates(
    root: Path,
    marketplace_url: Optional[str] = None,
    template_filter: Optional[str] = None,
) -> Dict[str, Any]:
    """Check marketplace for newer template versions."""
    market = TemplateMarketplace(marketplace_url=marketplace_url)
    builtin_dir = root / "weebot" / "templates" / "builtin"
    local = _local_templates(builtin_dir)

    if template_filter:
        local = [t for t in local if t["id"] == template_filter or t["name"] == template_filter]

    if not market._is_online():
        return {"status": "offline", "updates": [], "checked": len(local)}

    remote_list = market.search(query="")
    remote_map = {t.id: t for t in remote_list}

    updates: List[Dict[str, str]] = []
    for tmpl in local:
        remote = remote_map.get(tmpl["id"])
        if not remote:
            continue
        if compare_versions(tmpl["version"], remote.version) < 0:
            updates.append(
                {
                    "id": tmpl["id"],
                    "name": tmpl["name"],
                    "local_version": tmpl["version"],
                    "remote_version": remote.version,
                }
            )

    return {"status": "online", "updates": updates, "checked": len(local)}


def upgrade_templates(
    root: Path,
    marketplace_url: Optional[str] = None,
    template_filter: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Upgrade templates to latest from marketplace."""
    market = TemplateMarketplace(marketplace_url=marketplace_url)
    result = check_template_updates(root, marketplace_url, template_filter)

    if result["status"] != "online":
        return result

    upgraded: List[str] = []
    failed: List[str] = []
    if not dry_run:
        for item in result["updates"]:
            try:
                market.download(item["id"], version=item["remote_version"])
                upgraded.append(item["id"])
            except Exception:
                failed.append(item["id"])

    return {
        "status": result["status"],
        "checked": result["checked"],
        "updates": result["updates"],
        "upgraded": upgraded,
        "failed": failed,
        "dry_run": dry_run,
    }
