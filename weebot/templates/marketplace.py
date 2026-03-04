"""
Template Marketplace - Share and discover templates.

Features:
- Template catalog
- Search and filter
- Ratings and reviews
- Import/Export
- Community templates
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
from urllib.parse import urljoin

import requests

from weebot.templates.parser import WorkflowTemplate, TemplateParser

_log = logging.getLogger(__name__)


@dataclass
class TemplateListing:
    """Template listing in marketplace."""
    id: str
    name: str
    description: str
    author: str
    version: str
    tags: List[str]
    download_count: int
    rating: float
    rating_count: int
    created_at: str
    updated_at: str
    download_url: str
    preview_url: Optional[str] = None


@dataclass
class TemplateReview:
    """User review for template."""
    template_id: str
    user: str
    rating: int  # 1-5
    comment: str
    created_at: str


class TemplateMarketplace:
    """
    Client for template marketplace.
    
    Connects to remote marketplace or local catalog.
    """
    
    DEFAULT_MARKETPLACE_URL = "https://marketplace.weebot.io/api/v1"
    
    def __init__(
        self,
        marketplace_url: Optional[str] = None,
        local_cache_dir: Optional[Path] = None,
    ):
        """
        Initialize marketplace client.
        
        Args:
            marketplace_url: URL of marketplace API
            local_cache_dir: Directory for local cache
        """
        self.marketplace_url = marketplace_url or self.DEFAULT_MARKETPLACE_URL
        self.cache_dir = local_cache_dir or Path.home() / ".weebot" / "marketplace"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        self.parser = TemplateParser()
        self._local_catalog: Optional[List[TemplateListing]] = None
    
    # Search & Discovery
    
    def search(
        self,
        query: str = "",
        tags: Optional[List[str]] = None,
        author: Optional[str] = None,
        min_rating: Optional[float] = None,
        sort_by: str = "relevance",  # relevance, downloads, rating, newest
    ) -> List[TemplateListing]:
        """
        Search templates in marketplace.
        
        Args:
            query: Search query
            tags: Filter by tags
            author: Filter by author
            min_rating: Minimum rating (1-5)
            sort_by: Sort order
            
        Returns:
            List of matching templates
        """
        # Try remote marketplace
        if self._is_online():
            try:
                return self._search_remote(query, tags, author, min_rating, sort_by)
            except Exception as e:
                _log.warning(f"Remote search failed: {e}, using local catalog")
        
        # Fall back to local catalog
        return self._search_local(query, tags, author, min_rating, sort_by)
    
    def _search_remote(
        self,
        query: str,
        tags: Optional[List[str]],
        author: Optional[str],
        min_rating: Optional[float],
        sort_by: str,
    ) -> List[TemplateListing]:
        """Search remote marketplace."""
        params = {
            "q": query,
            "sort": sort_by,
        }
        
        if tags:
            params["tags"] = ",".join(tags)
        if author:
            params["author"] = author
        if min_rating:
            params["min_rating"] = min_rating
        
        response = requests.get(
            f"{self.marketplace_url}/templates",
            params=params,
            timeout=10,
        )
        response.raise_for_status()
        
        data = response.json()
        return [TemplateListing(**item) for item in data.get("templates", [])]
    
    def _search_local(
        self,
        query: str,
        tags: Optional[List[str]],
        author: Optional[str],
        min_rating: Optional[float],
        sort_by: str,
    ) -> List[TemplateListing]:
        """Search local catalog."""
        catalog = self._get_local_catalog()
        
        # Filter
        results = catalog
        
        if query:
            query_lower = query.lower()
            results = [
                t for t in results
                if query_lower in t.name.lower()
                or query_lower in t.description.lower()
            ]
        
        if tags:
            results = [
                t for t in results
                if any(tag in t.tags for tag in tags)
            ]
        
        if author:
            results = [t for t in results if t.author.lower() == author.lower()]
        
        if min_rating:
            results = [t for t in results if t.rating >= min_rating]
        
        # Sort
        if sort_by == "downloads":
            results.sort(key=lambda t: t.download_count, reverse=True)
        elif sort_by == "rating":
            results.sort(key=lambda t: t.rating, reverse=True)
        elif sort_by == "newest":
            results.sort(key=lambda t: t.created_at, reverse=True)
        
        return results
    
    def get_popular(self, limit: int = 10) -> List[TemplateListing]:
        """Get most popular templates."""
        return self.search(sort_by="downloads")[:limit]
    
    def get_newest(self, limit: int = 10) -> List[TemplateListing]:
        """Get newest templates."""
        return self.search(sort_by="newest")[:limit]
    
    def get_top_rated(self, limit: int = 10) -> List[TemplateListing]:
        """Get top rated templates."""
        return self.search(sort_by="rating", min_rating=4.0)[:limit]
    
    def get_by_author(self, author: str) -> List[TemplateListing]:
        """Get all templates by an author."""
        return self.search(author=author)
    
    def get_by_tag(self, tag: str) -> List[TemplateListing]:
        """Get templates by tag."""
        return self.search(tags=[tag])
    
    def get_tags(self) -> List[str]:
        """Get all available tags."""
        catalog = self._get_local_catalog()
        tags = set()
        for listing in catalog:
            tags.update(listing.tags)
        return sorted(tags)
    
    # Download & Install
    
    def download(
        self,
        template_id: str,
        version: Optional[str] = None,
        install_dir: Optional[Path] = None,
    ) -> Path:
        """
        Download and install a template.
        
        Args:
            template_id: Template ID
            version: Specific version or latest
            install_dir: Where to install (default: builtin)
            
        Returns:
            Path to installed template
        """
        install_dir = install_dir or Path("weebot/templates/builtin")
        
        # Get template info
        listing = self._get_template_info(template_id)
        if not listing:
            raise ValueError(f"Template {template_id} not found")
        
        # Download
        if self._is_online():
            try:
                template_path = self._download_remote(
                    template_id,
                    version or listing.version,
                    install_dir,
                )
            except Exception as e:
                _log.error(f"Download failed: {e}")
                raise
        else:
            raise RuntimeError("Cannot download: offline mode")
        
        # Update local catalog
        self._update_local_catalog(listing)
        
        _log.info(f"Downloaded {template_id} to {template_path}")
        return template_path
    
    def _download_remote(
        self,
        template_id: str,
        version: str,
        install_dir: Path,
    ) -> Path:
        """Download from remote marketplace."""
        url = f"{self.marketplace_url}/templates/{template_id}/download"
        
        response = requests.get(url, params={"version": version}, timeout=30)
        response.raise_for_status()
        
        # Save to file
        template_data = response.text
        template_name = template_id.replace("-", "_")
        template_path = install_dir / f"{template_name}.yaml"
        
        template_path.write_text(template_data, encoding="utf-8")
        
        return template_path
    
    def install_from_file(
        self,
        file_path: Path,
        install_dir: Optional[Path] = None,
    ) -> Path:
        """
        Install template from local file.
        
        Args:
            file_path: Path to YAML template file
            install_dir: Where to install
            
        Returns:
            Path to installed template
        """
        install_dir = install_dir or Path("weebot/templates/builtin")
        
        # Validate template
        template = self.parser.parse_file(file_path)
        
        # Copy to install dir
        dest_path = install_dir / file_path.name
        dest_path.write_text(file_path.read_text(), encoding="utf-8")
        
        _log.info(f"Installed {template.name} to {dest_path}")
        return dest_path
    
    def uninstall(self, template_name: str) -> bool:
        """
        Uninstall a template.
        
        Returns:
            True if removed, False if not found
        """
        # Find template file
        builtin_dir = Path("weebot/templates/builtin")
        template_file = builtin_dir / f"{template_name}.yaml"
        
        if template_file.exists():
            template_file.unlink()
            _log.info(f"Uninstalled {template_name}")
            return True
        
        return False
    
    # Publish & Share
    
    def publish(
        self,
        template_path: Path,
        author: str,
        tags: List[str],
        marketplace_token: Optional[str] = None,
    ) -> TemplateListing:
        """
        Publish template to marketplace.
        
        Args:
            template_path: Path to template file
            author: Author name
            tags: Tags for categorization
            marketplace_token: API token for authentication
            
        Returns:
            Published template listing
        """
        if not self._is_online():
            raise RuntimeError("Cannot publish: offline mode")
        
        # Validate template
        template = self.parser.parse_file(template_path)
        
        # Read file content
        content = template_path.read_text(encoding="utf-8")
        
        # Prepare request
        data = {
            "name": template.name,
            "description": template.description,
            "author": author,
            "version": template.version,
            "tags": tags,
            "content": content,
        }
        
        headers = {}
        if marketplace_token:
            headers["Authorization"] = f"Bearer {marketplace_token}"
        
        response = requests.post(
            f"{self.marketplace_url}/templates",
            json=data,
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        
        result = response.json()
        listing = TemplateListing(**result)
        
        _log.info(f"Published {template.name} to marketplace")
        return listing
    
    def update(
        self,
        template_id: str,
        template_path: Path,
        changelog: str,
        marketplace_token: str,
    ) -> TemplateListing:
        """Update published template."""
        template = self.parser.parse_file(template_path)
        content = template_path.read_text(encoding="utf-8")
        
        data = {
            "version": template.version,
            "changelog": changelog,
            "content": content,
        }
        
        response = requests.put(
            f"{self.marketplace_url}/templates/{template_id}",
            json=data,
            headers={"Authorization": f"Bearer {marketplace_token}"},
            timeout=30,
        )
        response.raise_for_status()
        
        return TemplateListing(**response.json())
    
    def delete(
        self,
        template_id: str,
        marketplace_token: str,
    ) -> bool:
        """Delete published template."""
        response = requests.delete(
            f"{self.marketplace_url}/templates/{template_id}",
            headers={"Authorization": f"Bearer {marketplace_token}"},
            timeout=10,
        )
        response.raise_for_status()
        
        return True
    
    # Reviews & Ratings
    
    def submit_review(
        self,
        template_id: str,
        rating: int,
        comment: str,
        user: str,
        marketplace_token: str,
    ) -> TemplateReview:
        """Submit a review for template."""
        if not 1 <= rating <= 5:
            raise ValueError("Rating must be between 1 and 5")
        
        data = {
            "template_id": template_id,
            "user": user,
            "rating": rating,
            "comment": comment,
        }
        
        response = requests.post(
            f"{self.marketplace_url}/templates/{template_id}/reviews",
            json=data,
            headers={"Authorization": f"Bearer {marketplace_token}"},
            timeout=10,
        )
        response.raise_for_status()
        
        return TemplateReview(**response.json())
    
    def get_reviews(self, template_id: str) -> List[TemplateReview]:
        """Get reviews for template."""
        response = requests.get(
            f"{self.marketplace_url}/templates/{template_id}/reviews",
            timeout=10,
        )
        response.raise_for_status()
        
        data = response.json()
        return [TemplateReview(**item) for item in data.get("reviews", [])]
    
    # Import/Export
    
    def export_template(
        self,
        template_name: str,
        output_path: Path,
        include_metadata: bool = True,
    ):
        """Export template to file."""
        template_path = Path("weebot/templates/builtin") / f"{template_name}.yaml"
        
        if not template_path.exists():
            raise FileNotFoundError(f"Template {template_name} not found")
        
        content = template_path.read_text(encoding="utf-8")
        
        if include_metadata:
            template = self.parser.parse_file(template_path)
            metadata = {
                "name": template.name,
                "version": template.version,
                "author": template.author,
                "exported_at": datetime.now().isoformat(),
            }
            output = f"# Metadata: {json.dumps(metadata)}\n\n{content}"
        else:
            output = content
        
        output_path.write_text(output, encoding="utf-8")
        _log.info(f"Exported {template_name} to {output_path}")
    
    def import_template(
        self,
        input_path: Path,
        install_dir: Optional[Path] = None,
    ) -> Path:
        """Import template from file."""
        content = input_path.read_text(encoding="utf-8")
        
        # Strip metadata if present
        if content.startswith("# Metadata:"):
            content = "\n".join(content.split("\n")[2:])
        
        # Validate
        template = self.parser.parse(content)
        
        # Save
        install_dir = install_dir or Path("weebot/templates/builtin")
        dest_path = install_dir / f"{template.name.replace(' ', '_').lower()}.yaml"
        dest_path.write_text(content, encoding="utf-8")
        
        _log.info(f"Imported {template.name} from {input_path}")
        return dest_path
    
    # Private methods
    
    def _is_online(self) -> bool:
        """Check if marketplace is accessible."""
        try:
            response = requests.get(
                f"{self.marketplace_url}/health",
                timeout=5,
            )
            return response.status_code == 200
        except:
            return False
    
    def _get_local_catalog(self) -> List[TemplateListing]:
        """Get local catalog cache."""
        if self._local_catalog is None:
            catalog_file = self.cache_dir / "catalog.json"
            
            if catalog_file.exists():
                with open(catalog_file) as f:
                    data = json.load(f)
                self._local_catalog = [
                    TemplateListing(**item) for item in data.get("templates", [])
                ]
            else:
                self._local_catalog = self._build_builtin_catalog()
        
        return self._local_catalog
    
    def _build_builtin_catalog(self) -> List[TemplateListing]:
        """Build catalog from builtin templates."""
        catalog = []
        builtin_dir = Path("weebot/templates/builtin")
        
        for yaml_file in builtin_dir.glob("*.yaml"):
            try:
                template = self.parser.parse_file(yaml_file)
                
                listing = TemplateListing(
                    id=template.name.replace(" ", "-").lower(),
                    name=template.name,
                    description=template.description[:200] if template.description else "",
                    author=template.author or "Weebot Team",
                    version=template.version,
                    tags=[],  # Could extract from description
                    download_count=0,
                    rating=5.0,
                    rating_count=1,
                    created_at=datetime.now().isoformat(),
                    updated_at=datetime.now().isoformat(),
                    download_url=f"file://{yaml_file.absolute()}",
                )
                
                catalog.append(listing)
            except Exception as e:
                _log.warning(f"Failed to parse {yaml_file}: {e}")
        
        return catalog
    
    def _update_local_catalog(self, listing: TemplateListing):
        """Update local catalog with new listing."""
        catalog = self._get_local_catalog()
        
        # Replace if exists
        for i, item in enumerate(catalog):
            if item.id == listing.id:
                catalog[i] = listing
                break
        else:
            catalog.append(listing)
        
        # Save
        catalog_file = self.cache_dir / "catalog.json"
        with open(catalog_file, "w") as f:
            json.dump(
                {"templates": [asdict(item) for item in catalog]},
                f,
                indent=2,
            )
        
        self._local_catalog = catalog
    
    def _get_template_info(self, template_id: str) -> Optional[TemplateListing]:
        """Get template info by ID."""
        catalog = self._get_local_catalog()
        
        for item in catalog:
            if item.id == template_id:
                return item
        
        return None


class LocalTemplateRepository:
    """
    Local template repository for offline use.
    
    Manages a collection of templates without marketplace.
    """
    
    def __init__(self, repo_dir: Optional[Path] = None):
        self.repo_dir = repo_dir or Path.home() / ".weebot" / "templates"
        self.repo_dir.mkdir(parents=True, exist_ok=True)
        
        self.parser = TemplateParser()
    
    def list_templates(self) -> List[Dict[str, Any]]:
        """List all templates in repository."""
        templates = []
        
        for yaml_file in self.repo_dir.glob("*.yaml"):
            try:
                template = self.parser.parse_file(yaml_file)
                templates.append({
                    "name": template.name,
                    "version": template.version,
                    "author": template.author,
                    "file": str(yaml_file),
                })
            except:
                pass
        
        return templates
    
    def add_template(self, source_path: Path) -> Path:
        """Add template to repository."""
        template = self.parser.parse_file(source_path)
        
        dest = self.repo_dir / f"{template.name.replace(' ', '_').lower()}.yaml"
        dest.write_text(source_path.read_text(), encoding="utf-8")
        
        return dest
    
    def remove_template(self, name: str) -> bool:
        """Remove template from repository."""
        template_file = self.repo_dir / f"{name.replace(' ', '_').lower()}.yaml"
        
        if template_file.exists():
            template_file.unlink()
            return True
        
        return False
    
    def export_bundle(self, output_path: Path, template_names: List[str]):
        """Export multiple templates as bundle."""
        import zipfile
        
        with zipfile.ZipFile(output_path, "w") as zf:
            for name in template_names:
                template_file = self.repo_dir / f"{name.replace(' ', '_').lower()}.yaml"
                if template_file.exists():
                    zf.write(template_file, template_file.name)
        
        _log.info(f"Exported {len(template_names)} templates to {output_path}")
    
    def import_bundle(self, bundle_path: Path):
        """Import templates from bundle."""
        import zipfile
        
        with zipfile.ZipFile(bundle_path, "r") as zf:
            zf.extractall(self.repo_dir)
        
        _log.info(f"Imported templates from {bundle_path}")
