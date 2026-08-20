"""ScraperTool — Exposes the production-grade Spacescraper web intelligence system as an agent tool."""

from __future__ import annotations

import logging
from typing import Any
import httpx
import sys
import asyncio

from pydantic import PrivateAttr

from weebot.tools.base import BaseTool, ToolResult
from weebot.config.tool_config import ToolConfig, resolve_setting

logger = logging.getLogger(__name__)


class ScraperTool(BaseTool):
    """Execute enterprise web intelligence crawls using Spacescraper.

    Uses Spacescraper with local headless CLI execution as the default,
    falling back to headless Web API, and finally automated docker-compose cluster initiation.
    """

    _tool_config: ToolConfig | None = PrivateAttr(default=None)

    def set_config(self, config: ToolConfig) -> None:
        """Inject a ToolConfig (Spacescraper endpoint/creds) via the tool registry."""
        self._tool_config = config

    name: str = "spacescraper"
    description: str = (
        "Execute enterprise web crawling and structured intelligence extraction using Spacescraper. "
        "Supports targeted portal scraping, custom declarative overlay parsing, fuzzy deduplication, "
        "and AI-powered entity classification."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The target website URL to scrape (e.g., 'https://ted.europa.eu').",
            },
            "site": {
                "type": "string",
                "description": "Site-specific extraction strategy identifier (e.g., 'esa_emits', 'nato_nspa', 'sam_gov', 'generic').",
                "default": "generic",
            },
            "overlay": {
                "type": "object",
                "description": "Optional custom JSON declarative field mappings for custom layout parsing.",
                "default": None,
            },
        },
        "required": ["url"],
    }

    async def execute(
        self, url: str, site: str = "generic", overlay: dict | None = None, **kwargs: Any
    ) -> ToolResult:
        api_url = resolve_setting(
            self._tool_config, "scraper_api_url", "SCRAPER_API_URL", "http://localhost:8000"
        ).rstrip("/")
        api_key = resolve_setting(self._tool_config, "scraper_api_key", "SCRAPER_API_KEY")
        scraper_dir = resolve_setting(
            self._tool_config, "scraper_dir", "SCRAPER_DIR", "E:\\Documents\\Vibe-Coding\\Scraper"
        )

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        # Setup Web API payload
        payload = {"url": url, "target_site": site, "overlay": overlay or {}}

        # Subprocess CLI command runner (Method 1)
        async def _run_cli() -> str:
            cli_args = [sys.executable, "submit_url.py", url, "--site", site]
            logger.info("Executing Method 1 (Default Headless CLI) in %s", scraper_dir)
            logger.info("CLI command: %s", " ".join(cli_args))

            process = await asyncio.create_subprocess_exec(
                *cli_args,
                cwd=scraper_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                err_msg = (
                    stderr.decode(errors="ignore").strip() or stdout.decode(errors="ignore").strip()
                )
                raise RuntimeError(f"CLI submission exit code {process.returncode}: {err_msg}")

            return stdout.decode(errors="ignore").strip()

        # Web API request runner (Method 2)
        async def _run_api() -> dict:
            logger.info(
                "Executing Method 2 (Fallback Headless API) POST request to %s/jobs", api_url
            )
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(f"{api_url}/jobs", json=payload, headers=headers)
                resp.raise_for_status()
                return resp.json()

        # Docker-Compose Restarter (Method 3)
        async def _run_docker_compose_up() -> None:
            logger.info(
                "Executing Method 3 (Docker Fallback) to spin up the containerized cluster..."
            )
            process = await asyncio.create_subprocess_exec(
                "docker-compose",
                "up",
                "-d",
                cwd=scraper_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            if process.returncode != 0:
                err_msg = (
                    stderr.decode(errors="ignore").strip() or stdout.decode(errors="ignore").strip()
                )
                raise RuntimeError(f"docker-compose failed: {err_msg}")

            logger.info(
                "Docker-compose services successfully initiated. Waiting 5s for broker to pre-warm..."
            )
            await asyncio.sleep(5.0)

        # Execution sequence with cascading fallback triggers
        try:
            # 1. Try Method 1: Headless CLI (Default)
            try:
                cli_output = await _run_cli()
                summary = (
                    f"Spacescraper successfully dispatched via local CLI (Method 1):\n\n"
                    f"{cli_output}\n"
                )
                return ToolResult.success_result(
                    output=summary,
                    data={"method": "cli", "url": url, "site": site, "cli_output": cli_output},
                )
            except Exception as cli_exc:
                logger.warning(
                    "Method 1 (CLI) failed: %s. Transitioning to Method 2 (API Fallback)...",
                    cli_exc,
                )

                # 2. Try Method 2: Headless Web API (Fallback 1)
                try:
                    api_resp = await _run_api()
                    summary = (
                        f"Spacescraper successfully dispatched via REST API (Method 2):\n\n"
                        f"Status: {api_resp.get('status', 'enqueued')}\n"
                        f"Job ID: {api_resp.get('job_id', 'unknown')}\n"
                    )
                    return ToolResult.success_result(
                        output=summary,
                        data={"method": "api", "url": url, "site": site, "api_response": api_resp},
                    )
                except Exception as api_exc:
                    logger.warning(
                        "Method 2 (API) failed: %s. Transitioning to Method 3 (Docker Fallback)...",
                        api_exc,
                    )

                    # 3. Try Method 3: Self-healing via Docker-compose up + retry API
                    try:
                        await _run_docker_compose_up()
                        # Retry the API call since the cluster is now initiated!
                        api_resp = await _run_api()
                        summary = (
                            f"Spacescraper successfully initiated and enqueued after launching Docker cluster (Method 3):\n\n"
                            f"Status: {api_resp.get('status', 'enqueued')}\n"
                            f"Job ID: {api_resp.get('job_id', 'unknown')}\n"
                        )
                        return ToolResult.success_result(
                            output=summary,
                            data={
                                "method": "docker_compose",
                                "url": url,
                                "site": site,
                                "api_response": api_resp,
                            },
                        )
                    except Exception as docker_exc:
                        logger.error(
                            "All Spacescraper submission methods failed. Method 3 error: %s",
                            docker_exc,
                        )
                        return ToolResult.error_result(
                            f"Spacescraper execution failed across all 3 modes.\n"
                            f"CLI Error: {cli_exc}\n"
                            f"API Error: {api_exc}\n"
                            f"Docker Retry Error: {docker_exc}"
                        )

        except Exception as exc:
            logger.error("Scraper execution crashed with unhandled exception: %s", exc)
            return ToolResult.error_result(f"Spacescraper execution crashed: {exc}")
