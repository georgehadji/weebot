"""FilePatchStore — self-improvement patches held as JSON files, one per patch.

Proposals wait here as pending until ``improve apply``; the applied and reverted
flags are written back, so ``improve list`` shows each patch's state.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from weebot.domain.models.self_improvement import SelfImprovementPatch


class FilePatchStore:
    """Patches under *directory*, named by patch id."""

    def __init__(self, directory: Path) -> None:
        self._dir = Path(directory)

    def _path(self, patch_id: str) -> Path:
        if not patch_id or any(c in patch_id for c in "/\\.:"):
            raise ValueError(f"not a patch id: {patch_id!r}")
        return self._dir / f"{patch_id}.json"

    async def save(self, patch: SelfImprovementPatch) -> None:
        def _write() -> None:
            self._dir.mkdir(parents=True, exist_ok=True)
            self._path(patch.id).write_text(patch.model_dump_json(indent=2), encoding="utf-8")

        await asyncio.to_thread(_write)

    async def get(self, patch_id: str) -> SelfImprovementPatch | None:
        path = self._path(patch_id)
        if not path.exists():
            return None
        text = await asyncio.to_thread(path.read_text, encoding="utf-8")
        return SelfImprovementPatch.model_validate_json(text)

    async def list(self) -> list[SelfImprovementPatch]:
        if not self._dir.exists():
            return []

        def _read() -> list[SelfImprovementPatch]:
            patches = [
                SelfImprovementPatch.model_validate_json(p.read_text(encoding="utf-8"))
                for p in self._dir.glob("*.json")
            ]
            return sorted(patches, key=lambda p: p.created_at, reverse=True)

        return await asyncio.to_thread(_read)
