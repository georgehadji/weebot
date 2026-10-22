"""F14: xai_api_key counts as a provider key.

Fixed in W1.3 with one `_PROVIDER_KEYS` table read by both methods; see
tasks/icm_fix_plan.md.
"""

import pytest

from weebot.config.settings import WeebotSettings


def test_xai_key_alone_passes_validation():
    WeebotSettings(xai_api_key="xai-test").validate_at_least_one_key()


def test_xai_key_listed_as_provider():
    assert "xai" in WeebotSettings(xai_api_key="xai-test").available_providers()


def test_no_key_error_names_every_provider_env_var():
    with pytest.raises(ValueError) as exc:
        WeebotSettings().validate_at_least_one_key()
    for env_name in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "XAI_API_KEY"):
        assert env_name in str(exc.value)
