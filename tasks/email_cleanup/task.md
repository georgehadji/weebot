# Email Cleanup Assistant — Thunderbird / Webmail

Use the browser to scan your webmail for emails that are candidates for cleanup (old, promotional, spam-like, or from senders you rarely engage with). Like Thunderbird's disk-space management but automated. **This is read-only analysis — no actual deletion.**

## Pre-requisites
- You should already be logged into your webmail (Gmail, Outlook, or your provider).
- If not logged in, navigate to the webmail login page and pause — do NOT attempt to guess credentials.

## Steps
1. Navigate to your webmail inbox
2. Identify cleanup candidates using these signals (check all that apply across different mail folders if accessible):
   - **Age**: emails older than 90 days (look for date indicators)
   - **Sender type**: "noreply@", "donotreply@", "newsletter@", "notifications@", promotional domains
   - **Read but untouched**: read emails with no replies from you (check for "Re:" or thread indicators)
   - **Bulk category**: emails in Promotions/Social tabs (Gmail) or bulk folders (Outlook)
   - **Large attachments**: emails with attachment indicators (paperclip icon) — these use storage quota
3. For each category above, extract a sample (up to 5 per category) with:
   - Sender
   - Subject
   - Date
   - Category match reason
4. Produce a cleanup report:

   ```
   ## 🧹 Email Cleanup Report — [Date]

   ### 📦 By Category

   #### 🕐 Old Emails (>90 days) — X found
   | From | Subject | Date | Folder |
   |------|---------|------|--------|
   | ... | ... | ... | ... |

   #### 📢 Promotional / Bulk — Y found
   ...

   #### 👻 No-Reply Senders — Z found
   ...

   #### 📎 Large Attachments — W found
   ...

   ### 📊 Summary
   | Category | Count | Est. Space |
   |----------|-------|-----------|
   | Old (>90d) | X | — |
   | Promotional | Y | — |
   | No-Reply | Z | — |
   | Large Attach | W | — |
   | **Total Candidates** | **X+Y+Z+W** | — |

   ### 🎯 Recommended Actions
   - **Safe to archive**: Promotional + No-Reply (Y+Z emails)
   - **Review first**: Old emails, Large attachments (X+W emails)
   - **Keep**: Emails from known contacts with replies/threads

   ⚠️ No emails were deleted, archived, or modified. This is a read-only report.
   ```

## Tools to Use
- `browser_navigator` — for AI-driven navigation across folders
- `advanced_browser` — for precise Playwright actions (click tabs, extract data)
- `web_scraper` — for structured data extraction with CSS selectors

## Important
- **Absolutely NO deletion, archiving, or modification of any emails**
- Read-only analysis — extract metadata only
- Do NOT open email bodies — subjects and visible metadata only
- If 2FA or re-authentication is needed, stop and report
- Save the report to `Output/email_cleanup/cleanup_YYYY-MM-DD.md`

## Expected Output
A read-only cleanup report categorizing email cleanup candidates by type (old, promotional, no-reply, large attachments) with sample emails per category and safe-action recommendations.
