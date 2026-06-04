"""Unit tests for Media Delivery on Messaging (Hermes M5).

Covers:
- extract_media detects bare absolute file paths
- [[audio_as_voice]] and [[as_document]] directives
- Media file path validation (extension filtering)
- Clean text after stripping paths and directives

Note: imports are inside test methods to avoid slow langchain import at collection time.
"""
import pytest


class TestMediaExtraction:
    """Validates GatewayAdapter.extract_media()."""

    def test_no_media_returns_empty(self):
        """Plain text with no file paths returns empty media list."""
        from weebot.interfaces.gateways.base import GatewayAdapter

        text, paths, as_doc, as_voice = GatewayAdapter.extract_media(
            "Hello, how can I help you?"
        )
        assert text == "Hello, how can I help you?"
        assert paths == []
        assert as_doc is False
        assert as_voice is False

    def test_detects_png_path(self):
        """Bare absolute path to a .png file is detected."""
        from weebot.interfaces.gateways.base import GatewayAdapter

        text, paths, as_doc, as_voice = GatewayAdapter.extract_media(
            "Here is your chart:\n/home/user/chart.png"
        )
        assert len(paths) == 1
        assert "chart.png" in paths[0]

    def test_detects_multiple_paths(self):
        """Multiple file paths are all detected."""
        from weebot.interfaces.gateways.base import GatewayAdapter

        text, paths, as_doc, as_voice = GatewayAdapter.extract_media(
            "Image 1: /tmp/img1.jpg\nImage 2: /tmp/img2.png"
        )
        assert len(paths) == 2
        assert "img1.jpg" in paths[0]
        assert "img2.png" in paths[1]

    def test_paths_are_stripped_from_text(self):
        """File paths are removed from the cleaned text."""
        from weebot.interfaces.gateways.base import GatewayAdapter

        text, paths, as_doc, as_voice = GatewayAdapter.extract_media(
            "Result:\n/tmp/output.png\nDone."
        )
        assert "output.png" not in text
        assert "Result:" in text
        assert "Done." in text

    def test_detect_as_document_directive(self):
        """[[as_document]] directive sets as_document flag and is stripped."""
        from weebot.interfaces.gateways.base import GatewayAdapter

        text, paths, as_doc, as_voice = GatewayAdapter.extract_media(
            "/tmp/report.png\n[[as_document]]"
        )
        assert as_doc is True
        assert "[[as_document]]" not in text

    def test_detect_audio_as_voice_directive(self):
        """[[audio_as_voice]] directive sets as_voice flag."""
        from weebot.interfaces.gateways.base import GatewayAdapter

        text, paths, as_doc, as_voice = GatewayAdapter.extract_media(
            "/tmp/recording.mp3\n[[audio_as_voice]]"
        )
        assert as_voice is True

    def test_ignores_non_media_extensions(self):
        """Non-media file extensions are not included."""
        from weebot.interfaces.gateways.base import GatewayAdapter

        text, paths, as_doc, as_voice = GatewayAdapter.extract_media(
            "File: /tmp/data.bin\nConfig: /tmp/.env"
        )
        assert len(paths) == 0

    def test_both_directives(self):
        """Both directives can be present simultaneously."""
        from weebot.interfaces.gateways.base import GatewayAdapter

        text, paths, as_doc, as_voice = GatewayAdapter.extract_media(
            "/tmp/audio.mp3\n[[audio_as_voice]]\n[[as_document]]"
        )
        assert as_doc is True
        assert as_voice is True
