"""DesignSystemTool — extract design tokens via npx skillui (no API key needed)."""
from __future__ import annotations
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from weebot.tools.base import BaseTool, ToolResult


class DesignSystemTool(BaseTool):
    name: str = "design_system"
    description: str = (
        "Extract a complete design system from any website, GitHub repo, or "
        "local directory. Returns colors, typography, spacing, animations, "
        "components, and screenshots as structured data. Uses skillui under "
        "the hood (npm package, installed on first use). "
        "Use this tool when you need to match a reference design or build "
        "UI that looks like an existing site."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "Website URL to extract design from (e.g. https://linear.app)",
            },
            "repo": {
                "type": "string",
                "description": "GitHub repo URL to clone and scan (alternative to url)",
            },
            "directory": {
                "type": "string",
                "description": "Local project path to scan (alternative to url)",
            },
            "name": {
                "type": "string",
                "description": "Override the output project name (default: derived from URL)",
            },
            "ultra": {
                "type": "boolean",
                "description": "Enable full cinematic extraction with screenshots and animations (uses Playwright, slower)",
                "default": False,
            },
        },
        "required": [],
    }

    async def execute(
        self,
        url: str = "",
        repo: str = "",
        directory: str = "",
        name: str = "",
        ultra: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        # Validate: exactly one input source
        sources = [s for s in (url, repo, directory) if s]
        if len(sources) != 1:
            return ToolResult.error_result(
                error="Provide exactly one of: url, repo, or directory"
            )

        # Build command
        cmd = self._build_cmd(url, repo, directory, name, ultra)

        # Run in tempdir so output doesn't pollute workspace
        with tempfile.TemporaryDirectory(prefix="weebot_design_") as tmpdir:
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    cwd=tmpdir,
                )
            except subprocess.TimeoutExpired:
                return ToolResult.error_result(
                    error="skillui timed out after 120s. Try without --ultra or for a smaller site."
                )
            except FileNotFoundError:
                return ToolResult.error_result(
                    error=(
                        "skillui not found. Install it with: "
                        "npm install -g skillui"
                    )
                )

            if result.returncode != 0:
                # Try to auto-install on first failure
                if "not found" in result.stderr.lower() or "enoent" in result.stderr.lower():
                    try:
                        install = subprocess.run(
                            "npm install -g skillui",
                            capture_output=True,
                            text=True,
                            timeout=60,
                            shell=True,
                        )
                        if install.returncode != 0:
                            return ToolResult.error_result(
                                error=f"Failed to install skillui: {install.stderr[:500]}"
                            )
                        # Retry after install
                        result = subprocess.run(
                            cmd,
                            capture_output=True,
                            text=True,
                            timeout=120,
                            cwd=tmpdir,
                        )
                        if result.returncode != 0:
                            return ToolResult.error_result(
                                error=f"skillui failed: {result.stderr[:1000]}"
                            )
                    except Exception as e:
                        return ToolResult.error_result(
                            error=f"skillui install/run failed: {e}"
                        )
                else:
                    return ToolResult.error_result(
                        error=f"skillui failed (exit {result.returncode}): {result.stderr[:1000]}"
                    )

            # Find output directory and parse tokens
            return self._parse_output(tmpdir, name or self._derive_name(url, repo, directory))

    def _build_cmd(
        self, url: str, repo: str, directory: str, name: str, ultra: bool
    ) -> list[str]:
        """Build skillui command as a list (no shell injection risk)."""
        parts = ["npx", "skillui"]
        if url:
            parts.extend(["--url", url])
        elif repo:
            parts.extend(["--repo", repo])
        else:
            parts.extend(["--dir", directory])
        if name:
            parts.extend(["--name", name])
        if ultra:
            parts.append("--mode")
            parts.append("ultra")
        parts.extend(["--out", "."])
        return parts

    def _derive_name(self, url: str, repo: str, directory: str) -> str:
        if url:
            return url.replace("https://", "").replace("http://", "").split("/")[0].replace(".", "-")
        if repo:
            return repo.rstrip("/").split("/")[-1].replace(".git", "")
        if directory:
            return Path(directory).name
        return "design"

    def _parse_output(self, tmpdir: str, name: str) -> ToolResult:
        """Find the output dir and extract structured data."""
        tmp = Path(tmpdir)
        design_dirs = list(tmp.glob(f"*{name}*")) or list(tmp.glob("*design*")) or [d for d in tmp.iterdir() if d.is_dir()]
        if not design_dirs:
            # skillui might have produced files directly in tmpdir
            design_dir = tmp
        else:
            design_dir = design_dirs[0]

        output = []
        data: dict[str, Any] = {}

        # Parse tokens
        tokens_dir = design_dir / "tokens"
        if tokens_dir.exists():
            for token_file in tokens_dir.glob("*.json"):
                try:
                    tokens = json.loads(token_file.read_text(encoding="utf-8"))
                    key = token_file.stem
                    data[key] = tokens
                    if isinstance(tokens, dict):
                        output.append(f"## {key}")
                        for k, v in tokens.items():
                            output.append(f"  {k}: {v}")
                except Exception:
                    pass

        # Read DESIGN.md
        design_md = design_dir / "DESIGN.md"
        if design_md.exists():
            content = design_md.read_text(encoding="utf-8")[:5000]
            output.insert(0, content)
            data["design_md"] = content

        # Read SKILL.md for agent context
        skill_md = design_dir / "SKILL.md"
        if skill_md.exists():
            data["skill_md"] = skill_md.read_text(encoding="utf-8")[:3000]

        # List screenshots
        screens_dir = design_dir / "screens"
        if screens_dir.exists():
            data["screenshots"] = []
            for img in screens_dir.rglob("*.png"):
                data["screenshots"].append(str(img.relative_to(design_dir)))

        return ToolResult.success_result(
            output="\n".join(output) if output else f"Design system extracted to {design_dir}",
            data=data,
        )
