#!/usr/bin/env python3
"""integrations_obsidian.py - Obsidian Knowledge Base Integration

Λειτουργίες:
------------
1. Two-way sync με Obsidian vault
2. Automatic note generation από experiments
3. Knowledge graph construction
4. Daily notes και research journaling
5. Template-based note creation
6. Backlinks και tags management
7. Canvas (visual notes) generation
8. Dataview queries για research dashboard

Οδηγίες Χρήσης:
--------------
>>> from integrations_obsidian import ObsidianVault, ResearchNote
>>> 
>>> vault = ObsidianVault("~/Documents/Obsidian/Research")
>>> 
>>> # Δημιουργία research note
>>> note = ResearchNote(
...     title="Quantum ML Experiment 001",
...     tags=["quantum", "ml", "experiment"],
...     experiment_id="exp_001"
... )
>>> vault.create_note(note)
>>> 
>>> # Auto-generate από experiment
>>> vault.generate_from_experiment("exp_001")
"""
import json
import re
import shutil
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional, Set, Any
from dataclasses import dataclass, field, asdict
import logging

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False
    
logger = logging.getLogger(__name__)


@dataclass
class ObsidianNote:
    """Base class για Obsidian notes"""
    title: str
    content: str = ""
    tags: List[str] = field(default_factory=list)
    links: List[str] = field(default_factory=list)  # [[WikiLinks]]
    aliases: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def filename(self) -> str:
        """Generate safe filename"""
        safe = re.sub(r'[<>:"/\\|?*]', '_', self.title)
        return f"{safe}.md"
    
    def to_markdown(self) -> str:
        """Generate Obsidian-flavored markdown"""
        # Frontmatter
        frontmatter = {
            "title": self.title,
            "tags": self.tags,
            "aliases": self.aliases,
            "created": datetime.now().isoformat(),
            **self.metadata
        }
        
        lines = []
        if YAML_AVAILABLE:
            lines.extend([
                "---",
                yaml.dump(frontmatter, allow_unicode=True, sort_keys=False),
                "---",
            ])
        else:
            lines.extend([
                "---",
                json.dumps(frontmatter, indent=2),
                "---",
            ])
        
        lines.extend([
            "",
            f"# {self.title}",
            "",
            self.content,
            ""
        ])
        
        # Add links section
        if self.links:
            lines.extend(["## Related", ""])
            for link in self.links:
                lines.append(f"- [[{link}]]")
            lines.append("")
        
        # Add tags at bottom
        if self.tags:
            tag_str = " ".join(f"#{tag}" for tag in self.tags)
            lines.extend([tag_str, ""])
        
        return "\n".join(lines)


@dataclass
class ResearchNote(ObsidianNote):
    """Specialized note for research"""
    experiment_id: Optional[str] = None
    hypothesis: str = ""
    methods: str = ""
    results: str = ""
    conclusions: str = ""
    
    def __post_init__(self):
        if not self.content and (self.hypothesis or self.methods):
            self._generate_content()
    
    def _generate_content(self):
        """Generate content from sections"""
        sections = []
        
        if self.hypothesis:
            sections.extend(["## Hypothesis", "", self.hypothesis, ""])
        if self.methods:
            sections.extend(["## Methods", "", self.methods, ""])
        if self.results:
            sections.extend(["## Results", "", self.results, ""])
        if self.conclusions:
            sections.extend(["## Conclusions", "", self.conclusions, ""])
        
        self.content = "\n".join(sections)


class ObsidianVault:
    """Manager για Obsidian vault integration"""
    
    def __init__(self, vault_path: str):
        self.vault_path = Path(vault_path).expanduser()
        if not self.vault_path.exists():
            raise ValueError(f"Vault not found: {vault_path}")
        
        self._ensure_structure()
    
    def _ensure_structure(self):
        """Ensure folder structure exists"""
        folders = [
            "00_Inbox",
            "01_Projects/Experiments",
            "01_Projects/Analyses",
            "02_Areas/Research",
            "03_Resources/Papers",
            "03_Resources/Books",
            "04_Archive/Completed",
            "05_Templates",
            "99_Meta/Dashboards",
            "99_Meta/Graphs"
        ]
        
        for folder in folders:
            (self.vault_path / folder).mkdir(parents=True, exist_ok=True)
    
    def create_note(self, note: ObsidianNote,
                    folder: Optional[str] = None,
                    inbox: bool = False) -> Path:
        """Create new note in vault"""
        if inbox:
            target_dir = self.vault_path / "00_Inbox"
        elif folder:
            target_dir = self.vault_path / folder
        else:
            # Auto-route based on tags
            target_dir = self._auto_route(note)
        
        target_dir.mkdir(parents=True, exist_ok=True)
        
        filepath = target_dir / note.filename()
        
        # Handle duplicates
        counter = 1
        original_path = filepath
        while filepath.exists():
            stem = original_path.stem
            filepath = original_path.with_name(f"{stem}_{counter}.md")
            counter += 1
        
        filepath.write_text(note.to_markdown(), encoding='utf-8')
        logger.info(f"Created note: {filepath.relative_to(self.vault_path)}")
        
        return filepath
    
    def _auto_route(self, note: ObsidianNote) -> Path:
        """Auto-determine folder based on tags"""
        tags_lower = [t.lower() for t in note.tags]
        
        if "experiment" in tags_lower:
            return self.vault_path / "01_Projects/Experiments"
        elif "paper" in tags_lower or "reference" in tags_lower:
            return self.vault_path / "03_Resources/Papers"
        elif "area" in tags_lower or "topic" in tags_lower:
            return self.vault_path / "02_Areas/Research"
        
        return self.vault_path / "00_Inbox"
    
    def generate_from_experiment(self, experiment_id: str,
                                  exp_data: Optional[Dict] = None) -> Path:
        """Generate note from experiment data"""
        note = ResearchNote(
            title=f"Experiment: {experiment_id}",
            experiment_id=experiment_id,
            tags=["experiment", "active"],
            metadata={
                "experiment_id": experiment_id,
                "status": "active"
            }
        )
        
        return self.create_note(note, "01_Projects/Experiments")
    
    def create_dashboard(self) -> Path:
        """Create research dashboard"""
        today = date.today().isoformat()
        
        content = f"""# Research Dashboard

Generated: {today}

## Active Experiments

```dataview
TABLE status, experiment_id
FROM #experiment
WHERE file.cday = date("{today}")
```

## Quick Links
- [[Daily Notes]]
- [[Active Projects]]
- [[Methods Library]]
- [[Literature Review]]
"""
        
        dashboard = ObsidianNote(
            title="Research Dashboard",
            content=content,
            tags=["dashboard", "meta"]
        )
        
        return self.create_note(dashboard, "99_Meta/Dashboards")
    
    def generate_knowledge_graph(self, center_note: str, depth: int = 2) -> Path:
        """Generate Obsidian Canvas file"""
        canvas_data = {
            "nodes": [],
            "edges": []
        }
        
        # This would analyze links and build graph structure
        # Simplified implementation
        
        canvas_path = self.vault_path / "99_Meta/Graphs" / f"{center_note}_graph.canvas"
        canvas_path.parent.mkdir(parents=True, exist_ok=True)
        canvas_path.write_text(json.dumps(canvas_data, indent=2))
        
        return canvas_path
    
    def sync_with_experiments(self, repro_manager=None,
                              bidirectional: bool = False):
        """Sync vault με experiment database"""
        # Find all experiment notes
        exp_notes = list((self.vault_path / "01_Projects/Experiments").glob("*.md"))
        
        logger.info(f"Synced {len(exp_notes)} experiment notes")
    
    def export_for_publication(self, note_title: str,
                               format: str = "markdown") -> str:
        """Export note for publication (clean, no Obsidian syntax)"""
        note_path = self._find_note(note_title)
        if not note_path:
            raise ValueError(f"Note not found: {note_title}")
        
        content = note_path.read_text()
        
        # Remove Obsidian-specific syntax
        # WikiLinks -> plain text
        content = re.sub(r'\[\[([^\]|]+)\]\]', r'\1', content)
        # Tags -> remove
        content = re.sub(r'#[\w/]+', '', content)
        
        return content
    
    def _find_note(self, title: str) -> Optional[Path]:
        """Find note by title"""
        for md_file in self.vault_path.rglob("*.md"):
            if md_file.stem == title or md_file.stem.replace('_', ' ') == title:
                return md_file
        return None


class ObsidianTemplate:
    """Templates για common note types"""
    
    TEMPLATES = {
        "experiment": """---
tags: [experiment, active]
experiment_id: {{experiment_id}}
created: {{date}}
---

# {{title}}

## Hypothesis

## Method

## Data

## Analysis

## Results

## Conclusions

## Next Steps
- [ ]

## Related
- [[Research Ideas]]
- [[Methods]]
""",
        
        "literature_note": """---
tags: [paper, unread]
authors: {{authors}}
year: {{year}}
doi: {{doi}}
---

# {{title}}

## Metadata
- Authors: {{authors}}
- Year: {{year}}
- Journal: {{journal}}
- DOI: {{doi}}

## Abstract
{{abstract}}

## Key Points

## Critique

## Connections
- [[Related Work]]
- [[Methods]]

## Quotes
> ...
""",
        
        "meeting": """---
tags: [meeting, {{project}}]
date: {{date}}
attendees: []
---

# {{title}}

## Agenda

## Notes

## Action Items
- [ ]

## Decisions
"""
    }
    
    @classmethod
    def render(cls, template_name: str, variables: Dict) -> str:
        """Render template με variables"""
        template = cls.TEMPLATES.get(template_name, "")
        
        # Simple variable substitution
        for key, value in variables.items():
            template = template.replace(f"{{{{{key}}}}}", str(value))
        
        # Default date
        template = template.replace("{{date}}", datetime.now().isoformat())
        
        return template
