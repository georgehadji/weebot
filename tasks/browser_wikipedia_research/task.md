# Wikipedia Research Assistant

Use the browser to search Wikipedia for a given topic, navigate to the article, and extract a concise summary.

## Steps
1. Launch the browser and navigate to `https://en.wikipedia.org`
2. Use the search box (`input[name="search"]`) to search for the topic: **"Artificial intelligence"**
3. Wait for the article page to load
4. Extract the first 2-3 paragraphs of the article (the introduction/summary section before the table of contents)
5. Also extract the infobox key facts if present (right-side panel)
6. Return the summary in this format:
   ```
   ## Title: [Article Title]

   ### Summary
   [First 2-3 paragraphs...]

   ### Key Facts (from infobox)
   - Fact 1
   - Fact 2
   ...
   ```

## Tools to Use
- `browser_navigator` — for AI-driven navigation (search, click results)
- `advanced_browser` — for precise Playwright actions (fill search box, click)
- `web_scraper` — for structured data extraction with CSS selectors

## Expected Output
A markdown-formatted research summary with the article title, introduction paragraphs, and infobox key facts.
