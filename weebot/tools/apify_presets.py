"""Curated preset ApifyActorTool instances for common use cases.

Call create_apify_preset_tools(service) to get all 10 pre-wired tools.
Each tool has a purpose-built run_input JSON Schema so the LLM knows what
to pass without consulting the actor's documentation.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from weebot.infrastructure.adapters.apify.apify_service import ApifyService
    from weebot.tools.apify_actor_tool import ApifyActorTool


def _schema(**props: dict) -> dict:
    """Build a JSON Schema object with the given property definitions."""
    required = [k for k, v in props.items() if v.pop("_required", False)]
    return {"type": "object", "properties": props, "required": required}


_PRESETS = [
    {
        "name": "apify_web_scraper",
        "actor_id": "apify/web-scraper",
        "description": (
            "Crawl one or more URLs and extract their text / structured data. "
            "Supports JavaScript-heavy pages via Chromium."
        ),
        "schema": _schema(
            startUrls={
                "_required": True,
                "type": "array",
                "items": {"type": "object", "properties": {"url": {"type": "string"}}},
                "description": "List of start URLs, e.g. [{\"url\": \"https://example.com\"}]",
            },
            maxRequestsPerCrawl={
                "type": "integer",
                "description": "Max pages to crawl (default 10)",
                "default": 10,
            },
        ),
    },
    {
        "name": "apify_google_search",
        "actor_id": "apify/google-search-scraper",
        "description": "Scrape Google Search results pages (SERP) for given queries.",
        "schema": _schema(
            queries={
                "_required": True,
                "type": "string",
                "description": "Newline-separated search queries",
            },
            maxPagesPerQuery={
                "type": "integer",
                "description": "Pages per query (default 1)",
                "default": 1,
            },
            resultsPerPage={
                "type": "integer",
                "description": "Results per page (default 10)",
                "default": 10,
            },
        ),
    },
    {
        "name": "apify_google_images",
        "actor_id": "apify/google-images-scraper",
        "description": "Scrape Google Images results with metadata (URL, title, source).",
        "schema": _schema(
            queries={
                "_required": True,
                "type": "string",
                "description": "Newline-separated image search queries",
            },
            maxImagesPerQuery={
                "type": "integer",
                "description": "Images per query (default 10)",
                "default": 10,
            },
        ),
    },
    {
        "name": "apify_youtube_transcript",
        "actor_id": "supreme_coder/youtube-transcript-scraper",
        "description": "Fetch transcripts and metadata from YouTube videos in bulk.",
        "schema": _schema(
            videoUrls={
                "_required": True,
                "type": "array",
                "items": {"type": "string"},
                "description": "YouTube video URLs or IDs",
            },
            language={
                "type": "string",
                "description": "Transcript language code (default 'en')",
                "default": "en",
            },
        ),
    },
    {
        "name": "apify_linkedin_jobs",
        "actor_id": "curious_coder/linkedin-jobs-scraper",
        "description": "Scrape LinkedIn job listings by keyword, location, and filters.",
        "schema": _schema(
            keyword={
                "_required": True,
                "type": "string",
                "description": "Job title or keyword to search",
            },
            location={
                "type": "string",
                "description": "Location filter (city, country, or 'Remote')",
            },
            maxJobs={
                "type": "integer",
                "description": "Max number of jobs to return (default 25)",
                "default": 25,
            },
        ),
    },
    {
        "name": "apify_twitter_scraper",
        "actor_id": "apidojo/tweet-flash",
        "description": "Scrape tweets from X/Twitter by search query or profile URL.",
        "schema": _schema(
            searchTerms={
                "_required": True,
                "type": "array",
                "items": {"type": "string"},
                "description": "Search queries or hashtags",
            },
            maxTweetsPerQuery={
                "type": "integer",
                "description": "Max tweets per query (default 20)",
                "default": 20,
            },
        ),
    },
    {
        "name": "apify_reddit_scraper",
        "actor_id": "trudax/reddit-scraper-lite",
        "description": "Scrape Reddit posts and comments from subreddits or search.",
        "schema": _schema(
            startUrls={
                "_required": True,
                "type": "array",
                "items": {"type": "object", "properties": {"url": {"type": "string"}}},
                "description": "Subreddit or post URLs to scrape",
            },
            maxComments={
                "type": "integer",
                "description": "Max comments per post (default 10)",
                "default": 10,
            },
        ),
    },
    {
        "name": "apify_website_to_markdown",
        "actor_id": "apify/website-content-crawler",
        "description": (
            "Crawl a website and convert each page to clean Markdown — "
            "ideal for feeding content into LLMs."
        ),
        "schema": _schema(
            startUrls={
                "_required": True,
                "type": "array",
                "items": {"type": "object", "properties": {"url": {"type": "string"}}},
                "description": "Entry point URLs",
            },
            maxCrawlDepth={
                "type": "integer",
                "description": "Max link-follow depth (default 1)",
                "default": 1,
            },
            maxCrawlPages={
                "type": "integer",
                "description": "Max pages to crawl (default 5)",
                "default": 5,
            },
        ),
    },
    {
        "name": "apify_email_finder",
        "actor_id": "misceres/email-scraper",
        "description": "Find email addresses on a website — useful for lead generation.",
        "schema": _schema(
            startUrls={
                "_required": True,
                "type": "array",
                "items": {"type": "object", "properties": {"url": {"type": "string"}}},
                "description": "URLs to scan for email addresses",
            },
            maxDepth={
                "type": "integer",
                "description": "Link crawl depth (default 1)",
                "default": 1,
            },
        ),
    },
    {
        "name": "apify_bing_search",
        "actor_id": "apify/bing-search-scraper",
        "description": "Scrape Bing search results (alternative to Google).",
        "schema": _schema(
            queries={
                "_required": True,
                "type": "string",
                "description": "Newline-separated search queries",
            },
            maxResultsPerQuery={
                "type": "integer",
                "description": "Results per query (default 10)",
                "default": 10,
            },
        ),
    },
]


def create_apify_preset_tools(apify_service: "ApifyService") -> List["ApifyActorTool"]:
    """Return all 10 pre-configured ApifyActorTool instances."""
    from weebot.tools.apify_actor_tool import ApifyActorTool

    tools = []
    for spec in _PRESETS:
        tools.append(
            ApifyActorTool(
                name=spec["name"],
                description=spec["description"],
                parameters=spec["schema"],
                actor_id=spec["actor_id"],
                apify_service=apify_service,
            )
        )
    return tools
