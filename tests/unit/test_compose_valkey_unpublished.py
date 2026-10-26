"""OPS-1 guard: the Valkey default password is safe only while no port is published.

Decision D5 of tasks/specs/arch_audit_2026_10_remediation_plan.md keeps
``${VALKEY_PASSWORD:-weebot_default}`` so ``docker compose up`` works without a
``.env``. That is acceptable only because ``weebot-valkey`` publishes nothing and
is reachable on the compose network alone. This test pins the thing that
contains the risk.
"""

from __future__ import annotations

import pathlib

import yaml

_COMPOSE = pathlib.Path(__file__).resolve().parents[2] / "docker-compose.yml"


def test_valkey_publishes_no_port():
    services = yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))["services"]
    ports = services["weebot-valkey"].get("ports") or []
    assert ports == [], (
        "OPS-1: weebot-valkey now publishes a port, and its password defaults to "
        "'weebot_default' (docker-compose.yml, ${VALKEY_PASSWORD:-weebot_default}). "
        "Either stop publishing the port, or make VALKEY_PASSWORD required first. "
        "See tasks/specs/arch_audit_2026_10_remediation_plan.md section 1.4 (decision D5)."
    )


def test_valkey_has_no_host_network_or_expose_to_other_hosts():
    service = yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))["services"]["weebot-valkey"]
    assert service.get("network_mode") != "host", "host networking publishes every port"
