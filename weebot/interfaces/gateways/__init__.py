"""Gateways module — external messaging platform adapters."""

from weebot.interfaces.gateways.base import GatewayAdapter, GatewayMessage, GatewayResponse
from weebot.interfaces.gateways.telegram import TelegramAdapter
from weebot.interfaces.gateways.slack import SlackAdapter
from weebot.interfaces.gateways.whatsapp import WhatsAppAdapter
from weebot.interfaces.gateways.signal import SignalAdapter
from weebot.interfaces.gateways.email import EmailAdapter

__all__ = [
    "GatewayAdapter",
    "GatewayMessage",
    "GatewayResponse",
    "TelegramAdapter",
    "SlackAdapter",
    "WhatsAppAdapter",
    "SignalAdapter",
    "EmailAdapter",
]
