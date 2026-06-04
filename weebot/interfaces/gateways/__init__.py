"""Gateways module — external messaging platform adapters."""
from weebot.interfaces.gateways.base import GatewayAdapter, GatewayMessage, GatewayResponse
from weebot.interfaces.gateways.telegram import TelegramAdapter
from weebot.interfaces.gateways.slack import SlackAdapter

__all__ = [
    "GatewayAdapter",
    "GatewayMessage",
    "GatewayResponse",
    "TelegramAdapter",
    "SlackAdapter",
]
