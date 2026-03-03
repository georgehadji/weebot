"""Template registry for loading and managing templates."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Set, Union

from weebot.templates.parser import TemplateParser, WorkflowTemplate, TemplateValidationError

_log = logging.getLogger(__name__)


class TemplateRegistry:
    """
    Registry for workflow templates.
    
    Features:
    - Register templates programmatically
    - Load templates from files and directories
    - Load built-in templates
    - Search and filter templates
    - Template metadata access
    """
    
    def __init__(self):
        self._templates: Dict[str, WorkflowTemplate] = {}
        self._parser = TemplateParser()
        self._load_errors: List[str] = []
    
    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------
    
    def register(self, template: WorkflowTemplate) -> None:
        """
        Register a template in the registry.
        
        Args:
            template: The workflow template to register
            
        Raises:
            ValueError: If a template with the same name already exists
        """
        if template.name in self._templates:
            raise ValueError(f"Template '{template.name}' is already registered")
        
        self._templates[template.name] = template
        _log.debug(f"Registered template: {template.name}")
    
    def unregister(self, name: str) -> bool:
        """
        Remove a template from the registry.
        
        Args:
            name: Name of the template to remove
            
        Returns:
            True if template was removed, False if not found
        """
        if name in self._templates:
            del self._templates[name]
            _log.debug(f"Unregistered template: {name}")
            return True
        return False
    
    def clear(self) -> None:
        """Remove all templates from the registry."""
        self._templates.clear()
        self._load_errors.clear()
        _log.debug("Cleared all templates from registry")
    
    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------
    
    def get(self, name: str) -> Optional[WorkflowTemplate]:
        """
        Get a template by name.
        
        Args:
            name: Template name
            
        Returns:
            The template if found, None otherwise
        """
        return self._templates.get(name)
    
    def get_required(self, name: str) -> WorkflowTemplate:
        """
        Get a template by name, raising if not found.
        
        Args:
            name: Template name
            
        Returns:
            The template
            
        Raises:
            KeyError: If template not found
        """
        if name not in self._templates:
            raise KeyError(f"Template '{name}' not found in registry")
        return self._templates[name]
    
    def list_templates(self) -> List[str]:
        """
        List all registered template names.
        
        Returns:
            List of template names (sorted alphabetically)
        """
        return sorted(self._templates.keys())
    
    def has_template(self, name: str) -> bool:
        """Check if a template exists in the registry."""
        return name in self._templates
    
    # ------------------------------------------------------------------
    # Search & Filter
    # ------------------------------------------------------------------
    
    def search(self, query: str) -> List[WorkflowTemplate]:
        """
        Search templates by name or description.
        
        Args:
            query: Search string (case-insensitive)
            
        Returns:
            List of matching templates
        """
        query_lower = query.lower()
        results = []
        
        for template in self._templates.values():
            if (query_lower in template.name.lower() or
                query_lower in template.description.lower() or
                query_lower in template.author.lower()):
                results.append(template)
        
        return results
    
    def filter_by_author(self, author: str) -> List[WorkflowTemplate]:
        """Get all templates by a specific author."""
        return [t for t in self._templates.values() 
                if t.author.lower() == author.lower()]
    
    def filter_by_parameter(self, param_name: str) -> List[WorkflowTemplate]:
        """Get all templates that have a specific parameter."""
        return [t for t in self._templates.values() 
                if param_name in t.parameters]
    
    # ------------------------------------------------------------------
    # Loading from Files
    # ------------------------------------------------------------------
    
    def load_from_file(self, path: Union[str, Path]) -> WorkflowTemplate:
        """
        Load and register a template from a file.
        
        Args:
            path: Path to YAML or JSON template file
            
        Returns:
            The loaded template
            
        Raises:
            FileNotFoundError: If file doesn't exist
            TemplateValidationError: If template is invalid
            ValueError: If template name already registered
        """
        path = Path(path)
        template = self._parser.parse_file(path)
        self.register(template)
        return template
    
    def load_from_directory(self, directory: Union[str, Path],
                           pattern: str = "*.yaml") -> int:
        """
        Load all templates from a directory.
        
        Args:
            directory: Directory to search
            pattern: File pattern to match (default: *.yaml)
            
        Returns:
            Number of templates successfully loaded
        """
        directory = Path(directory)
        if not directory.exists():
            _log.warning(f"Directory not found: {directory}")
            return 0
        
        count = 0
        self._load_errors = []
        
        for file_path in directory.glob(pattern):
            try:
                self.load_from_file(file_path)
                count += 1
            except (TemplateValidationError, ValueError) as e:
                error_msg = f"Failed to load {file_path.name}: {e}"
                self._load_errors.append(error_msg)
                _log.warning(error_msg)
            except Exception as e:
                error_msg = f"Unexpected error loading {file_path.name}: {e}"
                self._load_errors.append(error_msg)
                _log.error(error_msg)
        
        _log.info(f"Loaded {count} templates from {directory}")
        return count
    
    def load_builtin_templates(self) -> int:
        """
        Load all built-in templates.
        
        Returns:
            Number of templates loaded
        """
        builtin_dir = Path(__file__).parent / "builtin"
        return self.load_from_directory(builtin_dir, "*.yaml")
    
    # ------------------------------------------------------------------
    # Metadata & Info
    # ------------------------------------------------------------------
    
    def get_metadata(self, name: str) -> Optional[Dict]:
        """
        Get metadata for a template.
        
        Returns:
            Dictionary with template metadata
        """
        template = self.get(name)
        if not template:
            return None
        
        return {
            "name": template.name,
            "version": template.version,
            "description": template.description,
            "author": template.author,
            "parameter_count": len(template.parameters),
            "parameters": [
                {
                    "name": p.name,
                    "type": p.type,
                    "required": p.required,
                    "has_default": p.default is not None
                }
                for p in template.parameters.values()
            ]
        }
    
    def list_metadata(self) -> List[Dict]:
        """Get metadata for all templates."""
        return [self.get_metadata(name) for name in self.list_templates()]
    
    def get_load_errors(self) -> List[str]:
        """Get errors from the last load operation."""
        return self._load_errors.copy()
    
    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------
    
    def get_statistics(self) -> Dict:
        """Get registry statistics."""
        if not self._templates:
            return {
                "total_templates": 0,
                "total_parameters": 0,
                "authors": [],
                "avg_parameters_per_template": 0
            }
        
        authors: Set[str] = set()
        total_params = 0
        
        for template in self._templates.values():
            if template.author:
                authors.add(template.author)
            total_params += len(template.parameters)
        
        return {
            "total_templates": len(self._templates),
            "total_parameters": total_params,
            "authors": sorted(authors),
            "avg_parameters_per_template": round(total_params / len(self._templates), 2)
        }
    
    def __len__(self) -> int:
        """Return number of registered templates."""
        return len(self._templates)
    
    def __contains__(self, name: str) -> bool:
        """Check if template exists (enables 'in' operator)."""
        return name in self._templates
