"""BM25SkillRetriever matches words regardless of case and punctuation.

It used to split on whitespace only, so ``denied,`` never matched ``denied`` and
``Access`` never matched ``access``: "moli_fetch got 403 access denied" retrieved
code-review instead of camofox-browser.
"""

from __future__ import annotations

from dataclasses import dataclass

from weebot.application.services.bm25_skill_retriever import BM25SkillRetriever, _tokenize


@dataclass
class _Skill:
    name: str
    description: str
    content: str = ""


class _Registry:
    def __init__(self, *skills: _Skill):
        self._skills = {s.name: s for s in skills}

    def list_names(self):
        return list(self._skills)

    def get(self, name):
        return self._skills.get(name)


def test_tokens_are_lowercase_words_without_punctuation():
    assert _tokenize('Blocked: "Access denied", HTTP 403/429!') == [
        "blocked", "access", "denied", "http", "403", "429",
    ]
    assert _tokenize("use moli_fetch or camofox-browser") == [
        "use", "moli_fetch", "or", "camofox", "browser",
    ]


async def test_case_and_punctuation_do_not_hide_a_skill():
    registry = _Registry(
        _Skill("stealth", 'Read pages that block bots (HTTP 403/429, "access denied").'),
        _Skill("review", "Review code changes and pull requests for bugs."),
        _Skill("video", "Make videos from code: title cards, captions."),
    )
    retriever = BM25SkillRetriever(registry)
    matches = await retriever.retrieve("Read the page - moli_fetch got 403 Access Denied.")
    assert matches[0].skill_name == "stealth"
