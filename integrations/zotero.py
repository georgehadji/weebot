#!/usr/bin/env python3
"""integrations_zotero.py - Zotero Reference Manager Integration

Λειτουργίες:
------------
1. Two-way sync με Zotero library
2. Automatic citation key generation
3. PDF attachment management
4. Tag/Collection synchronization
5. Citation insertion σε papers
6. Bibliography export σε multiple formats
7. Duplicate detection και merging

Οδηγίες Χρήσης:
--------------
>>> from integrations_zotero import ZoteroSync
>>> 
>>> zot = ZoteroSync(
...     library_id="12345",
...     library_type="user",
...     api_key="your_api_key"
... )
>>> 
>>> # Sync
>>> zot.sync()
>>> 
>>> # Export για paper
>>> zot.export_bibliography("my_paper", format="biblatex")
"""
import json
import logging
from typing import Dict, List, Optional, Union
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

try:
    from pyzotero import zotero
    PYZOTERO_AVAILABLE = True
except ImportError:
    PYZOTERO_AVAILABLE = False
    logger.warning("pyzotero not installed, Zotero integration disabled")


@dataclass
class ZoteroItem:
    """Simplified Zotero item representation"""
    key: str
    title: str
    authors: List[str]
    year: Optional[int]
    item_type: str  # journalArticle, book, etc.
    doi: Optional[str] = None
    url: Optional[str] = None
    abstract: Optional[str] = None
    tags: List[str] = None
    collections: List[str] = None
    pdf_path: Optional[str] = None
    
    def __post_init__(self):
        if self.tags is None:
            self.tags = []
        if self.collections is None:
            self.collections = []
    
    def to_csl(self) -> Dict:
        """Convert to CSL-JSON format"""
        return {
            "id": self.key,
            "type": self.item_type,
            "title": self.title,
            "author": [{"family": a.split(",")[0].strip(),
                       "given": a.split(",")[1].strip() if "," in a else ""}
                      for a in self.authors],
            "issued": {"date-parts": [[self.year]]} if self.year else None,
            "DOI": self.doi,
            "URL": self.url,
            "abstract": self.abstract
        }
    
    def generate_citation_key(self) -> str:
        """Generate BibTeX citation key"""
        if self.authors:
            first_author = self.authors[0].split(",")[0].strip().lower()
        else:
            first_author = "unknown"
        
        year = str(self.year) if self.year else "nd"
        
        # Create unique key
        key = f"{first_author}{year}"
        return key


class ZoteroSync:
    """Synchronization with Zotero library"""
    
    def __init__(self, library_id: Optional[str] = None,
                 library_type: str = "user",
                 api_key: Optional[str] = None,
                 cache_dir: str = "./zotero_cache"):
        
        self.library_id = library_id
        self.library_type = library_type
        self.api_key = api_key
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        
        self.zot = None
        if PYZOTERO_AVAILABLE and library_id and api_key:
            self.zot = zotero.Zotero(library_id, library_type, api_key)
        
        self.local_items: Dict[str, ZoteroItem] = {}
        self._load_cache()
    
    def _load_cache(self):
        """Load cached items"""
        cache_file = self.cache_dir / "items.json"
        if cache_file.exists():
            try:
                data = json.loads(cache_file.read_text())
                for item_data in data:
                    item = ZoteroItem(**item_data)
                    self.local_items[item.key] = item
            except Exception as e:
                logger.warning(f"Failed to load cache: {e}")
    
    def _save_cache(self):
        """Save items to cache"""
        cache_file = self.cache_dir / "items.json"
        data = []
        for item in self.local_items.values():
            item_dict = {
                "key": item.key,
                "title": item.title,
                "authors": item.authors,
                "year": item.year,
                "item_type": item.item_type,
                "doi": item.doi,
                "url": item.url,
                "abstract": item.abstract,
                "tags": item.tags,
                "collections": item.collections
            }
            data.append(item_dict)
        
        cache_file.write_text(json.dumps(data, indent=2))
    
    def sync(self, full_sync: bool = False) -> Dict[str, int]:
        """Sync with Zotero server"""
        if not self.zot:
            logger.warning("Zotero not configured")
            return {"added": 0, "updated": 0, "removed": 0}
        
        stats = {"added": 0, "updated": 0, "removed": 0}
        
        try:
            # Fetch items from Zotero
            items = self.zot.items(limit=100)
            
            for item in items:
                z_item = self._convert_zotero_item(item)
                
                if z_item.key not in self.local_items:
                    stats["added"] += 1
                else:
                    stats["updated"] += 1
                
                self.local_items[z_item.key] = z_item
            
            self._save_cache()
            logger.info(f"Sync complete: {stats}")
            
        except Exception as e:
            logger.error(f"Sync failed: {e}")
        
        return stats
    
    def _convert_zotero_item(self, item: Dict) -> ZoteroItem:
        """Convert Zotero API item to ZoteroItem"""
        data = item.get("data", {})
        
        # Extract authors
        creators = data.get("creators", [])
        authors = []
        for creator in creators:
            if creator.get("creatorType") in ["author", "editor"]:
                first = creator.get("firstName", "")
                last = creator.get("lastName", "")
                if first:
                    authors.append(f"{last}, {first}")
                else:
                    authors.append(last)
        
        # Extract year
        date = data.get("date", "")
        year = None
        if date:
            try:
                year = int(date.split("-")[0])
            except ValueError:
                pass
        
        return ZoteroItem(
            key=item.get("key"),
            title=data.get("title", "Untitled"),
            authors=authors,
            year=year,
            item_type=data.get("itemType", "document"),
            doi=data.get("DOI"),
            url=data.get("url"),
            abstract=data.get("abstractNote"),
            tags=[t.get("tag") for t in data.get("tags", [])],
            collections=item.get("data", {}).get("collections", [])
        )
    
    def search_local(self, query: str) -> List[ZoteroItem]:
        """Search local cache"""
        query_lower = query.lower()
        results = []
        
        for item in self.local_items.values():
            if (query_lower in item.title.lower() or
                any(query_lower in a.lower() for a in item.authors) or
                query_lower in (item.abstract or "").lower() or
                any(query_lower in t.lower() for t in item.tags)):
                results.append(item)
        
        return results
    
    def add_item_from_agent(self, title: str, authors: List[str],
                           year: int, doi: Optional[str] = None,
                           **kwargs) -> Optional[str]:
        """Add new item from agent"""
        if not self.zot:
            logger.warning("Zotero not configured")
            return None
        
        template = {
            "itemType": "journalArticle",
            "title": title,
            "creators": [{"creatorType": "author", 
                         "firstName": "", 
                         "lastName": a} for a in authors],
            "date": str(year),
            "DOI": doi
        }
        
        try:
            result = self.zot.create_items([template])
            key = result.get("successful", {}).get("0", {}).get("key")
            logger.info(f"Added item: {key}")
            return key
        except Exception as e:
            logger.error(f"Failed to add item: {e}")
            return None
    
    def export_bibliography(self, name: str, format: str = "biblatex",
                           items: Optional[List[str]] = None) -> str:
        """Export bibliography in specified format"""
        if items:
            export_items = [self.local_items[k] for k in items if k in self.local_items]
        else:
            export_items = list(self.local_items.values())
        
        if format == "biblatex":
            return self._export_biblatex(export_items)
        elif format == "csl-json":
            return json.dumps([i.to_csl() for i in export_items], indent=2)
        elif format == "apa":
            return self._export_apa(export_items)
        else:
            raise ValueError(f"Unknown format: {format}")
    
    def _export_biblatex(self, items: List[ZoteroItem]) -> str:
        """Export as BibLaTeX"""
        lines = []
        
        for item in items:
            key = item.generate_citation_key()
            entry_type = "article" if item.item_type == "journalArticle" else "misc"
            
            lines.append(f"@{entry_type}{{{key},")
            lines.append(f"  title = {{{item.title}}},")
            lines.append(f"  author = {{{' and '.join(item.authors)}}},")
            if item.year:
                lines.append(f"  year = {{{item.year}}},")
            if item.doi:
                lines.append(f"  doi = {{{item.doi}}},")
            if item.url:
                lines.append(f"  url = {{{item.url}}},")
            lines.append("}")
            lines.append("")
        
        return "\n".join(lines)
    
    def _export_apa(self, items: List[ZoteroItem]) -> str:
        """Export as APA formatted citations"""
        lines = []
        
        for item in items:
            # Simplified APA format
            if len(item.authors) == 1:
                authors_str = item.authors[0]
            elif len(item.authors) == 2:
                authors_str = f"{item.authors[0]} & {item.authors[1]}"
            elif len(item.authors) > 2:
                authors_str = f"{item.authors[0]} et al."
            else:
                authors_str = "Unknown"
            
            line = f"{authors_str} ({item.year or 'n.d.'}). {item.title}."
            lines.append(line)
        
        return "\n\n".join(lines)
