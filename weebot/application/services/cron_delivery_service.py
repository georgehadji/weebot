"""Cron Delivery Service — delivers cron agent results to configured targets.

Supports delivery to Telegram, Discord, Slack, file paths, or no delivery
(just logging).
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from weebot.domain.models.cron_job import CronJobRecord, DeliveryTargetType

logger = logging.getLogger(__name__)


class CronDeliveryService:
    """Delivers cron agent results to configured targets."""

    async def deliver(
        self,
        job: CronJobRecord,
        result_text: str,
    ) -> bool:
        """Deliver *result_text* according to the job's delivery target.

        Args:
            job: The cron job that produced the result.
            result_text: The text to deliver.

        Returns:
            True if delivery succeeded (or was a no-op).
        """
        target = job.deliver_to
        if target is None or target.type == DeliveryTargetType.NONE:
            logger.info("Cron job %s: no delivery target — result logged only", job.id)
            return True

        try:
            if target.type == DeliveryTargetType.FILE:
                return await self._deliver_to_file(job, result_text, target.destination)
            elif target.type == DeliveryTargetType.TELEGRAM:
                return await self._deliver_to_telegram(job, result_text, target.destination)
            elif target.type == DeliveryTargetType.DISCORD:
                return await self._deliver_to_discord(job, result_text, target.destination)
            elif target.type == DeliveryTargetType.SLACK:
                return await self._deliver_to_slack(job, result_text, target.destination)
            else:
                logger.warning("Unknown delivery target type: %s", target.type)
                return False
        except Exception as exc:
            logger.error("Delivery failed for cron job %s: %s", job.id, exc)
            return False

    async def _deliver_to_file(self, job: CronJobRecord, text: str, path: str | None) -> bool:
        """Write result to a file."""
        output_path = Path(path or f"cron-output/{job.id}.txt")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(output_path.write_text, text, encoding="utf-8")
        logger.info("Cron job %s: delivered to %s", job.id, output_path)
        return True

    async def _deliver_to_telegram(self, job: CronJobRecord, text: str, chat_id: str | None) -> bool:
        """Send result to a Telegram chat."""
        if not chat_id:
            logger.warning("Cron job %s: no Telegram chat_id configured", job.id)
            return False

        from weebot.config.settings import WeebotSettings
        settings = WeebotSettings()
        token = settings.telegram_bot_token
        if not token:
            logger.warning("Cron job %s: no TELEGRAM_BOT_TOKEN configured", job.id)
            return False

        import aiohttp
        api = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text[:4096]}
        async with aiohttp.ClientSession() as session:
            async with session.post(api, json=payload) as resp:
                return resp.status == 200

    async def _deliver_to_discord(self, job: CronJobRecord, text: str, channel_id: str | None) -> bool:
        """Send result to a Discord channel."""
        if not channel_id:
            logger.warning("Cron job %s: no Discord channel_id configured", job.id)
            return False

        from weebot.config.settings import WeebotSettings
        settings = WeebotSettings()
        token = settings.discord_bot_token
        if not token:
            logger.warning("Cron job %s: no DISCORD_BOT_TOKEN configured", job.id)
            return False

        import aiohttp
        url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
        headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
        payload = {"content": text[:2000]}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                return resp.status == 200

    async def _deliver_to_slack(self, job: CronJobRecord, text: str, webhook_url: str | None) -> bool:
        """Send result to a Slack webhook."""
        if not webhook_url:
            logger.warning("Cron job %s: no Slack webhook URL configured", job.id)
            return False

        import aiohttp
        payload = {"text": text[:4000]}
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=payload) as resp:
                return resp.status == 200
