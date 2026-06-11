"""
Interface Customization System for Weebot

This module provides capabilities for customizing the user interface
based on user preferences, accessibility needs, and usage patterns.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol
import logging
from abc import ABC, abstractmethod
import uuid

from weebot.domain.models.user_profile import UserProfile, PreferenceCategory
from weebot.application.ports.profile_storage_port import ProfileStoragePort


class ThemeType(Enum):
    """Types of UI themes."""
    LIGHT = "light"
    DARK = "dark"
    AUTO = "auto"  # Follow system preference
    HIGH_CONTRAST = "high_contrast"
    CUSTOM = "custom"


class LayoutType(Enum):
    """Types of UI layouts."""
    STANDARD = "standard"
    COMPACT = "compact"
    SPACIOUS = "spacious"
    ACCESSIBLE = "accessible"
    CUSTOM = "custom"


class FontSize(Enum):
    """Font size options."""
    EXTRA_SMALL = "extra_small"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    EXTRA_LARGE = "extra_large"
    CUSTOM = "custom"


class ColorPalette(Enum):
    """Color palette options."""
    DEFAULT = "default"
    BLUE_REDUCED = "blue_reduced"  # For red-green colorblind users
    YELLOW_BLUE = "yellow_blue"   # For red-green colorblind users
    GRAYSCALE = "grayscale"       # For various color vision deficiencies
    CUSTOM = "custom"


class AccessibilityFeature(Enum):
    """Accessibility features."""
    SCREEN_READER_COMPATIBLE = "screen_reader_compatible"
    KEYBOARD_NAVIGATION = "keyboard_navigation"
    VOICE_COMMANDS = "voice_commands"
    TEXT_TO_SPEECH = "text_to_speech"
    SPEECH_TO_TEXT = "speech_to_text"
    ENLARGED_CURSOR = "enlarged_cursor"
    REDUCED_ANIMATION = "reduced_animation"
    HIGH_CONTRAST_MODE = "high_contrast_mode"
    DYSLEXIA_FRIENDLY = "dyslexia_friendly"


@dataclass
class UIComponent:
    """Definition of a UI component."""
    name: str
    component_type: str  # "button", "menu", "panel", "input", etc.
    position: Dict[str, int]  # x, y coordinates
    size: Dict[str, int]  # width, height
    visibility: bool
    accessibility_label: Optional[str] = None
    shortcut_key: Optional[str] = None  # Keyboard shortcut


@dataclass
class InterfacePreferences:
    """User interface preferences."""
    theme: ThemeType
    layout: LayoutType
    font_size: FontSize
    color_palette: ColorPalette
    language: str
    timezone: str
    accessibility_features: List[AccessibilityFeature]
    ui_components: List[UIComponent]
    custom_css: Optional[str] = None
    last_updated: datetime = field(default_factory=datetime.now)


@dataclass
class CustomizedInterface:
    """A customized interface configuration."""
    user_id: str
    interface_id: str
    preferences: InterfacePreferences
    created_at: datetime
    last_accessed: datetime
    is_active: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


class InterfaceCustomizer(ABC):
    """Abstract base class for interface customizers."""
    
    @abstractmethod
    async def customize_interface(self, user_profile: UserProfile) -> CustomizedInterface:
        """Generate a customized interface for a user."""
        pass


class AccessibilityBasedCustomizer(InterfaceCustomizer):
    """Customizes interface based on accessibility needs."""
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    async def customize_interface(self, user_profile: UserProfile) -> CustomizedInterface:
        """Generate an accessibility-focused interface."""
        # Extract accessibility preferences from user profile
        accessibility_prefs = {}
        for pref in user_profile.preferences:
            if pref.category == PreferenceCategory.INTERFACE_CUSTOMIZATION:
                accessibility_prefs[pref.key] = pref.value
        
        # Determine theme based on preferences
        theme_str = accessibility_prefs.get("theme", "auto")
        try:
            theme = ThemeType(theme_str)
        except ValueError:
            theme = ThemeType.AUTO
        
        # Determine layout based on preferences
        layout_str = accessibility_prefs.get("layout_preference", "standard")
        try:
            layout = LayoutType(layout_str)
        except ValueError:
            layout = LayoutType.STANDARD
        
        # Determine font size based on preferences
        font_size_str = accessibility_prefs.get("font_size", "medium")
        try:
            font_size = FontSize(font_size_str)
        except ValueError:
            font_size = FontSize.MEDIUM
        
        # Determine color palette based on preferences
        color_palette_str = accessibility_prefs.get("color_palette", "default")
        try:
            color_palette = ColorPalette(color_palette_str)
        except ValueError:
            color_palette = ColorPalette.DEFAULT
        
        # Extract accessibility features
        features_str = accessibility_prefs.get("accessibility_features", [])
        if isinstance(features_str, str):
            features_str = [features_str]
        
        accessibility_features = []
        for feat_str in features_str:
            try:
                feat = AccessibilityFeature(feat_str)
                accessibility_features.append(feat)
            except ValueError:
                self.logger.warning(f"Unknown accessibility feature: {feat_str}")
        
        # Create default UI components
        ui_components = self._create_default_ui_components(accessibility_features)
        
        # Create interface preferences
        interface_prefs = InterfacePreferences(
            theme=theme,
            layout=layout,
            font_size=font_size,
            color_palette=color_palette,
            language=accessibility_prefs.get("language", "en"),
            timezone=accessibility_prefs.get("timezone", "UTC"),
            accessibility_features=accessibility_features,
            ui_components=ui_components,
            custom_css=accessibility_prefs.get("custom_css")
        )
        
        # Create customized interface
        interface = CustomizedInterface(
            user_id=user_profile.user_id,
            interface_id=f"interface_{uuid.uuid4().hex[:8]}",
            preferences=interface_prefs,
            created_at=datetime.now(),
            last_accessed=datetime.now(),
            is_active=True,
            metadata={
                "customization_basis": "accessibility_needs",
                "user_expertise": user_profile.expertise_level
            }
        )
        
        return interface
    
    def _create_default_ui_components(self, accessibility_features: List[AccessibilityFeature]) -> List[UIComponent]:
        """Create default UI components based on accessibility features."""
        components = []
        
        # Base components
        base_components = [
            UIComponent(
                name="main_menu",
                component_type="menu",
                position={"x": 0, "y": 0},
                size={"width": 200, "height": 600},
                visibility=True,
                accessibility_label="Main navigation menu"
            ),
            UIComponent(
                name="workspace",
                component_type="panel",
                position={"x": 200, "y": 0},
                size={"width": 800, "height": 600},
                visibility=True,
                accessibility_label="Main workspace area"
            ),
            UIComponent(
                name="sidebar",
                component_type="panel",
                position={"x": 1000, "y": 0},
                size={"width": 300, "height": 600},
                visibility=True,
                accessibility_label="Sidebar with tools and options"
            ),
            UIComponent(
                name="status_bar",
                component_type="panel",
                position={"x": 0, "y": 600},
                size={"width": 1300, "height": 30},
                visibility=True,
                accessibility_label="Status bar with system information"
            )
        ]
        
        components.extend(base_components)
        
        # Add accessibility-specific components if needed
        if AccessibilityFeature.VOICE_COMMANDS in accessibility_features:
            components.append(UIComponent(
                name="voice_control",
                component_type="button",
                position={"x": 10, "y": 10},
                size={"width": 50, "height": 50},
                visibility=True,
                accessibility_label="Voice command activation button",
                shortcut_key="Ctrl+Shift+V"
            ))
        
        if AccessibilityFeature.TEXT_TO_SPEECH in accessibility_features:
            components.append(UIComponent(
                name="text_to_speech",
                component_type="button",
                position={"x": 70, "y": 10},
                size={"width": 50, "height": 50},
                visibility=True,
                accessibility_label="Text-to-speech activation button",
                shortcut_key="Ctrl+Shift+S"
            ))
        
        if AccessibilityFeature.ENLARGED_CURSOR in accessibility_features:
            components.append(UIComponent(
                name="cursor_enlarger",
                component_type="overlay",
                position={"x": 0, "y": 0},
                size={"width": 1300, "height": 630},
                visibility=True,
                accessibility_label="Cursor enlargement overlay"
            ))
        
        return components


class ExpertiseBasedCustomizer(InterfaceCustomizer):
    """Customizes interface based on user expertise level."""
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    async def customize_interface(self, user_profile: UserProfile) -> CustomizedInterface:
        """Generate an interface customized for user's expertise level."""
        # Determine customization based on expertise level
        expertise_level = user_profile.expertise_level
        
        # Set interface parameters based on expertise
        if expertise_level == "beginner":
            # Beginner-friendly: simple layout, large fonts, clear labels
            theme = ThemeType.LIGHT
            layout = LayoutType.SPACIOUS
            font_size = FontSize.LARGE
            color_palette = ColorPalette.DEFAULT
            accessibility_features = [
                AccessibilityFeature.SCREEN_READER_COMPATIBLE,
                AccessibilityFeature.REDUCED_ANIMATION
            ]
        elif expertise_level == "intermediate":
            # Intermediate: balanced approach
            theme = ThemeType.AUTO
            layout = LayoutType.STANDARD
            font_size = FontSize.MEDIUM
            color_palette = ColorPalette.DEFAULT
            accessibility_features = [AccessibilityFeature.SCREEN_READER_COMPATIBLE]
        elif expertise_level == "advanced":
            # Advanced: compact layout, efficient design
            theme = ThemeType.DARK
            layout = LayoutType.COMPACT
            font_size = FontSize.MEDIUM
            color_palette = ColorPalette.DEFAULT
            accessibility_features = []
        elif expertise_level == "expert":
            # Expert: highly customizable, efficient
            theme = ThemeType.DARK
            layout = LayoutType.COMPACT
            font_size = FontSize.SMALL
            color_palette = ColorPalette.DEFAULT
            accessibility_features = []
        else:
            # Default to intermediate
            theme = ThemeType.AUTO
            layout = LayoutType.STANDARD
            font_size = FontSize.MEDIUM
            color_palette = ColorPalette.DEFAULT
            accessibility_features = [AccessibilityFeature.SCREEN_READER_COMPATIBLE]
        
        # Create UI components based on expertise level
        ui_components = self._create_expertise_based_components(expertise_level)
        
        # Create interface preferences
        interface_prefs = InterfacePreferences(
            theme=theme,
            layout=layout,
            font_size=font_size,
            color_palette=color_palette,
            language="en",  # Could be derived from profile
            timezone="UTC",  # Could be derived from profile
            accessibility_features=accessibility_features,
            ui_components=ui_components
        )
        
        # Create customized interface
        interface = CustomizedInterface(
            user_id=user_profile.user_id,
            interface_id=f"interface_{uuid.uuid4().hex[:8]}",
            preferences=interface_prefs,
            created_at=datetime.now(),
            last_accessed=datetime.now(),
            is_active=True,
            metadata={
                "customization_basis": "expertise_level",
                "user_expertise": expertise_level
            }
        )
        
        return interface
    
    def _create_expertise_based_components(self, expertise_level: str) -> List[UIComponent]:
        """Create UI components based on user expertise level."""
        components = []
        
        if expertise_level == "beginner":
            # Beginner: More guidance, larger elements, clearer labels
            components = [
                UIComponent(
                    name="guided_toolbar",
                    component_type="toolbar",
                    position={"x": 0, "y": 0},
                    size={"width": 1300, "height": 80},
                    visibility=True,
                    accessibility_label="Guided toolbar with labeled buttons",
                ),
                UIComponent(
                    name="workspace_with_help",
                    component_type="panel",
                    position={"x": 0, "y": 80},
                    size={"width": 1300, "height": 520},
                    visibility=True,
                    accessibility_label="Main workspace with help tooltips"
                ),
                UIComponent(
                    name="big_action_buttons",
                    component_type="panel",
                    position={"x": 0, "y": 600},
                    size={"width": 1300, "height": 100},
                    visibility=True,
                    accessibility_label="Large action buttons for common tasks"
                )
            ]
        elif expertise_level == "intermediate":
            # Intermediate: Balanced approach
            components = [
                UIComponent(
                    name="standard_toolbar",
                    component_type="toolbar",
                    position={"x": 0, "y": 0},
                    size={"width": 1300, "height": 40},
                    visibility=True,
                    accessibility_label="Standard toolbar"
                ),
                UIComponent(
                    name="workspace",
                    component_type="panel",
                    position={"x": 0, "y": 40},
                    size={"width": 1000, "height": 560},
                    visibility=True,
                    accessibility_label="Main workspace"
                ),
                UIComponent(
                    name="properties_panel",
                    component_type="panel",
                    position={"x": 1000, "y": 40},
                    size={"width": 300, "height": 560},
                    visibility=True,
                    accessibility_label="Properties panel"
                )
            ]
        else:
            # Advanced/Expert: Compact, efficient
            components = [
                UIComponent(
                    name="minimal_toolbar",
                    component_type="toolbar",
                    position={"x": 0, "y": 0},
                    size={"width": 1300, "height": 30},
                    visibility=True,
                    accessibility_label="Minimal toolbar with keyboard shortcuts"
                ),
                UIComponent(
                    name="workspace",
                    component_type="panel",
                    position={"x": 0, "y": 30},
                    size={"width": 1000, "height": 570},
                    visibility=True,
                    accessibility_label="Main workspace"
                ),
                UIComponent(
                    name="compact_sidebar",
                    component_type="panel",
                    position={"x": 1000, "y": 30},
                    size={"width": 300, "height": 570},
                    visibility=True,
                    accessibility_label="Compact sidebar"
                )
            ]
        
        return components


class DomainBasedCustomizer(InterfaceCustomizer):
    """Customizes interface based on user's preferred domains."""
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        
        # Define domain-specific interface preferences
        self.domain_preferences = {
            "technology": {
                "theme": ThemeType.DARK,
                "layout": LayoutType.COMPACT,
                "components": ["code_editor", "terminal", "debugger", "api_docs"]
            },
            "business": {
                "theme": ThemeType.LIGHT,
                "layout": LayoutType.STANDARD,
                "components": ["dashboard", "analytics", "reports", "calendar"]
            },
            "education": {
                "theme": ThemeType.LIGHT,
                "layout": LayoutType.SPACIOUS,
                "components": ["notebook", "resources", "assignments", "gradebook"]
            },
            "research": {
                "theme": ThemeType.AUTO,
                "layout": LayoutType.STANDARD,
                "components": ["literature_review", "data_analysis", "visualization", "bibliography"]
            },
            "creative": {
                "theme": ThemeType.DARK,
                "layout": LayoutType.SPACIOUS,
                "components": ["canvas", "palette", "assets", "preview"]
            }
        }
    
    async def customize_interface(self, user_profile: UserProfile) -> CustomizedInterface:
        """Generate an interface customized for user's preferred domains."""
        # Determine primary domain from user profile
        preferred_domains = user_profile.preferred_domains
        primary_domain = preferred_domains[0] if preferred_domains else "general"
        
        # Get domain-specific preferences
        domain_pref = self.domain_preferences.get(primary_domain, self.domain_preferences.get("general", {}))
        
        # Set interface parameters based on domain
        theme = ThemeType(domain_pref.get("theme", "auto"))
        layout = LayoutType(domain_pref.get("layout", "standard"))
        font_size = FontSize.MEDIUM  # Domain doesn't typically affect font size
        color_palette = ColorPalette.DEFAULT
        
        # Create domain-specific UI components
        ui_components = self._create_domain_specific_components(
            domain_pref.get("components", []),
            user_profile.expertise_level
        )
        
        # Determine accessibility features based on domain and expertise
        accessibility_features = self._determine_accessibility_features(
            primary_domain, user_profile.expertise_level
        )
        
        # Create interface preferences
        interface_prefs = InterfacePreferences(
            theme=theme,
            layout=layout,
            font_size=font_size,
            color_palette=color_palette,
            language="en",  # Could be derived from profile
            timezone="UTC",  # Could be derived from profile
            accessibility_features=accessibility_features,
            ui_components=ui_components
        )
        
        # Create customized interface
        interface = CustomizedInterface(
            user_id=user_profile.user_id,
            interface_id=f"interface_{uuid.uuid4().hex[:8]}",
            preferences=interface_prefs,
            created_at=datetime.now(),
            last_accessed=datetime.now(),
            is_active=True,
            metadata={
                "customization_basis": "domain_preference",
                "primary_domain": primary_domain,
                "user_expertise": user_profile.expertise_level
            }
        )
        
        return interface
    
    def _create_domain_specific_components(
        self, 
        domain_components: List[str], 
        expertise_level: str
    ) -> List[UIComponent]:
        """Create UI components specific to a domain."""
        components = []
        
        # Base components
        base_components = [
            UIComponent(
                name="main_toolbar",
                component_type="toolbar",
                position={"x": 0, "y": 0},
                size={"width": 1300, "height": 40},
                visibility=True,
                accessibility_label="Main toolbar"
            ),
            UIComponent(
                name="workspace",
                component_type="panel",
                position={"x": 0, "y": 40},
                size={"width": 1000, "height": 560},
                visibility=True,
                accessibility_label="Main workspace"
            ),
            UIComponent(
                name="domain_sidebar",
                component_type="panel",
                position={"x": 1000, "y": 40},
                size={"width": 300, "height": 560},
                visibility=True,
                accessibility_label="Domain-specific tools and options"
            )
        ]
        
        components.extend(base_components)
        
        # Add domain-specific components
        for i, comp_name in enumerate(domain_components):
            components.append(UIComponent(
                name=comp_name,
                component_type=comp_name,  # Could be more specific
                position={"x": 1010, "y": 50 + i * 40},  # Position in sidebar
                size={"width": 280, "height": 35},
                visibility=True,
                accessibility_label=f"Domain-specific component: {comp_name.replace('_', ' ').title()}"
            ))
        
        # Adjust component sizes based on expertise level
        if expertise_level in ["advanced", "expert"]:
            # Make components more compact for experienced users
            for comp in components:
                if comp.component_type in ["button", "input", "panel"]:
                    # Reduce size slightly for expert users
                    comp.size["width"] = int(comp.size["width"] * 0.95)
                    comp.size["height"] = int(comp.size["height"] * 0.95)
        
        return components
    
    def _determine_accessibility_features(
        self, 
        domain: str, 
        expertise_level: str
    ) -> List[AccessibilityFeature]:
        """Determine appropriate accessibility features based on domain and expertise."""
        features = [AccessibilityFeature.SCREEN_READER_COMPATIBLE]
        
        # Add domain-specific features
        if domain in ["technology", "research"]:
            # Users in these domains may spend long hours - add comfort features
            features.append(AccessibilityFeature.REDUCED_ANIMATION)
        
        if domain == "education":
            # Educational users may include students with various needs
            features.append(AccessibilityFeature.DYSLEXIA_FRIENDLY)
        
        if domain == "creative":
            # Creative work may involve color-sensitive tasks
            features.append(AccessibilityFeature.HIGH_CONTRAST_MODE)
        
        # Add features based on expertise level
        if expertise_level == "beginner":
            features.extend([
                AccessibilityFeature.KEYBOARD_NAVIGATION,
                AccessibilityFeature.REDUCED_ANIMATION
            ])
        
        return features


class InterfaceCustomizationEngine:
    """Main engine for interface customization."""
    
    def __init__(self, storage: ProfileStoragePort):
        self.storage = storage
        self.customizers = [
            AccessibilityBasedCustomizer(),
            ExpertiseBasedCustomizer(),
            DomainBasedCustomizer()
        ]
        self.logger = logging.getLogger(f"{__name__}.InterfaceCustomizationEngine")
        self.active_interfaces: Dict[str, CustomizedInterface] = {}
    
    async def get_customized_interface(self, user_id: str) -> Optional[CustomizedInterface]:
        """Get a customized interface for a user."""
        # Get user profile
        profile = await self.storage.load_profile(user_id)
        if not profile:
            self.logger.warning(f"No profile found for user {user_id}")
            return None
        
        # Generate customized interface using all customizers
        customized_interfaces = []
        for customizer in self.customizers:
            try:
                interface = await customizer.customize_interface(profile)
                customized_interfaces.append(interface)
            except Exception as e:
                self.logger.error(f"Error in customizer {type(customizer).__name__}: {e}")
        
        # Merge the interfaces to create a comprehensive customization
        if customized_interfaces:
            # For now, return the first one; in a more sophisticated implementation,
            # we would merge the preferences from all customizers
            final_interface = await self._merge_interfaces(customized_interfaces, profile)
            self.active_interfaces[user_id] = final_interface
            return final_interface
        
        return None
    
    async def _merge_interfaces(
        self, 
        interfaces: List[CustomizedInterface], 
        profile: UserProfile
    ) -> CustomizedInterface:
        """Merge multiple interface customizations into one."""
        if not interfaces:
            return None
        
        # Start with the first interface
        merged = interfaces[0]
        
        # Merge preferences from other interfaces based on priority
        # Priority order: Accessibility > Domain > Expertise
        for interface in interfaces[1:]:
            # Accessibility settings take highest priority
            if interface.metadata.get("customization_basis") == "accessibility_needs":
                merged.preferences.theme = interface.preferences.theme
                merged.preferences.accessibility_features = interface.preferences.accessibility_features
                # Merge accessibility features
                for feat in interface.preferences.accessibility_features:
                    if feat not in merged.preferences.accessibility_features:
                        merged.preferences.accessibility_features.append(feat)
            
            # Domain settings take medium priority
            elif interface.metadata.get("customization_basis") == "domain_preference":
                # Only override if not set by accessibility
                if merged.preferences.theme == ThemeType.AUTO:
                    merged.preferences.theme = interface.preferences.theme
                # Add domain-specific components
                for comp in interface.preferences.ui_components:
                    # Avoid duplicating components
                    if not any(c.name == comp.name for c in merged.preferences.ui_components):
                        merged.preferences.ui_components.append(comp)
            
            # Expertise settings take lowest priority
            elif interface.metadata.get("customization_basis") == "expertise_level":
                # Only set if not already set by higher priority
                if merged.preferences.layout == LayoutType.STANDARD:
                    merged.preferences.layout = interface.preferences.layout
                if merged.preferences.font_size == FontSize.MEDIUM:
                    merged.preferences.font_size = interface.preferences.font_size
        
        # Update metadata
        merged.metadata["merged_from"] = [iface.metadata.get("customization_basis", "unknown") for iface in interfaces]
        merged.last_accessed = datetime.now()
        
        return merged
    
    async def update_interface_component(
        self, 
        user_id: str, 
        component_name: str, 
        new_position: Optional[Dict[str, int]] = None,
        new_size: Optional[Dict[str, int]] = None,
        visibility: Optional[bool] = None
    ) -> bool:
        """Update a specific UI component for a user."""
        interface = self.active_interfaces.get(user_id)
        if not interface:
            interface = await self.get_customized_interface(user_id)
            if not interface:
                return False
        
        # Find the component
        for component in interface.preferences.ui_components:
            if component.name == component_name:
                # Update properties
                if new_position is not None:
                    component.position = new_position
                if new_size is not None:
                    component.size = new_size
                if visibility is not None:
                    component.visibility = visibility
                
                # Update timestamp
                interface.last_accessed = datetime.now()
                return True
        
        return False
    
    async def get_interface_css(self, user_id: str) -> str:
        """Generate CSS for the user's customized interface."""
        interface = await self.get_customized_interface(user_id)
        if not interface:
            return self._get_default_css()
        
        css_parts = []
        
        # Theme-based colors
        if interface.preferences.theme == ThemeType.DARK:
            css_parts.append("""
                :root {
                    --bg-primary: #1e1e1e;
                    --bg-secondary: #2d2d2d;
                    --text-primary: #ffffff;
                    --text-secondary: #cccccc;
                    --border-color: #444444;
                    --accent-color: #007acc;
                }
            """)
        elif interface.preferences.theme == ThemeType.LIGHT:
            css_parts.append("""
                :root {
                    --bg-primary: #ffffff;
                    --bg-secondary: #f5f5f5;
                    --text-primary: #000000;
                    --text-secondary: #444444;
                    --border-color: #dddddd;
                    --accent-color: #007acc;
                }
            """)
        elif interface.preferences.theme == ThemeType.HIGH_CONTRAST:
            css_parts.append("""
                :root {
                    --bg-primary: #000000;
                    --bg-secondary: #000000;
                    --text-primary: #ffffff;
                    --text-secondary: #ffffff;
                    --border-color: #ffffff;
                    --accent-color: #ffff00;
                }
            """)
        else:  # Auto or default
            css_parts.append("""
                :root {
                    --bg-primary: #ffffff;
                    --bg-secondary: #f5f5f5;
                    --text-primary: #000000;
                    --text-secondary: #444444;
                    --border-color: #dddddd;
                    --accent-color: #007acc;
                }
                
                @media (prefers-color-scheme: dark) {
                    :root {
                        --bg-primary: #1e1e1e;
                        --bg-secondary: #2d2d2d;
                        --text-primary: #ffffff;
                        --text-secondary: #cccccc;
                        --border-color: #444444;
                        --accent-color: #007acc;
                    }
                }
            """)
        
        # Font size settings
        font_size_map = {
            FontSize.EXTRA_SMALL: "0.7rem",
            FontSize.SMALL: "0.85rem",
            FontSize.MEDIUM: "1rem",
            FontSize.LARGE: "1.2rem",
            FontSize.EXTRA_LARGE: "1.5rem"
        }
        font_size = font_size_map.get(interface.preferences.font_size, "1rem")
        
        css_parts.append(f"""
            body {{
                font-size: {font_size};
                background-color: var(--bg-primary);
                color: var(--text-primary);
            }}
            
            .interface-component {{
                border: 1px solid var(--border-color);
                border-radius: 4px;
                padding: 8px;
            }}
            
            .button, button {{
                font-size: {font_size};
            }}
            
            .input, input, textarea {{
                font-size: {font_size};
                background-color: var(--bg-secondary);
                color: var(--text-primary);
                border: 1px solid var(--border-color);
            }}
        """)
        
        # Layout adjustments
        if interface.preferences.layout == LayoutType.COMPACT:
            css_parts.append("""
                .interface-component {
                    padding: 4px;
                    margin: 2px;
                }
                
                .button, button {
                    padding: 4px 8px;
                    margin: 1px;
                }
            """)
        elif interface.preferences.layout == LayoutType.SPACIOUS:
            css_parts.append("""
                .interface-component {
                    padding: 12px;
                    margin: 6px;
                }
                
                .button, button {
                    padding: 8px 16px;
                    margin: 3px;
                }
            """)
        
        # Accessibility features
        if AccessibilityFeature.HIGH_CONTRAST_MODE in interface.preferences.accessibility_features:
            css_parts.append("""
                * {
                    border: 2px solid !important;
                }
                
                .interface-component {
                    border-width: 2px !important;
                }
            """)
        
        if AccessibilityFeature.REDUCED_ANIMATION in interface.preferences.accessibility_features:
            css_parts.append("""
                * {
                    animation-duration: 0.01ms !important;
                    animation-iteration-count: 1 !important;
                    transition-duration: 0.01ms !important;
                }
            """)
        
        # Add any custom CSS from preferences
        if interface.preferences.custom_css:
            css_parts.append(interface.preferences.custom_css)
        
        return "\n".join(css_parts)
    
    def _get_default_css(self) -> str:
        """Get default CSS if no customization is available."""
        return """
            :root {
                --bg-primary: #ffffff;
                --bg-secondary: #f5f5f5;
                --text-primary: #000000;
                --text-secondary: #444444;
                --border-color: #dddddd;
                --accent-color: #007acc;
            }
            
            body {
                font-family: Arial, sans-serif;
                font-size: 1rem;
                background-color: var(--bg-primary);
                color: var(--text-primary);
                margin: 0;
                padding: 10px;
            }
            
            .interface-component {
                border: 1px solid var(--border-color);
                border-radius: 4px;
                padding: 8px;
                margin: 4px 0;
            }
            
            .button, button {
                background-color: var(--accent-color);
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                cursor: pointer;
                font-size: 1rem;
            }
            
            .input, input, textarea {
                font-size: 1rem;
                padding: 6px;
                border: 1px solid var(--border-color);
                border-radius: 4px;
                background-color: var(--bg-secondary);
                color: var(--text-primary);
            }
        """
    
    async def get_interface_config(self, user_id: str) -> Dict[str, Any]:
        """Get the complete interface configuration for a user."""
        interface = await self.get_customized_interface(user_id)
        if not interface:
            return {}
        
        # Convert interface to dictionary format
        config = {
            "user_id": interface.user_id,
            "interface_id": interface.interface_id,
            "theme": interface.preferences.theme.value,
            "layout": interface.preferences.layout.value,
            "font_size": interface.preferences.font_size.value,
            "color_palette": interface.preferences.color_palette.value,
            "language": interface.preferences.language,
            "timezone": interface.preferences.timezone,
            "accessibility_features": [f.value for f in interface.preferences.accessibility_features],
            "ui_components": [
                {
                    "name": comp.name,
                    "component_type": comp.component_type,
                    "position": comp.position,
                    "size": comp.size,
                    "visibility": comp.visibility,
                    "accessibility_label": comp.accessibility_label,
                    "shortcut_key": comp.shortcut_key
                }
                for comp in interface.preferences.ui_components
            ],
            "css": await self.get_interface_css(user_id),
            "metadata": interface.metadata,
            "last_accessed": interface.last_accessed.isoformat()
        }
        
        return config


class InterfaceCustomizationTool:
    """Tool for managing interface customization."""
    
    def __init__(self, customization_engine: InterfaceCustomizationEngine):
        self.customization_engine = customization_engine
        self.logger = logging.getLogger(f"{__name__}.InterfaceCustomizationTool")
    
    async def get_interface_config(self, user_id: str) -> Dict[str, Any]:
        """Get the interface configuration for a user."""
        try:
            config = await self.customization_engine.get_interface_config(user_id)
            if config:
                return {
                    "success": True,
                    "user_id": user_id,
                    "interface_config": config
                }
            else:
                return {
                    "success": False,
                    "error": f"No interface configuration found for user {user_id}",
                    "user_id": user_id
                }
        except Exception as e:
            self.logger.error(f"Error getting interface config: {e}")
            return {
                "success": False,
                "error": f"Error getting interface config: {str(e)}",
                "user_id": user_id
            }
    
    async def get_interface_css(self, user_id: str) -> Dict[str, Any]:
        """Get the CSS for a user's customized interface."""
        try:
            css = await self.customization_engine.get_interface_css(user_id)
            return {
                "success": True,
                "user_id": user_id,
                "css": css
            }
        except Exception as e:
            self.logger.error(f"Error getting interface CSS: {e}")
            return {
                "success": False,
                "error": f"Error getting interface CSS: {str(e)}",
                "user_id": user_id
            }
    
    async def update_component(
        self, 
        user_id: str, 
        component_name: str, 
        new_position: Optional[Dict[str, int]] = None,
        new_size: Optional[Dict[str, int]] = None,
        visibility: Optional[bool] = None
    ) -> Dict[str, Any]:
        """Update a specific UI component."""
        try:
            success = await self.customization_engine.update_interface_component(
                user_id, component_name, new_position, new_size, visibility
            )
            if success:
                return {
                    "success": True,
                    "message": f"Updated component {component_name} for user {user_id}",
                    "user_id": user_id,
                    "component_name": component_name
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to update component {component_name} for user {user_id}",
                    "user_id": user_id,
                    "component_name": component_name
                }
        except Exception as e:
            self.logger.error(f"Error updating component: {e}")
            return {
                "success": False,
                "error": f"Error updating component: {str(e)}",
                "user_id": user_id,
                "component_name": component_name
            }
    
    def to_param(self) -> Dict[str, Any]:
        """Convert to parameter format for tool registration."""
        return {
            "type": "function",
            "function": {
                "name": "interface_customization_tool",
                "description": "Manage user interface customization settings",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["get_config", "get_css", "update_component"],
                            "description": "Action to perform"
                        },
                        "user_id": {
                            "type": "string",
                            "description": "ID of the user"
                        },
                        "component_name": {
                            "type": "string",
                            "description": "Name of the component (for update action)"
                        },
                        "new_position": {
                            "type": "object",
                            "properties": {
                                "x": {"type": "integer"},
                                "y": {"type": "integer"}
                            },
                            "description": "New position for the component (for update action)"
                        },
                        "new_size": {
                            "type": "object",
                            "properties": {
                                "width": {"type": "integer"},
                                "height": {"type": "integer"}
                            },
                            "description": "New size for the component (for update action)"
                        },
                        "visibility": {
                            "type": "boolean",
                            "description": "Visibility of the component (for update action)"
                        }
                    },
                    "required": ["action", "user_id"]
                }
            }
        }


# Example usage
if __name__ == "__main__":
    import asyncio
    
    async def example():
        # This example would require a profile manager
        # For demonstration, we'll create a simplified version
        
        # Create a basic customization engine
        from weebot.infrastructure.persistence.profile_storage import InMemoryUserProfileStorage
        from weebot.application.services.profile_manager import UserProfileManager
        
        storage = InMemoryUserProfileStorage()
        profile_manager = UserProfileManager(storage)
        
        # Create a sample user profile
        user_profile = await profile_manager.create_profile(
            user_id="user_123",
            name="Alex Johnson",
            email="alex@example.com"
        )
        
        # Add some preferences to the profile
        await profile_manager.update_preference(
            user_id="user_123",
            category=PreferenceCategory.INTERFACE_CUSTOMIZATION,
            key="theme",
            value="dark"
        )
        
        await profile_manager.update_preference(
            user_id="user_123",
            category=PreferenceCategory.INTERFACE_CUSTOMIZATION,
            key="layout_preference",
            value="compact"
        )
        
        # Create the customization engine
        customization_engine = InterfaceCustomizationEngine(profile_manager)
        
        print("Generating customized interface...")
        
        # Get interface configuration
        config = await customization_engine.get_interface_config("user_123")
        
        print(f"Interface configuration for user_123:")
        print(f"Theme: {config.get('theme', 'N/A')}")
        print(f"Layout: {config.get('layout', 'N/A')}")
        print(f"Font size: {config.get('font_size', 'N/A')}")
        print(f"Number of components: {len(config.get('ui_components', []))}")
        print(f"Accessibility features: {config.get('accessibility_features', [])}")
        
        # Get CSS
        css = await customization_engine.get_interface_css("user_123")
        print(f"\nGenerated CSS length: {len(css)} characters")
        
        # Update a component
        success = await customization_engine.update_interface_component(
            user_id="user_123",
            component_name="workspace",
            new_position={"x": 100, "y": 50},
            visibility=True
        )
        print(f"\nComponent update successful: {success}")
        
        # Get updated config
        updated_config = await customization_engine.get_interface_config("user_123")
        workspace_comp = next(
            (comp for comp in updated_config.get('ui_components', []) if comp['name'] == 'workspace'), 
            None
        )
        if workspace_comp:
            print(f"Updated workspace position: {workspace_comp['position']}")
        
        print("\nExample completed successfully!")
    
    asyncio.run(example())