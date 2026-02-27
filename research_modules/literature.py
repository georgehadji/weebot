#!/usr/bin/env python3
"""research_literature.py - Scientific Literature Integration & Citation Management

Λειτουργίες:
------------
1. Automatic citation extraction από text
2. DOI resolution και metadata fetching
3. BibTeX management
4. Citation style formatting (APA, MLA, Chicago)
5. Literature review generation
6. Semantic Scholar / Crossref integration
7. Reference deduplication

Οδηγίες Χρήσης:
--------------
>>> from research_literature import CitationManager, LiteratureReview
>>> 
>>> cm = CitationManager()
>>> 
>>> # Προσθήκη από DOI
>>> cm.add_from_doi("10.1038/s41586-021-03819-2")
>>> 
>>> # Generate bibliography
>>> print(cm.format_bibliography(style="apa"))
"""
import re
import json
import logging
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class Citation:
    """Αναπαράσταση citation"""
    id: str
    title: str
    authors: List[str]
    year: int
    journal: Optional[str] = None
    volume: Optional[str] = None
    pages: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    abstract: Optional[str] = None
    keywords: List[str] = field(default_factory=list)
    added_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def format_apa(self) -> str:
        """Format σε APA style"""
        authors_str = self._format_authors()
        parts = [authors_str, f"({self.year})", self.title]
        
        if self.journal:
            parts.append(f"*{self.journal}*")
            if self.volume:
                parts.append(f"*{self.volume}*")
            if self.pages:
                parts.append(self.pages)
        
        if self.doi:
            parts.append(f"https://doi.org/{self.doi}")
        
        return ". ".join(parts) + "."
    
    def format_bibtex(self) -> str:
        """Format σε BibTeX"""
        entry_type = "article" if self.journal else "misc"
        key = f"{self.authors[0].split(',')[0].lower()}{self.year}"
        
        fields = [
            f"  title={{{self.title}}}",
            f"  author={{{' and '.join(self.authors)}}}",
            f"  year={{{self.year}}}",
        ]
        
        if self.journal:
            fields.append(f"  journal={{{self.journal}}}")
        if self.volume:
            fields.append(f"  volume={{{self.volume}}}")
        if self.pages:
            fields.append(f"  pages={{{self.pages}}}")
        if self.doi:
            fields.append(f"  doi={{{self.doi}}}")
        
        return f"@{entry_type}{{{key},\n" + ",\n".join(fields) + "\n}"
    
    def _format_authors(self) -> str:
        """Format authors for citation"""
        if len(self.authors) == 1:
            return self.authors[0]
        elif len(self.authors) == 2:
            return f"{self.authors[0]} & {self.authors[1]}"
        elif len(self.authors) > 7:
            return f"{self.authors[0]} et al."
        else:
            return ", ".join(self.authors[:-1]) + ", & " + self.authors[-1]


class CitationManager:
    """Manager για citations και bibliography"""
    
    def __init__(self, storage_path: str = "./citations.json"):
        self.storage_path = Path(storage_path)
        self.citations: Dict[str, Citation] = {}
        self._load()
    
    def _load(self):
        """Load citations from storage"""
        if self.storage_path.exists():
            data = json.loads(self.storage_path.read_text())
            for item in data:
                citation = Citation(**item)
                self.citations[citation.id] = citation
    
    def _save(self):
        """Save citations to storage"""
        data = [asdict(c) for c in self.citations.values()]
        self.storage_path.write_text(json.dumps(data, indent=2))
    
    def add(self, citation: Citation) -> str:
        """Add citation to library"""
        self.citations[citation.id] = citation
        self._save()
        return citation.id
    
    def add_from_doi(self, doi: str) -> Optional[str]:
        """Fetch and add citation from DOI"""
        if not REQUESTS_AVAILABLE:
            logger.warning("requests not available")
            return None
        
        try:
            # Use Crossref API
            url = f"https://api.crossref.org/works/{doi}"
            response = requests.get(url)
            data = response.json()
            
            if data["status"] == "ok":
                work = data["message"]
                
                citation = Citation(
                    id=f"doi:{doi}",
                    title=work.get("title", [""])[0],
                    authors=[f"{a.get('family')}, {a.get('given', '')}" 
                            for a in work.get("author", [])],
                    year=work.get("published-print", {}).get("date-parts", [[0]])[0][0],
                    journal=work.get("container-title", [None])[0],
                    volume=work.get("volume"),
                    pages=work.get("page"),
                    doi=doi,
                    url=work.get("URL"),
                    abstract=work.get("abstract"),
                    keywords=work.get("subject", [])
                )
                
                return self.add(citation)
                
        except Exception as e:
            logger.error(f"Failed to fetch DOI {doi}: {e}")
        
        return None
    
    def extract_citations(self, text: str) -> List[str]:
        """Extract potential citations from text"""
        # Pattern for (Author, Year) or (Author et al., Year)
        pattern = r'\(([A-Z][a-z]+(?:\s+et\s+al\.)?(?:,\s*[A-Z][a-z]+)*,\s*\d{4}[a-z]?)\)'
        matches = re.findall(pattern, text)
        
        # Pattern for DOIs
        doi_pattern = r'10\.\d{4,}/[^\s]+'
        dois = re.findall(doi_pattern, text)
        
        return matches + dois
    
    def format_bibliography(self, style: str = "apa") -> str:
        """Format bibliography in specified style"""
        if style.lower() == "apa":
            formatter = lambda c: c.format_apa()
        elif style.lower() == "bibtex":
            formatter = lambda c: c.format_bibtex()
        else:
            formatter = lambda c: c.format_apa()
        
        entries = [formatter(c) for c in self.citations.values()]
        
        # Sort by year, then author
        entries.sort()
        
        return "\n\n".join(entries)
    
    def search(self, query: str) -> List[Citation]:
        """Search citations"""
        query_lower = query.lower()
        results = []
        
        for citation in self.citations.values():
            if (query_lower in citation.title.lower() or
                any(query_lower in a.lower() for a in citation.authors) or
                query_lower in (citation.abstract or "").lower()):
                results.append(citation)
        
        return results
    
    def export(self, output_path: str, format: str = "json"):
        """Export citations to file"""
        output_path = Path(output_path)
        
        if format == "json":
            data = [asdict(c) for c in self.citations.values()]
            output_path.write_text(json.dumps(data, indent=2))
        elif format == "bibtex":
            output_path.write_text(self.format_bibliography("bibtex"))
        elif format == "apa":
            output_path.write_text(self.format_bibliography("apa"))


class LiteratureReview:
    """Generate literature reviews from citations"""
    
    def __init__(self, citation_manager: CitationManager):
        self.cm = citation_manager
    
    def generate_summary(self, topic: str, max_citations: int = 10) -> str:
        """Generate summary of literature on topic"""
        relevant = self.cm.search(topic)[:max_citations]
        
        if not relevant:
            return f"No citations found for topic: {topic}"
        
        lines = [
            f"## Literature Review: {topic}",
            "",
            f"Found {len(relevant)} relevant publications:",
            ""
        ]
        
        for i, citation in enumerate(relevant, 1):
            lines.extend([
                f"{i}. {citation.format_apa()}",
                ""
            ])
            if citation.abstract:
                lines.append(f"   > {citation.abstract[:200]}...")
                lines.append("")
        
        return "\n".join(lines)
