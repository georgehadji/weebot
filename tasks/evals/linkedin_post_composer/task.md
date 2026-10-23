# LinkedIn Post Composer — Short-Form Update

Use the browser to navigate to LinkedIn, compose an engaging short-form post on a professional topic, format it for maximum reach, and either publish it or save as a draft for review.

## Topic
Write a post about: **"The most underrated skill in software engineering is clear written communication — here's why."**

## Steps

### 1. Navigate to LinkedIn
- Go to `https://www.linkedin.com`
- If you're already logged in, proceed to the home feed
- If a login page appears, **stop immediately** — do not attempt to enter credentials. Report the state and exit.

### 2. Open the Post Composer
- Click the "Start a post" box (usually at the top of the feed)
- Wait for the composer modal/dialog to fully load
- Confirm the composer is ready (text area visible, cursor active)

### 3. Compose the Post
Write a scroll-stopping post using this structure:

```
[HOOK LINE — bold or single-sentence opener that grabs attention]

[THE INSIGHT — 2-3 short paragraphs explaining the point. Use line breaks between each sentence for readability on mobile. No jargon.]

[EVIDENCE — one specific example or data point that backs the claim]

[CALL-TO-ACTION — one sentence that invites engagement: "What skill do you think is most underrated?"]

[Line break]
#softwareengineering #communication #careeradvice #techleadership
```

### 4. Format for LinkedIn
- Keep paragraphs to 1-2 sentences max (LinkedIn truncates at 3 lines on mobile)
- Use line breaks generously — blank lines between each line
- No markdown — LinkedIn uses plain text with Unicode for emphasis
- Hashtags: 3-5 relevant tags, each on its own style (PascalCase for multi-word)
- Total: 800-1300 characters (LinkedIn's ideal range for algorithm)

### 5. Post or Save
- **Option A (preferred):** Click "Post" to publish immediately
- **Option B:** If there's a "Save as draft" option or the task is configured for review-only, stop before clicking Post and report the composed text
- Take a screenshot of the final composer before posting
- After posting, confirm the post appears on your profile feed

### 6. Report
Return:
- The full text of the composed post
- Character count
- Screenshot (base64) of the composer before posting
- Confirmation that the post was published (or saved as draft)

## Tools to Use
- `browser_navigator` — for AI-driven navigation and post composition
- `advanced_browser` — for precise Playwright actions (click, type, wait, screenshot)
- `web_scraper` — for extracting post confirmation from the page

## Important
- If not logged into LinkedIn, stop and report — do NOT attempt login
- Do NOT modify your profile, send connection requests, or interact with other posts
- If 2FA is triggered, stop and report
- If the post fails to publish (error message), capture the error and report

## Expected Output
The full post text, character count, a screenshot of the composed post, and confirmation of publication.
