"""BerbTool — Exposes the production-grade Berb academic research platform as an agent tool."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
import httpx
import sys
import asyncio
from pathlib import Path

from pydantic import PrivateAttr

from weebot.tools.base import BaseTool, ToolResult
from weebot.config.tool_config import ToolConfig, resolve_setting

logger = logging.getLogger(__name__)


class BerbTool(BaseTool):
    """Execute autonomous academic research using the Berb platform.

    Uses Berb at http://localhost:8004 to run a 23-stage academic research pipeline
    from a single paper topic, or falls back to headless CLI execution.
    """

    _tool_config: Optional[ToolConfig] = PrivateAttr(default=None)

    def set_config(self, config: ToolConfig) -> None:
        """Inject a ToolConfig (Berb endpoint/creds) via the tool registry."""
        self._tool_config = config

    name: str = "berb"
    description: str = (
        "Execute a 23-stage autonomous academic research pipeline using Berb. "
        "Best for literature reviews, hypothesis testing, experiment designs, "
        "and drafting conference-ready papers or academic deepdives."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "description": "The research idea, topic, or paper concept to execute.",
            },
            "auto_approve": {
                "type": "boolean",
                "description": "Run without gate stops (highly recommended for agent delegation).",
                "default": True,
            },
            "from_stage": {
                "type": "string",
                "description": "Resume from a specific stage (e.g., 'PAPER_OUTLINE', 'EXPERIMENT').",
                "default": None,
            },
        },
        "required": ["topic"],
    }

    async def execute(
        self,
        topic: str,
        auto_approve: bool = True,
        from_stage: Optional[str] = None,
        **kwargs: Any,
    ) -> ToolResult:
        api_url = resolve_setting(
            self._tool_config, "berb_api_url", "BERB_API_URL", "http://localhost:8004"
        ).rstrip("/")
        api_key = resolve_setting(self._tool_config, "berb_api_key", "BERB_API_KEY")
        berb_dir = resolve_setting(
            self._tool_config, "berb_dir", "BERB_DIR", "E:\\Documents\\Vibe-Coding\\Berb"
        )

        headers = {
            "Content-Type": "application/json",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "topic": topic,
            "auto_approve": auto_approve,
            "from_stage": from_stage,
        }

        # ── Call POST /api/research/run ──
        async def _call_berb(req_payload: dict) -> dict:
            async with httpx.AsyncClient(timeout=300.0) as client:
                resp = await client.post(
                    f"{api_url}/api/research/run",
                    json=req_payload,
                    headers=headers,
                )
                resp.raise_for_status()
                return resp.json()

        try:
            # Nested try/except with CLI (Method 1) as DEFAULT and API (Method 2) as FALLBACK
            try:
                # Construct CLI arguments: python -m berb run --topic "<topic>"
                cli_args = [
                    sys.executable,
                    "-m", "berb",
                    "run",
                    "--topic", topic,
                ]
                if auto_approve:
                    cli_args.append("--auto-approve")
                if from_stage:
                    cli_args.extend(["--from-stage", from_stage])

                logger.info("Executing default headless CLI run of Berb in %s", berb_dir)
                logger.info("CLI command: %s", " ".join(cli_args))

                # Execute subprocess asynchronously
                process = await asyncio.create_subprocess_exec(
                    *cli_args,
                    cwd=berb_dir,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await process.communicate()

                if process.returncode != 0:
                    err_msg = stderr.decode(errors="ignore").strip() or stdout.decode(errors="ignore").strip()
                    logger.error("Berb CLI execution failed with exit code %d: %s", process.returncode, err_msg)
                    raise RuntimeError(f"Berb CLI execution failed with exit code {process.returncode}: {err_msg}")

                # CLI logs standard output
                logs_out = stdout.decode(errors="ignore").strip()
                result = {
                    "status": "success",
                    "message": f"Successfully completed academic research run for topic: '{topic}'",
                    "summary": logs_out[-2000:] if len(logs_out) > 2000 else logs_out,
                    "artifacts_dir": str(Path(berb_dir) / "artifacts"),
                }
            except Exception as cli_exc:
                logger.warning("Berb CLI execution failed: %s. Falling back to API...", cli_exc)
                try:
                    logger.info("Calling Berb API POST /api/research/run for topic: %s", topic)
                    result = await _call_berb(payload)
                except Exception as api_exc:
                    logger.error("Berb API fallback also failed: %s", api_exc)
                    return ToolResult.error_result(
                        f"Berb execution failed. CLI error: {cli_exc}. API error: {api_exc}"
                    )

            # ── Handle response ──
            summary_text = result.get("summary") or result.get("message") or "Berb academic research run completed successfully."
            artifacts_dir = result.get("artifacts_dir") or str(Path(berb_dir) / "artifacts")

            summary = (
                f"Berb Academic Research Output:\n\n"
                f"{summary_text}\n\n"
                f"Artifacts and papers are generated at: {artifacts_dir}\n"
            )

            return ToolResult.success_result(
                output=summary,
                data={
                    "topic": topic,
                    "summary": summary_text,
                    "artifacts_dir": artifacts_dir,
                    "raw_response": result,
                },
            )

        except Exception as exc:
            logger.error("Berb execution failed: %s", exc)
            return ToolResult.error_result(f"Berb execution failed: {exc}")
