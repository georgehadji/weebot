"""ReasonerTool — Exposes the production-grade Reasoner service as an agent tool."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
import httpx

from pydantic import PrivateAttr

from weebot.tools.base import BaseTool, ToolResult
from weebot.config.tool_config import ToolConfig, resolve_setting

logger = logging.getLogger(__name__)


class ReasonerTool(BaseTool):
    """Execute deep reasoning workflows using the Reasoner engine.

    Uses Reasoner at http://localhost:8003 to execute complex reasoning pipelines
    with various models, multi-perspective debate, and synthesis.
    """

    _tool_config: Optional[ToolConfig] = PrivateAttr(default=None)

    def set_config(self, config: ToolConfig) -> None:
        """Inject a ToolConfig (Reasoner endpoint/creds) via the tool registry."""
        self._tool_config = config

    name: str = "reasoner"
    description: str = (
        "Execute a structured reasoning pipeline using Reasoner. "
        "Best for complex analysis, strategic decision making, risk assessment, "
        "or deep domain research where high reliability, critique, and synthesis "
        "are required."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "problem": {
                "type": "string",
                "description": "The complex question, decision, or prompt to solve.",
            },
            "preset": {
                "type": "string",
                "description": (
                    "Reasoning preset to use (e.g. 'research-premium', 'research-budget', "
                    "'debate-budget', 'debate-premium', 'socratic-budget', 'socratic-premium')."
                ),
                "default": "research-budget",
            },
            "web_search": {
                "type": "boolean",
                "description": "Enable live web search for retrieving up-to-date facts.",
                "default": False,
            },
            "smart_search": {
                "type": "boolean",
                "description": "Enable agentic multi-query search if web_search is enabled.",
                "default": True,
            },
            "top_k": {
                "type": "integer",
                "description": "Number of top perspectives to synthesize (default: 2).",
                "default": 2,
            },
            "sequential": {
                "type": "boolean",
                "description": "Force sequential perspective evaluation to avoid rate limits.",
                "default": False,
            },
            "no_cache": {
                "type": "boolean",
                "description": "Bypass local search and response cache.",
                "default": False,
            },
            "force_pipeline": {
                "type": "boolean",
                "description": "Force execution of all pipeline phases regardless of quick answers.",
                "default": False,
            },
            "enhance_prompt": {
                "type": "boolean",
                "description": "Let Reasoner optimize your prompt before execution.",
                "default": False,
            },
            "expert": {
                "type": "boolean",
                "description": "Enable high-end reasoning expert mode.",
                "default": False,
            },
            "source_type": {
                "type": "string",
                "description": "Limit web search sources: 'general', 'academic', 'news', 'code'.",
                "default": "general",
            },
            "domain": {
                "type": "string",
                "description": "Restrict web search to a specific domain (e.g. 'wikipedia.org').",
                "default": None,
            },
        },
        "required": ["problem"],
    }

    async def execute(
        self,
        problem: str,
        preset: str = "research-budget",
        web_search: bool = False,
        smart_search: bool = True,
        top_k: int = 2,
        sequential: bool = False,
        no_cache: bool = False,
        force_pipeline: bool = False,
        enhance_prompt: bool = False,
        expert: bool = False,
        source_type: str = "general",
        domain: Optional[str] = None,
        **kwargs: Any,
    ) -> ToolResult:
        api_url = resolve_setting(
            self._tool_config, "reasoner_api_url", "REASONER_API_URL", "http://localhost:8003"
        ).rstrip("/")
        api_key = resolve_setting(self._tool_config, "reasoner_api_key", "REASONER_API_KEY")
        reasoner_dir = resolve_setting(
            self._tool_config, "reasoner_dir", "REASONER_DIR", "E:\\Documents\\Vibe-Coding\\Reasoner"
        )

        headers = {
            "Content-Type": "application/json",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        # ── Step 1: Discover Tool Contract ──
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                contract_resp = await client.get(f"{api_url}/api/agent/tools", headers=headers)
                if contract_resp.status_code == 200:
                    logger.info("Successfully discovered Reasoner contract from /api/agent/tools")
                else:
                    contract_resp = await client.get(f"{api_url}/openapi.json", headers=headers)
                    if contract_resp.status_code == 200:
                        logger.info("Successfully discovered Reasoner contract from /openapi.json")
        except Exception as exc:
            logger.debug("Failed to discover Reasoner tool contract: %s. Continuing anyway.", exc)

        # ── Setup request payload ──
        payload = {
            "problem": problem,
            "preset": preset,
            "top_k": top_k,
            "sequential": sequential,
            "no_cache": no_cache,
            "force_pipeline": force_pipeline,
            "enhance_prompt": enhance_prompt,
            "expert": expert,
            "web_search": web_search,
            "smart_search": smart_search,
            "source_type": source_type,
            "domain": domain,
            "attachments": [],
            "file_ids": [],
        }

        # ── Call POST /api/agent/run/sync ──
        async def _call_reasoner(req_payload: dict) -> dict:
            async with httpx.AsyncClient(timeout=180.0) as client:
                resp = await client.post(
                    f"{api_url}/api/agent/run/sync",
                    json=req_payload,
                    headers=headers,
                )
                resp.raise_for_status()
                return resp.json()

        try:
            # Nested try/except for the API call and CLI fallback
            try:
                logger.info("Calling Reasoner POST /api/agent/run/sync with preset=%s", preset)
                result = await _call_reasoner(payload)
            except Exception as api_exc:
                logger.warning("Reasoner API call failed: %s. Falling back to headless CLI...", api_exc)
                try:
                    import sys
                    import tempfile
                    import json
                    import asyncio
                    from pathlib import Path

                    # Construct CLI arguments
                    cli_args = [
                        sys.executable,
                        "main.py",
                        "--problem", problem,
                        "--preset", preset,
                        "--top-k", str(top_k),
                    ]
                    if sequential:
                        cli_args.append("--sequential")
                    if no_cache:
                        cli_args.append("--no-cache")
                    if force_pipeline:
                        cli_args.append("--force-pipeline")
                    if enhance_prompt:
                        cli_args.append("--enhance-prompt")
                    if web_search:
                        cli_args.append("--web-search")
                    if source_type and source_type != "general":
                        cli_args.extend(["--source-type", source_type])
                    if domain:
                        cli_args.extend(["--domain", domain])

                    # Create temporary file path to receive the output
                    with tempfile.TemporaryDirectory() as tmpdir:
                        temp_json_path = Path(tmpdir) / "reasoner_headless_output.json"
                        cli_args.extend(["--output", str(temp_json_path)])
                        
                        logger.info("Falling back to headless CLI execution of Reasoner in %s", reasoner_dir)
                        logger.info("CLI command: %s", " ".join(cli_args))
                        
                        # Execute subprocess asynchronously
                        process = await asyncio.create_subprocess_exec(
                            *cli_args,
                            cwd=reasoner_dir,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                        )
                        stdout, stderr = await process.communicate()
                        
                        if process.returncode != 0:
                            err_msg = stderr.decode(errors="ignore").strip() or stdout.decode(errors="ignore").strip()
                            logger.error("Reasoner CLI execution failed with exit code %d: %s", process.returncode, err_msg)
                            raise RuntimeError(f"Reasoner CLI execution failed with exit code {process.returncode}: {err_msg}")
                        
                        # Read back the saved JSON results
                        if not temp_json_path.exists():
                            logger.error("Reasoner CLI completed but output file was not created: %s", temp_json_path)
                            raise FileNotFoundError(f"Reasoner CLI output file was not created at {temp_json_path}")
                            
                        with open(temp_json_path, encoding="utf-8") as f:
                            result = json.load(f)
                except Exception as cli_exc:
                    logger.error("Reasoner CLI fallback also failed: %s", cli_exc)
                    return ToolResult.error_result(
                        f"Reasoner execution failed. API error: {api_exc}. CLI error: {cli_exc}"
                    )
            
            # ── Handle response ──
            synthesis = result.get("synthesis")
            if not synthesis:
                logger.warning("Reasoner response missing synthesis answer. Retrying with web_search=True...")
                # Treat missing synthesis as a failed run and retry with web_search=True
                payload["web_search"] = True
                result = await _call_reasoner(payload)
                synthesis = result.get("synthesis")
                if not synthesis:
                    return ToolResult.error_result("Reasoner execution succeeded but returned no synthesis final answer.")

            citations = result.get("citations", [])
            errors = result.get("errors", [])
            models_used = result.get("models_used", [])

            # Construct summary
            summary = f"Reasoner final answer:\n\n{synthesis}\n\n"
            if citations:
                summary += f"Citations:\n" + "\n".join(f"- {c}" for c in citations) + "\n\n"
            if models_used:
                summary += f"Models used: {', '.join(models_used)}\n"
            if errors:
                summary += f"Warnings/Errors encountered: {', '.join(errors)}\n"

            return ToolResult.success_result(
                output=summary,
                data={
                    "synthesis": synthesis,
                    "citations": citations,
                    "models_used": models_used,
                    "errors": errors,
                    "raw_response": result,
                },
            )

        except Exception as exc:
            logger.error("Reasoner execution failed: %s", exc)
            return ToolResult.error_result(f"Reasoner execution failed: {exc}")
