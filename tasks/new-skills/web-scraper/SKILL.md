---
name: web-scraper
description: "Use when the user asks to scrape, extract, or collect data from websites. Trigger keywords: scrape, extract data, crawl, collect from web."
license: MIT
---

# Web Scraper

## When to use
The user wants to extract structured data from web pages — product listings, articles, tables, or search results.

## Workflow

1. **Check robots.txt** — always verify the site allows scraping before proceeding.
2. **Fetch the page** — use `python_execute` with `requests` + `BeautifulSoup`, or browser for JS-heavy pages.
3. **Identify data patterns** — inspect HTML to find CSS selectors for target data.
4. **Extract structured data:** text content, links, tables, image URLs.
5. **Apply rate limiting** — minimum 1-second delay between requests.
6. **Handle pagination** — detect and follow "next page" links.
7. **Save output** — CSV for tabular data, JSON for nested data, Markdown for articles.

## Safety rules
- ALWAYS check robots.txt first
- NEVER scrape at high frequency (max 1 request/second)
- NEVER attempt to bypass authentication or paywalls
- NEVER scrape personal data, emails, or phone numbers
- ALWAYS respect 429 responses with exponential backoff
- Set a reasonable User-Agent header

## Tool guidance
- `python_execute`: Primary tool — use `requests`, `BeautifulSoup`, `lxml`.
- `browser`: Use for JS-rendered pages that `requests` can't handle.

## Output
- Structured data file (CSV or JSON)
- Summary: pages scraped, records extracted, time taken
