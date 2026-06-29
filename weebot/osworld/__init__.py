"""OSWorld integration package for weebot.

Provides:
- WeebotOSWorldAgent: drop-in replacement for OSWorld's PromptAgent
- OSWorld-compatible action format translation
- Screenshot + a11y tree observation handling
- VLM-based action prediction loop
"""
from weebot.osworld.agent_adapter import WeebotOSWorldAgent

__all__ = ["WeebotOSWorldAgent"]
