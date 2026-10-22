"""Python run from a shell is classified like python_execute (found in plan B2c).

W3.8 classified `python_execute` code that imports a network library, but the
same code run as `python -c "..."` through bash or powershell matched neither
the shell download patterns nor the line-anchored Python pattern. A real web
run showed the planner choosing exactly that form, so the egress gate never saw
it.
"""

from __future__ import annotations

import pytest

from weebot.core.egress_guard import EgressGuard

_URLLIB = (
    "python -c \"import urllib.request; "
    "print(urllib.request.urlopen('https://httpbin.org/get').status)\""
)


@pytest.mark.parametrize(
    ("tool", "command", "recipient"),
    [
        ("bash", _URLLIB, "httpbin.org"),
        ("powershell", _URLLIB, "httpbin.org"),
        ("bash", "python3 -c 'import requests; requests.post(\"https://api.x.test/a\")'",
         "api.x.test"),
        ("powershell", "py -c \"from httpx import post; post('https://h.test')\"", "h.test"),
        ("bash", "python.exe -c \"import socket; socket.create_connection(('h', 80))\"", None),
    ],
)
def test_shell_python_with_a_network_import_is_egress(tool, command, recipient):
    found, is_egress = EgressGuard()._detect_egress(tool, {"command": command})
    assert is_egress
    assert found == recipient


@pytest.mark.parametrize(
    "command",
    [
        "python -c \"import json; print(json.dumps({}))\"",
        "python script.py",
        "pip list",
        "echo import requests",
    ],
)
def test_shell_python_without_network_is_not_egress(command):
    assert EgressGuard()._detect_egress("bash", {"command": command}) == (None, False)
