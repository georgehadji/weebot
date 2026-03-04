"""Registry for agent personas with import/export utilities."""
from __future__ import annotations

import json
import shutil
import zipfile
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from weebot.agents.models import AgentPersona
from weebot.agents.parser import AgentPersonaParser


class AgentRegistry:
    """Manage persona definitions and registry storage."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.registry_dir = self.root / ".weebot" / "agents" / "registry"
        self.definitions_dir = self.root / ".weebot" / "agents" / "definitions"
        self.registry_dir.mkdir(parents=True, exist_ok=True)
        self.definitions_dir.mkdir(parents=True, exist_ok=True)
        self._parser = AgentPersonaParser()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def register(self, persona: AgentPersona, source_path: Optional[Path] = None) -> Path:
        """Register a persona and store its definition."""
        persona_path = self.registry_dir / f"{persona.persona_id}.json"
        persona_path.write_text(json.dumps(asdict(persona), indent=2), encoding="utf-8")

        if source_path:
            dest = self.definitions_dir / Path(source_path).name
            if source_path.resolve() != dest.resolve():
                shutil.copyfile(source_path, dest)
        return persona_path

    def get(self, persona_id: str) -> Optional[AgentPersona]:
        path = self.registry_dir / f"{persona_id}.json"
        if not path.exists():
            # Try by name lookup
            for p in self.list_personas():
                if p.name.lower() == persona_id.lower():
                    return p
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return AgentPersona(**data)

    def list_personas(self) -> List[AgentPersona]:
        personas: List[AgentPersona] = []
        for file in self.registry_dir.glob("*.json"):
            data = json.loads(file.read_text(encoding="utf-8"))
            personas.append(AgentPersona(**data))
        return personas

    # ------------------------------------------------------------------
    # Import / Export
    # ------------------------------------------------------------------

    def import_path(self, path: Path) -> List[AgentPersona]:
        """Import agent personas from file or directory."""
        path = Path(path)
        personas: List[AgentPersona] = []
        if path.is_file():
            if path.suffix.lower() == ".zip":
                personas.extend(self.import_bundle(path))
            else:
                persona = self._parser.parse_file(path)
                self.register(persona, source_path=path)
                personas.append(persona)
            return personas

        for md_file in path.rglob("*.md"):
            persona = self._parser.parse_file(md_file)
            self.register(persona, source_path=md_file)
            personas.append(persona)
        return personas

    def import_bundle(self, bundle_path: Path) -> List[AgentPersona]:
        """Import personas from a zip bundle."""
        personas: List[AgentPersona] = []
        with zipfile.ZipFile(bundle_path, "r") as zf:
            zf.extractall(self.definitions_dir)
        for md_file in self.definitions_dir.rglob("*.md"):
            persona = self._parser.parse_file(md_file)
            self.register(persona, source_path=md_file)
            personas.append(persona)
        return personas

    def export_bundle(self, output_path: Path, persona_ids: Optional[Iterable[str]] = None) -> Path:
        """Export personas into a zip bundle."""
        output_path = Path(output_path)
        persona_ids = set(persona_ids or [])

        with zipfile.ZipFile(output_path, "w") as zf:
            for md_file in self.definitions_dir.glob("*.md"):
                if persona_ids:
                    persona = self._parser.parse_file(md_file)
                    if persona.persona_id not in persona_ids:
                        continue
                zf.write(md_file, md_file.name)
        return output_path

    # ------------------------------------------------------------------
    # Sync
    # ------------------------------------------------------------------

    def sync_to_claude(self, target_dir: Path, force: bool = False) -> List[Path]:
        """Copy definitions into Claude's agents directory."""
        target_dir = Path(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        synced: List[Path] = []
        for md_file in self.definitions_dir.glob("*.md"):
            dest = target_dir / md_file.name
            if dest.exists() and not force:
                continue
            shutil.copyfile(md_file, dest)
            synced.append(dest)
        return synced

    # ------------------------------------------------------------------
    # Packs
    # ------------------------------------------------------------------

    def list_divisions(self) -> List[str]:
        divisions = {p.division for p in self.list_personas() if p.division}
        return sorted(divisions)

    def pack(self, division: str) -> List[AgentPersona]:
        return [p for p in self.list_personas() if p.division.lower() == division.lower()]
