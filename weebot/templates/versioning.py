"""
Template Versioning System.

Features:
- Semantic versioning for templates
- Version history tracking
- Migration support between versions
- Deprecation warnings
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from packaging import version as pkg_version

from weebot.templates.parser import WorkflowTemplate

_log = logging.getLogger(__name__)


def _unsafe_migration_scripts_enabled() -> bool:
    """Opt-in flag for legacy migration scripts that execute arbitrary Python."""
    return os.getenv("WEEBOT_ENABLE_UNSAFE_MIGRATION_SCRIPTS", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@dataclass
class TemplateVersion:
    """Represents a template version."""
    version: str
    created_at: str
    author: str
    changelog: str
    template_hash: str
    is_deprecated: bool = False
    deprecated_message: str = ""
    replaced_by: Optional[str] = None


@dataclass
class VersionMigration:
    """Migration between template versions."""
    from_version: str
    to_version: str
    parameter_mapping: Dict[str, str]
    transformation_script: Optional[str] = None


class TemplateVersionManager:
    """
    Manage template versions and migrations.
    
    Features:
    - Track version history
    - Validate semantic versions
    - Migrate between versions
    - Handle deprecations
    """
    
    VERSIONS_DIR = ".template_versions"
    
    def __init__(self, templates_dir: Optional[Path] = None):
        """
        Initialize version manager.
        
        Args:
            templates_dir: Directory containing templates
        """
        self.templates_dir = templates_dir or Path("weebot/templates/builtin")
        self.versions_dir = self.templates_dir / self.VERSIONS_DIR
        self.versions_dir.mkdir(exist_ok=True)
    
    def register_version(
        self,
        template_name: str,
        version: str,
        author: str,
        changelog: str,
        template: WorkflowTemplate,
    ) -> TemplateVersion:
        """
        Register a new template version.
        
        Args:
            template_name: Template identifier
            version: Semantic version (e.g., "1.2.3")
            author: Author name
            changelog: Description of changes
            template: The workflow template
            
        Returns:
            TemplateVersion record
        """
        # Validate version
        self._validate_version(version)
        
        # Check if version already exists
        existing = self.get_version_history(template_name)
        for v in existing:
            if v.version == version:
                raise ValueError(f"Version {version} already exists for {template_name}")
        
        # Create version record
        version_record = TemplateVersion(
            version=version,
            created_at=datetime.now().isoformat(),
            author=author,
            changelog=changelog,
            template_hash=self._compute_hash(template),
        )
        
        # Save version
        self._save_version(template_name, version_record)
        
        # Save template snapshot
        self._save_template_snapshot(template_name, version, template)
        
        _log.info(f"Registered version {version} for {template_name}")
        return version_record
    
    def get_version_history(self, template_name: str) -> List[TemplateVersion]:
        """
        Get version history for a template.
        
        Returns:
            List of versions sorted by date (newest first)
        """
        versions_file = self._get_versions_file(template_name)
        
        if not versions_file.exists():
            return []
        
        with open(versions_file) as f:
            data = json.load(f)
        
        versions = [TemplateVersion(**v) for v in data.get("versions", [])]
        
        # Sort by version (newest first)
        versions.sort(key=lambda v: pkg_version.parse(v.version), reverse=True)
        
        return versions
    
    def get_latest_version(self, template_name: str) -> Optional[TemplateVersion]:
        """Get latest non-deprecated version."""
        versions = self.get_version_history(template_name)
        
        for v in versions:
            if not v.is_deprecated:
                return v
        
        return versions[0] if versions else None
    
    def deprecate_version(
        self,
        template_name: str,
        version: str,
        message: str,
        replaced_by: Optional[str] = None,
    ):
        """
        Mark a version as deprecated.
        
        Args:
            template_name: Template name
            version: Version to deprecate
            message: Deprecation message
            replaced_by: Optional replacement version
        """
        versions = self.get_version_history(template_name)
        
        for v in versions:
            if v.version == version:
                v.is_deprecated = True
                v.deprecated_message = message
                v.replaced_by = replaced_by
                break
        else:
            raise ValueError(f"Version {version} not found for {template_name}")
        
        self._save_versions(template_name, versions)
        _log.info(f"Deprecated version {version} of {template_name}")
    
    def check_deprecation(
        self,
        template_name: str,
        version: str,
    ) -> Optional[Tuple[bool, str, Optional[str]]]:
        """
        Check if a version is deprecated.
        
        Returns:
            Tuple of (is_deprecated, message, replacement_version) or None
        """
        versions = self.get_version_history(template_name)
        
        for v in versions:
            if v.version == version:
                if v.is_deprecated:
                    return (True, v.deprecated_message, v.replaced_by)
                return (False, "", None)
        
        return None
    
    def compare_versions(
        self,
        template_name: str,
        version1: str,
        version2: str,
    ) -> int:
        """
        Compare two versions.
        
        Returns:
            -1 if version1 < version2
             0 if version1 == version2
             1 if version1 > version2
        """
        v1 = pkg_version.parse(version1)
        v2 = pkg_version.parse(version2)
        
        if v1 < v2:
            return -1
        elif v1 > v2:
            return 1
        return 0
    
    def create_migration(
        self,
        template_name: str,
        from_version: str,
        to_version: str,
        parameter_mapping: Dict[str, str],
        transformation_script: Optional[str] = None,
    ) -> VersionMigration:
        """
        Create migration between versions.
        
        Args:
            template_name: Template name
            from_version: Source version
            to_version: Target version
            parameter_mapping: Map old param names to new
            transformation_script: Optional transformation code
            
        Returns:
            VersionMigration record
        """
        # Validate versions exist
        history = self.get_version_history(template_name)
        versions = [v.version for v in history]
        
        if from_version not in versions:
            raise ValueError(f"Source version {from_version} not found")
        if to_version not in versions:
            raise ValueError(f"Target version {to_version} not found")
        
        migration = VersionMigration(
            from_version=from_version,
            to_version=to_version,
            parameter_mapping=parameter_mapping,
            transformation_script=transformation_script,
        )
        
        self._save_migration(template_name, migration)
        
        return migration
    
    def migrate_parameters(
        self,
        template_name: str,
        from_version: str,
        to_version: str,
        parameters: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Migrate parameters from old version to new.
        
        Args:
            template_name: Template name
            from_version: Source version
            to_version: Target version
            parameters: Old parameters
            
        Returns:
            Migrated parameters
        """
        migration = self._get_migration(template_name, from_version, to_version)
        
        if not migration:
            _log.warning(f"No migration found from {from_version} to {to_version}")
            return parameters
        
        # Apply parameter mapping
        migrated = {}
        for old_key, value in parameters.items():
            new_key = migration.parameter_mapping.get(old_key, old_key)
            migrated[new_key] = value
        
        # Apply transformation script if present
        if migration.transformation_script:
            if not _unsafe_migration_scripts_enabled():
                _log.warning(
                    "Skipped migration transformation script from %s to %s; "
                    "set WEEBOT_ENABLE_UNSAFE_MIGRATION_SCRIPTS=true to opt in.",
                    from_version,
                    to_version,
                )
            else:
                # Legacy compatibility mode: this is intentionally opt-in only.
                try:
                    transform_locals = {
                        "parameters": dict(migrated),
                        "result": dict(migrated),
                    }
                    exec(
                        migration.transformation_script,
                        {"__builtins__": {}},
                        transform_locals,
                    )
                    transformed = transform_locals.get("result", migrated)
                    if isinstance(transformed, dict):
                        migrated = transformed
                    else:
                        _log.error(
                            "Migration transformation returned non-dict result; ignoring."
                        )
                except Exception as e:
                    _log.error(f"Migration transformation failed: {e}")
        
        return migrated
    
    def list_all_versions(self) -> Dict[str, List[TemplateVersion]]:
        """List all versions for all templates."""
        result = {}
        
        for versions_file in self.versions_dir.glob("*_versions.json"):
            template_name = versions_file.stem.replace("_versions", "")
            result[template_name] = self.get_version_history(template_name)
        
        return result
    
    # Private methods
    
    def _validate_version(self, version: str):
        """Validate semantic version format."""
        try:
            pkg_version.parse(version)
        except Exception as e:
            raise ValueError(f"Invalid version format: {version}") from e
    
    def _compute_hash(self, template: WorkflowTemplate) -> str:
        """Compute hash of template for integrity."""
        import hashlib
        import json
        
        content = json.dumps({
            "name": template.name,
            "version": template.version,
            "workflow": template.workflow,
        }, sort_keys=True)
        
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def _get_versions_file(self, template_name: str) -> Path:
        """Get path to versions file."""
        return self.versions_dir / f"{template_name}_versions.json"
    
    def _save_version(self, template_name: str, version: TemplateVersion):
        """Save a version record."""
        versions = self.get_version_history(template_name)
        versions.append(version)
        self._save_versions(template_name, versions)
    
    def _save_versions(self, template_name: str, versions: List[TemplateVersion]):
        """Save all versions."""
        versions_file = self._get_versions_file(template_name)
        
        data = {
            "template_name": template_name,
            "versions": [asdict(v) for v in versions]
        }
        
        with open(versions_file, "w") as f:
            json.dump(data, f, indent=2)
    
    def _save_template_snapshot(
        self,
        template_name: str,
        version: str,
        template: WorkflowTemplate,
    ):
        """Save template snapshot."""
        snapshot_dir = self.versions_dir / "snapshots"
        snapshot_dir.mkdir(exist_ok=True)
        
        snapshot_file = snapshot_dir / f"{template_name}_{version}.json"
        
        import yaml
        data = {
            "name": template.name,
            "version": template.version,
            "description": template.description,
            "author": template.author,
            "parameters": {
                name: {
                    "type": param.type,
                    "description": param.description,
                    "required": param.required,
                    "default": param.default,
                }
                for name, param in template.parameters.items()
            },
            "workflow": template.workflow,
            "output": template.output,
        }
        
        with open(snapshot_file, "w") as f:
            json.dump(data, f, indent=2)
    
    def _save_migration(self, template_name: str, migration: VersionMigration):
        """Save migration record."""
        migrations_file = self.versions_dir / f"{template_name}_migrations.json"
        
        migrations = []
        if migrations_file.exists():
            with open(migrations_file) as f:
                data = json.load(f)
                migrations = data.get("migrations", [])
        
        # Check if migration already exists
        for i, m in enumerate(migrations):
            if m["from_version"] == migration.from_version and m["to_version"] == migration.to_version:
                migrations[i] = asdict(migration)
                break
        else:
            migrations.append(asdict(migration))
        
        with open(migrations_file, "w") as f:
            json.dump({"migrations": migrations}, f, indent=2)
    
    def _get_migration(
        self,
        template_name: str,
        from_version: str,
        to_version: str,
    ) -> Optional[VersionMigration]:
        """Get migration record."""
        migrations_file = self.versions_dir / f"{template_name}_migrations.json"
        
        if not migrations_file.exists():
            return None
        
        with open(migrations_file) as f:
            data = json.load(f)
        
        for m in data.get("migrations", []):
            if m["from_version"] == from_version and m["to_version"] == to_version:
                return VersionMigration(**m)
        
        return None


class VersionedTemplateRegistry:
    """
    Template registry with versioning support.
    
    Combines TemplateRegistry with VersionManager.
    """
    
    def __init__(self, registry=None, version_manager=None):
        from weebot.templates.registry import TemplateRegistry
        
        self.registry = registry or TemplateRegistry()
        self.version_manager = version_manager or TemplateVersionManager()
    
    def register_with_version(
        self,
        template: WorkflowTemplate,
        author: str,
        changelog: str,
    ) -> TemplateVersion:
        """Register template with version tracking."""
        # Register with registry
        self.registry.register(template)
        
        # Register version
        return self.version_manager.register_version(
            template_name=template.name,
            version=template.version,
            author=author,
            changelog=changelog,
            template=template,
        )
    
    def get_template(
        self,
        name: str,
        version: Optional[str] = None,
        check_deprecated: bool = True,
    ) -> Optional[WorkflowTemplate]:
        """
        Get template with version support.
        
        Args:
            name: Template name
            version: Specific version or None for latest
            check_deprecated: Warn if version is deprecated
            
        Returns:
            Template or None
        """
        if version:
            # Check deprecation
            if check_deprecated:
                deprecation = self.version_manager.check_deprecation(name, version)
                if deprecation and deprecation[0]:
                    is_dep, message, replacement = deprecation
                    _log.warning(f"Template {name}@{version} is deprecated: {message}")
                    if replacement:
                        _log.warning(f"Use version {replacement} instead")
            
            # Try to get specific version
            # TODO: Load from snapshot if needed
            pass
        
        # Get from registry (latest)
        return self.registry.get(name)
    
    def list_templates_with_versions(self) -> Dict[str, List[str]]:
        """List all templates with their versions."""
        result = {}
        
        for name in self.registry.list_templates():
            versions = self.version_manager.get_version_history(name)
            result[name] = [v.version for v in versions]
        
        return result
