"""HTML to LLM-ready markdown converter."""
from __future__ import annotations

import logging
import re
from typing import Optional

from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)


class ContentExtractor:
    """Extract clean markdown from HTML for LLM consumption."""

    # Elements to remove (noise)
    NOISE_ELEMENTS = [
        "script", "style", "nav", "footer", "header",
        "aside", "advertisement", "ad", "iframe",
        "noscript", "svg", "canvas", "video", "audio",
    ]

    # Elements that are likely main content
    CONTENT_INDICATORS = [
        "article", "main", "content", "post", "entry",
    ]

    def __init__(self, max_tokens: int = 4000, preserve_links: bool = True):
        """Initialize extractor.

        Args:
            max_tokens: Approximate max tokens for output (approx 4 chars/token)
            preserve_links: Whether to preserve link URLs in markdown
        """
        self.max_chars = max_tokens * 4  # Rough approximation
        self.preserve_links = preserve_links

    def extract_markdown(self, html: str, url: Optional[str] = None) -> str:
        """Convert HTML to clean markdown.

        Args:
            html: Raw HTML content
            url: Source URL for resolving relative links

        Returns:
            Clean markdown string
        """
        soup = BeautifulSoup(html, "html.parser")

        # Remove noise elements
        for element_name in self.NOISE_ELEMENTS:
            for element in soup.find_all(element_name):
                element.decompose()

        # Find main content area
        main_content = self._find_main_content(soup)

        # Convert to markdown
        markdown = self._convert_to_markdown(main_content, url)

        # Clean up
        markdown = self._clean_markdown(markdown)

        # Truncate if needed
        if len(markdown) > self.max_chars:
            markdown = self._truncate(markdown)

        return markdown

    def _find_main_content(self, soup: BeautifulSoup) -> Tag:
        """Find the main content area of the page."""
        # Try common content selectors
        for selector in ["main", "article", "[role='main']", ".content", "#content",
                        ".post-content", ".entry-content", ".article-body"]:
            element = soup.select_one(selector)
            if element:
                return element

        # Fallback: body or html
        body = soup.find("body")
        if body:
            return body

        return soup

    def _convert_to_markdown(self, element: Tag, base_url: Optional[str] = None) -> str:
        """Convert BeautifulSoup element to markdown."""
        lines = []

        # Process direct children to avoid duplication
        for child in element.children:
            if isinstance(child, Tag):
                text = self._tag_to_markdown(child, base_url)
                if text:
                    lines.append(text)

        return "\n\n".join(lines)

    def _tag_to_markdown(self, tag: Tag, base_url: Optional[str] = None) -> Optional[str]:
        """Convert a single tag to markdown."""
        name = tag.name
        text = tag.get_text(strip=True)

        if not text and name not in ["img", "hr", "br"]:
            return None

        # Headings
        if name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
            level = int(name[1])
            return f"{'#' * level} {text}"

        # Paragraph
        if name == "p":
            # Process inline elements like links, code
            content = self._process_inline_elements(tag, base_url)
            return content if content else text

        # Links as block (when they contain block elements)
        if name == "a":
            href = tag.get("href", "")
            if self.preserve_links and href:
                return f"[{text}]({href})"
            return text

        # Unordered lists
        if name == "ul":
            items = []
            for li in tag.find_all("li", recursive=False):
                item_text = li.get_text(strip=True)
                if item_text:
                    items.append(f"- {item_text}")
            return "\n".join(items) if items else None

        # Ordered lists
        if name == "ol":
            items = []
            for i, li in enumerate(tag.find_all("li", recursive=False), 1):
                item_text = li.get_text(strip=True)
                if item_text:
                    items.append(f"{i}. {item_text}")
            return "\n".join(items) if items else None

        # Code blocks
        if name == "pre":
            code = tag.get_text()
            # Try to detect language
            lang = ""
            code_tag = tag.find("code")
            if code_tag and code_tag.get("class"):
                for cls in code_tag.get("class"):
                    if cls.startswith("language-"):
                        lang = cls.replace("language-", "")
                        break
            return f"```{lang}\n{code}\n```"

        # Tables
        if name == "table":
            return self._table_to_markdown(tag)

        # Blockquote
        if name == "blockquote":
            lines = text.split("\n")
            quoted = "\n".join(f"> {line}" for line in lines if line.strip())
            return quoted

        # Horizontal rule
        if name == "hr":
            return "---"

        # Images
        if name == "img":
            alt = tag.get("alt", "")
            src = tag.get("src", "")
            if src:
                return f"![{alt}]({src})"
            return None

        # Div with meaningful content - recurse
        if name in ["div", "section"]:
            lines = []
            for child in tag.children:
                if isinstance(child, Tag):
                    child_text = self._tag_to_markdown(child, base_url)
                    if child_text:
                        lines.append(child_text)
            return "\n\n".join(lines) if lines else None

        return None

    def _process_inline_elements(self, tag: Tag, base_url: Optional[str] = None) -> str:
        """Process inline elements within a paragraph."""
        parts = []
        for child in tag.children:
            if isinstance(child, Tag):
                if child.name == "a" and self.preserve_links:
                    href = child.get("href", "")
                    text = child.get_text(strip=True)
                    if href and text:
                        parts.append(f"[{text}]({href})")
                    elif text:
                        parts.append(text)
                elif child.name == "code":
                    code_text = child.get_text(strip=True)
                    parts.append(f"`{code_text}`")
                elif child.name == "strong" or child.name == "b":
                    parts.append(f"**{child.get_text(strip=True)}**")
                elif child.name == "em" or child.name == "i":
                    parts.append(f"*{child.get_text(strip=True)}*")
                else:
                    parts.append(child.get_text(strip=True))
            else:
                parts.append(str(child))

        return "".join(parts).strip()

    def _table_to_markdown(self, table: Tag) -> str:
        """Convert table to markdown format."""
        rows = []

        # Header
        thead = table.find("thead")
        if thead:
            header_row = thead.find("tr")
            if header_row:
                cells = [th.get_text(strip=True) for th in header_row.find_all(["th", "td"])]
                if cells:
                    rows.append("| " + " | ".join(cells) + " |")
                    rows.append("| " + " | ".join(["---"] * len(cells)) + " |")

        # Body
        tbody = table.find("tbody")
        if tbody:
            for tr in tbody.find_all("tr"):
                cells = [td.get_text(strip=True) for td in tr.find_all("td")]
                if cells:
                    rows.append("| " + " | ".join(cells) + " |")

        # If no thead/tbody, process all rows
        if not rows:
            for tr in table.find_all("tr"):
                cells = [cell.get_text(strip=True) for cell in tr.find_all(["td", "th"])]
                if cells:
                    rows.append("| " + " | ".join(cells) + " |")

        return "\n".join(rows) if rows else None

    def _clean_markdown(self, markdown: str) -> str:
        """Clean up markdown formatting."""
        # Remove excessive blank lines
        markdown = re.sub(r'\n{3,}', '\n\n', markdown)

        # Remove leading/trailing whitespace
        markdown = markdown.strip()

        # Fix list formatting - remove duplicate list markers
        lines = markdown.split('\n')
        cleaned = []
        for line in lines:
            # Remove duplicate list markers
            line = re.sub(r'^(\s*)-\s*-\s+', r'\1- ', line)
            cleaned.append(line)

        return '\n'.join(cleaned)

    def _truncate(self, markdown: str) -> str:
        """Truncate markdown to max length, preserving structure."""
        # Try to truncate at a logical boundary
        truncated = markdown[:self.max_chars]

        # Find last complete paragraph/section
        last_boundary = max(
            truncated.rfind('\n\n'),
            truncated.rfind('.\n'),
            truncated.rfind('```\n'),
        )

        if last_boundary > self.max_chars * 0.5:  # At least half was captured
            truncated = truncated[:last_boundary + 1]

        return truncated + "\n\n[Content truncated...]"

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count for text.

        Uses a rough approximation of 4 characters per token.
        """
        return len(text) // 4
