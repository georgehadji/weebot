"""Unit tests for HeuristicRouter task analysis."""
import pytest
from weebot.tools.heuristic_router import HeuristicRouter


@pytest.fixture
def router():
    return HeuristicRouter()


class TestRoutingDecisions:
    def test_file_task_routes_to_powershell(self, router):
        result = router.analyze_task("delete the old log file from workspace")
        assert result["primary_tool"] == "powershell"

    def test_web_task_routes_to_browser(self, router):
        result = router.analyze_task("navigate to the website and click login")
        assert result["primary_tool"] == "browser"

    def test_process_management_routes_to_powershell(self, router):
        result = router.analyze_task("kill the stuck process")
        assert result["primary_tool"] == "powershell"

    def test_scraping_routes_to_browser(self, router):
        result = router.analyze_task("scrape product data from online store")
        assert result["primary_tool"] == "browser"

    def test_directory_task_routes_to_powershell(self, router):
        result = router.analyze_task("list the directory contents")
        assert result["primary_tool"] == "powershell"

    def test_url_download_routes_to_browser(self, router):
        result = router.analyze_task("download file from web url")
        assert result["primary_tool"] == "browser"


class TestResultStructure:
    def test_result_has_required_keys(self, router):
        result = router.analyze_task("delete a file")
        assert "primary_tool" in result
        assert "confidence" in result
        assert "reasoning" in result
        assert "suggested_sequence" in result

    def test_primary_tool_is_valid_value(self, router):
        result = router.analyze_task("navigate to website")
        assert result["primary_tool"] in ("powershell", "browser")

    def test_confidence_is_between_zero_and_one(self, router):
        result = router.analyze_task("delete files from directory")
        assert 0.0 <= result["confidence"] <= 1.0

    def test_suggested_sequence_has_three_items(self, router):
        # Router now proposes a 3-tool fallback chain (primary + alternatives).
        result = router.analyze_task("delete files")
        assert len(result["suggested_sequence"]) == 3

    def test_suggested_sequence_leads_with_local_and_includes_web(self, router):
        # A local-file task leads with powershell and offers web fallbacks.
        result = router.analyze_task("delete files")
        assert "powershell" in result["suggested_sequence"]
        assert "web_search" in result["suggested_sequence"]

    def test_primary_tool_is_first_in_sequence(self, router):
        result = router.analyze_task("delete files from directory")
        assert result["suggested_sequence"][0] == result["primary_tool"]


class TestEdgeCases:
    def test_empty_task_returns_safe_default(self, router):
        # With no indicators the router defaults to a research/web tool.
        result = router.analyze_task("")
        assert result["primary_tool"] in ("powershell", "browser", "web_search", "vane_search")

    def test_mixed_task_returns_highest_scoring_tool(self, router):
        # Contains both ps and browser keywords — ps should win with more matches
        result = router.analyze_task("delete file from directory and save to disk")
        assert result["primary_tool"] == "powershell"

    def test_case_insensitive_matching(self, router):
        result_lower = router.analyze_task("delete file")
        result_upper = router.analyze_task("DELETE FILE")
        assert result_lower["primary_tool"] == result_upper["primary_tool"]
