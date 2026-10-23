# Email Inbox Digest — Thunderbird / Webmail

Use the browser to scan the inbox of your webmail account (the same account Thunderbird connects to), extract the 10 most recent email subject lines, senders, and dates, and produce a formatted daily digest. **Do NOT read email body contents** — subjects and metadata only, for privacy.

## Pre-requisites
- You should already be logged into your webmail (Gmail at `https://mail.google.com`, Outlook at `https://outlook.live.com`, or your provider's webmail).
- If not logged in, navigate to the webmail login page and pause — do NOT attempt to guess credentials.

## Steps
1. Navigate to your webmail inbox (e.g. `https://mail.google.com/mail/u/0/#inbox` for Gmail, `https://outlook.live.com/mail/inbox` for Outlook)
2. Wait for the inbox to load fully (email list visible)
3. Extract the 10 most recent emails:
   - **Subject line**
   - **Sender name/email**
   - **Date/time received**
   - **Read/unread status**
4. Format as a markdown digest:

   ```
   ## 📬 Inbox Digest — [Date]

   | # | From | Subject | Received | Status |
   |---|------|---------|----------|--------|
   | 1 | alice@example.com | Q3 Report Draft | 10:30 AM | unread |
   | 2 | bob@example.com | Meeting Tomorrow | 9:15 AM | read |
   ...
   ```

5. **Summary line**: "X unread, Y total" at the bottom.

## Tools to Use
- `browser_navigator` — for AI-driven navigation and interaction
- `advanced_browser` — for precise Playwright actions (wait, extract)
- `web_scraper` — for structured data extraction with CSS selectors

## Important
- Do NOT open or read email body contents — only subject lines and metadata
- Do NOT click any delete, archive, or send buttons
- If 2FA or re-authentication is needed, stop and report
- Save the digest to `Output/email_digest/digest_YYYY-MM-DD.md`

## Expected Output
A markdown table with 10 most recent emails (subjects, senders, dates, status) plus an unread/total summary.
