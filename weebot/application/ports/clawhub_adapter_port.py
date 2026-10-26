"""ClawHubAdapterPort — the application's contract for reading the ClawHub skills repo.

`ClawHubImporter` annotated its git adapter with the concrete
`weebot.infrastructure.adapters.clawhub_adapter.ClawHubGitAdapter`, and defaulted to
constructing one, which is the edge `app-no-infrastructure` forbids (WB-01).

The abstraction was already in the design: `clawhub_adapter.py` exists so that this
importer "does not import ``subprocess`` directly". This port is that intention stated
where the application layer can see it. Structural (`Protocol`) so the adapter satisfies
it as-is; two members is the whole surface the importer uses.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class ClawHubAdapterPort(Protocol):
    """Where the ClawHub skills repo is, and how to refresh it."""

    @property
    def repo_path(self) -> Path:
        """Local checkout of the skills repository."""
        ...

    def clone_or_update(self) -> None:
        """Clone the repo if absent, otherwise pull the latest revision."""
        ...
