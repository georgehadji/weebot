"""A deterministic :class:`ContentProvider` for tests, demos, and offline runs.

It leaves any pre-authored section ``body_tex`` untouched and fills empty ones
with a small, valid Greek LaTeX placeholder that still exercises math and
cross-references. The production provider (LLM-backed, Opus 4.8 / AUTHORING
profile) satisfies the same port.
"""
from __future__ import annotations

from weebot.application.document.ports import ContentProvider  # noqa: F401 (documents intent)
from weebot.domain.models.book import Book


class StubContentProvider:
    """Fills empty section bodies with valid placeholder Greek LaTeX."""

    def author(self, book: Book) -> Book:
        authored = book.model_copy(deep=True)
        for chapter in authored.chapters:
            for section in chapter.sections:
                if not section.body_tex.strip():
                    section.body_tex = (
                        f"Η ενότητα «{section.title}» παρουσιάζει το θέμα της. "
                        "Ισχύει η σχέση $a^2 + b^2 = c^2$.\n"
                    )
        return authored
