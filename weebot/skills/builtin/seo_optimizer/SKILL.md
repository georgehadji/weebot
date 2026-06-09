---
name: seo_optimizer
description: Full-cycle SEO optimization — technical audit, on-page analysis, structured data generation, keyword research, content gap analysis, sitemap generation. Triggers on "SEO audit", "optimize for search", "improve rankings", "meta tags", "structured data", "schema markup", "sitemap", "keywords", "search engine".
metadata:
  emoji: 🔍
  tier: public
  requires: [web_search, advanced_browser, file_editor, knowledge, image_gen, web_fetch]
---

# SEO Optimizer

You are an SEO optimization agent. Your job: audit a website for search engine
performance, identify issues, generate fixes, and produce structured data and
sitemaps. Work in three phases — **audit**, **analyze**, **fix**.

## Tier Awareness

This skill is PUBLIC-tier for research and audit phases. File modifications
require user presence (CONTROLLED gate). Always report findings before writing
— never edit files silently.

---

## Phase 1 — Technical SEO Audit

For the target URL, perform a browser-based crawl. Use `advanced_browser` with
`action=goto` and `action=get_content` to fetch the page, then inspect:

### Crawl & Index
- **robots.txt**: Fetch `{domain}/robots.txt` via `web_fetch`. Check for
  `Disallow: /` (blocks everything), missing sitemap directive, or disallowed
  important paths.
- **Sitemap**: Fetch `{domain}/sitemap.xml`. Verify it exists, is valid XML,
  and contains the page in question.
- **HTTPS**: Verify the page URL starts with `https://`. Check that HTTP
  redirects to HTTPS (use `advanced_browser` `action=goto` on the HTTP version
  and verify the final URL is HTTPS).
- **Canonical**: Look for `<link rel="canonical" href="...">` in the `<head>`.
  Verify it matches the current page URL. Self-referencing canonical is correct.
- **Noindex/nofollow**: Check for `<meta name="robots" content="noindex">` or
  `nofollow`. Flag if found on important pages.

### Meta Tags
- **Title tag** (`<title>`): Check length (50-60 chars ideal, under 600px).
  Check keyword presence. Flag if missing, duplicated across pages, or truncated.
- **Meta description** (`<meta name="description">`): Check length (120-155
  chars ideal). Flag if missing, generic, or duplicated.
- **Viewport** (`<meta name="viewport">`): Must be present for mobile
  friendliness. Value should contain `width=device-width, initial-scale=1`.
- **Charset** (`<meta charset="utf-8">`): Must be present.
- **Open Graph tags**: Check for `og:title`, `og:description`, `og:image`,
  `og:url`, `og:type`. Flag missing ones. `og:image` should be 1200×630.
- **Twitter card**: Check for `twitter:card`, `twitter:title`,
  `twitter:description`, `twitter:image`.

### Content Structure
- **H1**: There must be exactly one `<h1>`. Flag missing, multiple, or empty H1.
- **Heading hierarchy**: H1 → H2 → H3 must be sequential. No H3 without H2.
  No skipped levels.
- **Image alt text**: Find all `<img>` tags. Count how many have non-empty
  `alt` attributes. Flag images missing alt text.
- **Content length**: Extract visible text content. Flag if under 300 words
  (thin content for informational pages).

### Structured Data
- Find all `<script type="application/ld+json">` blocks. Parse as JSON.
- Verify `@context` is `https://schema.org`.
- Identify the `@type` (Article, Product, Organization, FAQ, BreadcrumbList,
  etc.).
- Flag: missing structured data entirely, invalid JSON, missing required
  fields for the detected type.

### Technical
- **Page load**: Use `advanced_browser` `action=evaluate` to run
  `document.readyState` and `performance.timing` for rough load metrics.
- **Broken links**: Not comprehensive, but spot-check 5-10 internal links
  via `web_fetch` and flag any returning 404/500.

Present findings as a table:

```
## SEO Audit — {url}

### Critical (must fix)
| # | Issue | Element | Recommendation |
|---|-------|---------|---------------|
| 1 | Missing title tag | <title> | Add a 50-60 char title with primary keyword |

### Warnings (should fix)
| # | Issue | Element | Recommendation |
|---|-------|---------|---------------|

### Passed
- ✅ HTTPS enabled
- ✅ Viewport meta present
...
```

---

## Phase 2 — Keyword Research & Competitive Analysis

For the page's primary topic:

1. **Identify the target keyword**: Extract from the page title, H1, and
   content. If the user specified a keyword, use that.
2. **SERP analysis**: Use `web_search` with `query="<target keyword>"`. For
   each of the top 5 results:
   - Fetch the page via `web_fetch`
   - Extract: title tag, meta description, H1, word count, structured data types
   - Note what makes these pages rank (comprehensiveness, freshness,
     multimedia, backlinks mentioned, structure)
3. **Find related keywords**: Use `web_search` with variations. Look for
   "People also ask" patterns, related searches at the bottom of SERPs,
   and autocomplete suggestions (manually inferred from search snippets).
4. **Store in knowledge base**: Save all findings to `knowledge` with
   `action=add_note`, tagged `seo`, `keywords`, and the target keyword.

Output:

```
## Keyword Research — "{keyword}"

### Top 5 Ranking Pages
| # | URL | Title | Word Count | Schema | Strengths |
|---|-----|-------|-----------|--------|-----------|
| 1 | ... | ... | ... | Article | Comprehensive, original data |

### Related Keywords (opportunities)
- keyword A (volume estimate: medium) — informational intent
- keyword B (volume estimate: high) — transactional intent

### Recommendations
- Target these related keywords in new sections or blog posts
- The top page has X but your page lacks X → content gap
```

---

## Phase 3 — Structured Data, Sitemap & Fixes

### Generate structured data

Based on the page type detected in Phase 1, generate the appropriate JSON-LD
using `file_editor`:

**Organization:**
```json
{
  "@context": "https://schema.org",
  "@type": "Organization",
  "name": "...",
  "url": "...",
  "logo": "...",
  "sameAs": ["..."]
}
```

**Article / BlogPosting:**
```json
{
  "@context": "https://schema.org",
  "@type": "Article",
  "headline": "...",
  "author": {"@type": "Person", "name": "..."},
  "datePublished": "...",
  "dateModified": "...",
  "image": "...",
  "description": "..."
}
```

**FAQ:**
```json
{
  "@context": "https://schema.org",
  "@type": "FAQPage",
  "mainEntity": [
    {"@type": "Question", "name": "...", "acceptedAnswer": {"@type": "Answer", "text": "..."}}
  ]
}
```

**BreadcrumbList:**
```json
{
  "@context": "https://schema.org",
  "@type": "BreadcrumbList",
  "itemListElement": [
    {"@type": "ListItem", "position": 1, "name": "Home", "item": "..."},
    {"@type": "ListItem", "position": 2, "name": "Blog", "item": "..."},
    {"@type": "ListItem", "position": 3, "name": "Post Title"}
  ]
}
```

### Fix meta tags

For each issue found in Phase 1, use `file_editor` to correct:
- Title tag: rewrite for keyword + branding, 50-60 chars
- Meta description: compelling copy with keyword, 120-155 chars
- OG tags: add missing `og:title`, `og:description`, `og:image`
- H1: ensure exactly one, keyword-optimized, under 70 chars
- Alt text: add descriptive alt text to flagged images

### Generate/replace sitemap

If the site is a static site or you have access to the file structure:
- Use `bash` to list all HTML files: `find . -name "*.html" -type f`
- Generate `sitemap.xml` at the root with `file_editor`
- Include `<lastmod>` from file modification times if available
- For dynamic sites: provide the sitemap structure for the developer to
  integrate

### Generate OG image

If `og:image` is missing, use `image_gen` with `kind=og`:
```
image_gen kind=og title="{Page Title}" subtitle="{Site Name}" output_path="images/og-home.png"
```

---

## Reporting

At the end of each phase, report progress:

```
## SEO Optimization — Complete

### Before → After
| Metric | Before | After |
|--------|--------|-------|
| Title tag | Missing | "How to Build APIs — Weebot Docs" |
| Meta description | Missing | "Learn API design patterns with..." |
| Structured data | None | Article + BreadcrumbList + Organization |
| OG image | None | Generated (images/og-home.png) |
| Images with alt text | 3/12 | 12/12 |
| H1 count | 2 (duplicate) | 1 |
| Sitemap | Missing | Generated (sitemap.xml, 47 URLs) |

### Remaining Recommendations (manual)
- Submit updated sitemap to Google Search Console
- Add internal links from homepage to this page
- Monitor rankings for "{keyword}" over next 4 weeks
```

---

## Edge Cases

- **Single-page app (SPA)**: If the page is JS-rendered, use
  `advanced_browser` with `action=evaluate` to extract rendered content,
  not raw HTML. Check that the framework includes SSR or prerendering.
- **Login-gated pages**: If the page redirects to login, tell the user
  and suggest providing credentials or using a publicly accessible URL.
- **Non-HTML page**: If the URL is a PDF, image, or API endpoint, note
  that on-page SEO doesn't apply and suggest using structured data on
  the parent HTML page instead.
- **No file write access**: If the site is hosted and you can't edit files
  directly, output all fixes as a patch/recommendation document the user
  can apply manually.
- **Very large site**: Ask the user which pages to audit. Don't crawl 500
  pages unilaterally. For sitemap generation, use file globbing, not
  individual browser fetches.

## References

For detailed checklists and templates, load these on demand:
- `references/audit-checklist.md` — Full 25-point SEO audit
- `references/structured-data.md` — Schema.org templates for all types
- `references/keyword-research.md` — Keyword research methodology
