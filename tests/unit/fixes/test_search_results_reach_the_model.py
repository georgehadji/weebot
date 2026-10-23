"""Search tools put their results in `output`, the only part the model reads (F63).

The executor shows the LLM `str(result)`, which is `output`; `data` and
`metadata` go to facts and logs. search_images said only "Found N images" and
vane_search kept its sources in metadata, so the agent never saw a URL.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


async def test_search_images_output_lists_the_urls():
    from weebot.tools import image_search

    ddgs = MagicMock()
    ddgs.__enter__ = lambda s: s
    ddgs.__exit__ = lambda s, *a: False
    ddgs.images.return_value = [
        {"title": "Cat", "image": "https://img.example/cat.jpg", "url": "https://page.example/cat"}
    ]
    with patch.object(image_search, "_DDGS_AVAILABLE", True), patch.object(
        image_search, "DDGS", return_value=ddgs, create=True
    ):
        result = await image_search.ImageSearchTool().execute(query="cat")
    assert "https://img.example/cat.jpg" in str(result)
    assert "https://page.example/cat" in str(result)
