# SEO Audit Checklist — 25 Points

Run this checklist for each page or site being audited.

## Crawl & Index (5)
- [ ] robots.txt exists and is not blocking important paths
- [ ] sitemap.xml exists, is valid XML, and includes this page
- [ ] HTTP → HTTPS redirect works (301)
- [ ] Canonical URL is present and self-referencing
- [ ] No accidental noindex/nofollow on important pages

## Meta Tags (6)
- [ ] Title tag is 50-60 characters, includes primary keyword
- [ ] Title tag is unique across the site
- [ ] Meta description is 120-155 characters, includes keyword
- [ ] Meta description is unique and compelling (not generic)
- [ ] Viewport meta tag exists (`width=device-width, initial-scale=1`)
- [ ] Charset meta tag exists (`charset="utf-8"`)

## Open Graph & Social (5)
- [ ] `og:title` present (should match page title)
- [ ] `og:description` present
- [ ] `og:image` present — 1200×630 PNG/JPG
- [ ] `og:url` present — canonical page URL
- [ ] `twitter:card` present (`summary_large_image` for articles)

## Content Structure (4)
- [ ] Exactly one `<h1>` — keyword-optimized, under 70 chars
- [ ] Heading hierarchy is sequential (H1 → H2 → H3, no skips)
- [ ] All `<img>` tags have non-empty `alt` attributes
- [ ] Content length ≥ 300 words (informational pages) or ≥ 150 words (landing pages)

## Structured Data (3)
- [ ] JSON-LD present with `@context: "https://schema.org"`
- [ ] Type matches content (Article, Product, FAQ, Organization, LocalBusiness)
- [ ] Required fields for the type are present (Google's Rich Results Test)

## Technical (2)
- [ ] Page loads in under 3 seconds (document.readyState check)
- [ ] No broken internal links (spot-check 5-10 links, flag 404s/500s)
