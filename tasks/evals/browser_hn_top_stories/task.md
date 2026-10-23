# Hacker News Top Stories Scraper

Use the browser to navigate to **Hacker News** (https://news.ycombinator.com), extract the top 5 story titles and their links, and return them as a numbered list.

## Steps
1. Launch the browser and navigate to `https://news.ycombinator.com`
2. Wait for the page to load fully
3. Extract the top 5 story titles (found in `.titleline > a` elements on the front page)
4. Extract the corresponding URLs for each story
5. Return the results as a formatted list:
   ```
   1. [Story Title](URL)
   2. [Story Title](URL)
   ...
   ```

## Tools to Use
- `browser_navigator` — for AI-driven navigation and interaction
- `advanced_browser` — for precise Playwright-based extraction if needed
- `web_scraper` — for structured data extraction with CSS selectors

## Expected Output
A numbered list of the top 5 HN stories with titles and clickable links.
