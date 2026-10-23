# Unread Email Triage — Thunderbird / Webmail

Use the browser to scan your webmail inbox for **unread emails only**, categorize each by likely priority based on sender and subject patterns, and produce a triage report. Like Thunderbird's quick-filter but automated via browser.

## Pre-requisites
- You should already be logged into your webmail (Gmail, Outlook, or your provider).
- If not logged in, navigate to the webmail login page and pause — do NOT attempt to guess credentials.

## Steps
1. Navigate to your webmail inbox
2. Apply the "unread" filter (in Gmail: `is:unread` search or click Unread; in Outlook: Filter → Unread)
3. Wait for filtered results to load
4. For each unread email (up to 20), extract:
   - **Sender** (name and email)
   - **Subject line**
   - **Time received**
   - **Has attachments?** (look for paperclip icon)
   - **Is a reply to your thread?** (look for "Re:" prefix or thread indicators)
5. Categorize each email into priority buckets:
   - 🔴 **High** — from known contacts (boss, team, family), marked urgent, or "Re:" to your threads
   - 🟡 **Medium** — newsletters, notifications from services you use, calendar invites
   - 🟢 **Low** — promotional, social media notifications, no-reply addresses
6. Produce a triage report:

   ```
   ## 📬 Unread Email Triage — [Date/Time]

   ### 🔴 High Priority (X emails)
   | From | Subject | Received | Attachments | Reply? |
   |------|---------|----------|-------------|--------|
   | ... | ... | ... | ... | ... |

   ### 🟡 Medium Priority (Y emails)
   ...

   ### 🟢 Low Priority (Z emails)
   ...

   ### Summary
   - Total unread: N
   - Needs reply: M
   - Can archive: L
   ```

## Tools to Use
- `browser_navigator` — for AI-driven navigation
- `advanced_browser` — for precise Playwright actions (click filter, extract data)
- `web_scraper` — for structured data extraction with CSS selectors

## Important
- Do NOT open or read email body contents — subjects and metadata only
- Do NOT click delete, archive, or send — this is read-only triage
- Save the report to `Output/email_triage/triage_YYYY-MM-DD_HHMM.md`

## Expected Output
A prioritized triage report categorizing unread emails into High/Medium/Low with sender, subject, time, attachment status, and reply indicators.
