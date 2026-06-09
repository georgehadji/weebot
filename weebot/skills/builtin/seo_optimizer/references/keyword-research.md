# Keyword Research Methodology

## 1. Identify the Target Keyword
- Extract from page `<title>`, `<h1>`, first paragraph
- If user specified a keyword, use that as primary
- Classify intent:
  - **Informational**: "how to...", "what is...", "guide to..."
  - **Transactional**: "buy...", "best...", "...review", "...pricing"
  - **Navigational**: brand name, product name, "login"
  - **Commercial**: "...vs...", "top...", "...comparison"

## 2. SERP Analysis (Top 5)
Run `web_search` with the primary keyword. For each of the top 5 results:
- **Fetch the page** via `web_fetch`
- Extract: `<title>`, meta description, `<h1>`, word count, structured data types
- Note common patterns:
  - Do they all have a certain section (e.g., FAQ, pricing table)?
  - Do they include images, videos, tables?
  - How do they structure their content (listicle, guide, comparison)?
  - What's the average word count?

## 3. Related Keywords Discovery
- Search for variations: `"{keyword} guide"`, `"{keyword} tutorial"`, `"best {keyword}"`
- Look at Google's "People also ask" and "Related searches" sections
- Note question-based keywords (starting with "how", "what", "why", "when")
- Note long-tail keywords (5+ words, very specific)

## 4. Competitor Content Gap
- Compare the target page to the top-ranking pages:
  - Does the target cover the same subtopics?
  - Is the target missing sections that all top pages have?
  - Is the target's content more or less current?
  - Does the target have unique data/examples that competitors don't?

## 5. Priority Matrix

| Priority | Criteria |
|----------|----------|
| **High** | High search volume, low competition, high relevance to the page |
| **Medium** | Moderate volume, aligned with page intent, gaps in current content |
| **Low** | Low volume, tangential relevance, better suited for a separate page |

## 6. Storage

Store findings in `knowledge` with `action=add_note`:
```
title: "Keyword Research: {primary keyword}"
body: structured summary
tags: "seo, keywords, {primary keyword}"
project_id: "seo"
```
