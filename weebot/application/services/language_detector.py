"""LanguageDetector — detects the language of user input (Enhancement 7).

Uses a lightweight character-n-gram approach with no external dependencies.
Detects common languages: English, Greek, French, German, Spanish, Italian,
Portuguese, Russian, Chinese, Japanese, Arabic.

The detected language is stored in SessionContext.detected_language and
injected into the system prompt using the XML prompt architecture from
Enhancement 1.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Unicode block ranges for quick language detection fallback
_LATIN_COMMON = range(0x0041, 0x007B)  # Basic Latin
_LATIN_EXTENDED = range(0x00C0, 0x0250)  # Latin-1 Supplement + Extended
_GREEK = range(0x0370, 0x0400)
_CYRILLIC = range(0x0400, 0x0500)
_ARABIC = range(0x0600, 0x0700)
_CJK = [range(0x4E00, 0xA000), range(0x3400, 0x4DC0)]  # CJK Unified
_JAPANESE_KANA = range(0x3040, 0x3100)  # Hiragana + Katakana


# Common words per language for scoring
_LANGUAGE_MARKERS: dict[str, list[str]] = {
    "en": ["the", "is", "are", "and", "for", "this", "that", "with", "from", "was", "were", "been", "have", "has", "had", "not", "but", "what", "which", "their", "them", "will", "would", "could", "should", "about", "there", "each", "how", "all", "your", "our", "its", "also", "very", "just", "than"],
    "el": ["και", "το", "τη", "τα", "στο", "από", "για", "με", "είναι", "την", "που", "του", "θα", "να", "έχει", "δεν", "ήταν", "τους", "στην", "αυτό", "ότι", "επίσης"],
    "fr": ["le", "la", "les", "des", "est", "sont", "pour", "avec", "dans", "sur", "pas", "une", "que", "qui", "nous", "vous", "ils", "ont", "fait", "mais", "tout", "plus", "être", "avoir", "cette", "leur", "aussi"],
    "de": ["der", "die", "das", "und", "ist", "sind", "für", "mit", "auf", "ein", "eine", "sich", "auch", "werden", "nicht", "sie", "wie", "zum", "zur", "bei", "hat", "wird", "durch", "gegen", "nach", "dies"],
    "es": ["el", "la", "los", "las", "es", "son", "para", "con", "por", "del", "una", "como", "más", "pero", "sus", "vez", "este", "entre", "está", "muy", "sin", "qué", "han", "cada", "ser"],
    "it": ["il", "la", "le", "gli", "è", "sono", "per", "con", "che", "una", "del", "della", "delle", "degli", "nel", "sul", "sulla", "nell", "sugli", "come", "più", "ma", "anche", "quando", "sua", "suo"],
    "pt": ["o", "a", "os", "as", "é", "são", "para", "com", "por", "uma", "mais", "mas", "como", "foi", "seu", "sua", "cada", "muito", "entre", "este", "pode", "ser", "seus", "sem"],
    "ru": ["и", "в", "на", "с", "что", "это", "не", "по", "для", "от", "как", "его", "она", "они", "но", "также", "быть", "из", "у", "к", "о", "так", "за"],
    "zh": ["的", "是", "在", "了", "有", "和", "不", "也", "就", "都", "要", "对", "到", "与", "而", "这", "那", "以", "说", "会", "很", "为", "能", "及"],
    "ja": ["は", "が", "を", "に", "の", "と", "で", "も", "です", "ます", "た", "いる", "ある", "する", "ない", "この", "その", "あの", "どの", "彼", "私", "それ", "から"],
    "ar": ["في", "من", "على", "إلى", "هذا", "كان", "أن", "ما", "هل", "مع", "هذه", "عند", "كل", "كانت", "غير", "قد", "لم", "عن", "إذا", "قال", "لقد", "كانوا"],
}


class LanguageDetector:
    """Detect the language of a text string."""

    @staticmethod
    def detect(text: str) -> str:
        """Return an ISO 639-1 language code for *text*.

        Returns 'en' as a safe default when confidence is low.
        """
        if not text.strip():
            return "en"

        # 1. Check Unicode blocks for CJK / Greek / Cyrillic / Arabic
        script_score: dict[str, int] = {}
        for char in text:
            cp = ord(char)
            if cp in _GREEK:
                script_score["el"] = script_score.get("el", 0) + 1
            elif cp in _CYRILLIC:
                script_score["ru"] = script_score.get("ru", 0) + 1
            elif cp in _ARABIC:
                script_score["ar"] = script_score.get("ar", 0) + 1
            elif cp in _JAPANESE_KANA:
                script_score["ja"] = script_score.get("ja", 0) + 1
            elif any(block.start <= cp < block.stop for block in _CJK):
                script_score["zh"] = script_score.get("zh", 0) + 1

        # If a non-Latin script dominates, return it
        if script_score:
            dominant = max(script_score, key=script_score.get)
            script_ratio = script_score[dominant] / max(len(text), 1)
            if script_ratio > 0.05:  # At least 5% of characters
                return dominant

        # 2. Latin-script: score by common word markers
        words = re.findall(r"[a-zA-Zα-ωά-ώ]+", text.lower())
        if not words:
            return "en"

        word_scores: dict[str, int] = {}
        for lang, markers in _LANGUAGE_MARKERS.items():
            if lang in ("el", "ru", "ar", "zh", "ja"):
                continue  # Already handled by script check
            word_scores[lang] = sum(1 for m in markers if m in words)

        if word_scores:
            best = max(word_scores, key=word_scores.get)
            best_score = word_scores[best]
            if best_score > 0:
                # Check that best has at least as many hits as English
                en_score = word_scores.get("en", 0)
                if best_score >= en_score and best != "en":
                    return best
                if best == "en":
                    return "en"

        return "en"

    @staticmethod
    def get_injection(language_code: str) -> str:
        """Return an XML-scoped language instruction for system prompt injection."""
        if language_code == "en" or not language_code:
            return ""
        language_names = {
            "el": "Greek (Ελληνικά)",
            "fr": "French",
            "de": "German",
            "es": "Spanish",
            "it": "Italian",
            "pt": "Portuguese",
            "ru": "Russian",
            "zh": "Chinese (中文)",
            "ja": "Japanese (日本語)",
            "ar": "Arabic (العربية)",
        }
        name = language_names.get(language_code, language_code.upper())
        return f"\n<language>Respond in {name}</language>"
