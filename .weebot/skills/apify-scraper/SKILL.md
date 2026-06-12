---
name: apify-scraper
emoji: 🕷️
description: Run Apify web-scraping actors to extract data from websites, search engines, and social media
requires_env:
  - APIFY_API_KEY
homepage: https://apify.com
---

# Apify Web Scraping

Use these tools when you need to extract data from websites, search engines, or social platforms.
All tools run as Apify actors in the cloud — no local browser required.

## Available Tools

| Tool | Actor | Best for |
|------|-------|----------|
| `apify_web_scraper` | apify/web-scraper | Any website, JS-heavy pages |
| `apify_google_search` | apify/google-search-scraper | Google SERP results |
| `apify_google_images` | apify/google-images-scraper | Google Images |
| `apify_youtube_transcript` | supreme_coder/youtube-transcript-scraper | Video transcripts |
| `apify_linkedin_jobs` | curious_coder/linkedin-jobs-scraper | Job listings |
| `apify_twitter_scraper` | apidojo/tweet-flash | Tweets / X posts |
| `apify_reddit_scraper` | trudax/reddit-scraper-lite | Reddit threads |
| `apify_website_to_markdown` | apify/website-content-crawler | LLM-ready markdown |
| `apify_email_finder` | misceres/email-scraper | Lead gen emails |
| `apify_bing_search` | apify/bing-search-scraper | Bing SERP results |

## How to Call a Tool

Pass a `run_input` dict matching the actor's input schema:

```python
# Google search
result = await apify_google_search.execute(
    run_input={"queries": "weebot AI agent\nClaude Code", "maxPagesPerQuery": 1}
)

# Website to markdown
result = await apify_website_to_markdown.execute(
    run_input={"startUrls": [{"url": "https://example.com"}], "maxCrawlPages": 3}
)
```

## Reading Results

Results are in `ToolResult.data["items"]` — a list of dicts from the actor's dataset:

```python
items = result.data["items"]   # list of scraped records
count = result.data["count"]   # total number of items
```

The `output` field contains a JSON preview of the first 50 items.

## Trigger Phrases

Use Apify tools when the user says things like:
- "scrape", "crawl", "extract from website"
- "search Google / Bing for..."
- "get YouTube transcript"
- "find LinkedIn jobs"
- "find emails on this website"
- "get tweets about..."
- "scrape Reddit"

## Custom Actors

For actors not in the preset list, use `ApifyActorTool` directly:

```python
from weebot.tools.apify_actor_tool import ApifyActorTool
tool = ApifyActorTool(
    name="apify_my_actor",
    description="...",
    parameters={"type": "object", "properties": {"run_input": {"type": "object"}}},
    actor_id="username/actor-name",
    apify_service=service,
)
```

Find actor IDs at https://apify.com/store
