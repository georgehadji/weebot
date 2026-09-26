"""Each provider's default model must be one that provider serves.

MODEL_FACTORY_ANTHROPIC had become "qwen/qwen3.8-max", so AnthropicAdapter's
default request asked api.anthropic.com for a qwen model; MODEL_FACTORY_OPENAI
had become "moonshotai/kimi-k2.6", which BrowserTool's last-resort ChatOpenAI
sent to api.openai.com. Both drifted in commits about cascade ordering.
"""

from weebot.config.model_catalog import MODELS
from weebot.config.model_refs import MODEL_FACTORY_ANTHROPIC, MODEL_FACTORY_OPENAI


def test_anthropic_default_is_a_live_anthropic_model():
    assert "/" not in MODEL_FACTORY_ANTHROPIC  # sent as-is to Anthropic's API
    assert f"anthropic/{MODEL_FACTORY_ANTHROPIC}" in MODELS


def test_openai_default_is_a_live_openai_model():
    assert "/" not in MODEL_FACTORY_OPENAI  # sent as-is to api.openai.com
    assert f"openai/{MODEL_FACTORY_OPENAI}" in MODELS
