# Form Filling Demo — GitHub Signup Page

Use the browser to navigate to the GitHub signup page, fill in the registration form with test data, and capture a screenshot of the filled form.

## Steps
1. Navigate to `https://github.com/signup`
2. Wait for the signup form to load
3. Fill in the form fields:
   - **Email**: `testuser@example.com`
   - **Password**: `TestPassword123!` (note: this is a demo — do NOT actually submit/register)
   - **Username**: `testuser-demo-2024`
   - **Product interest** (if shown): select any option
4. After filling, take a **screenshot** of the filled form
5. Do NOT submit the form — stop after the screenshot
6. Return the screenshot and a summary of which fields were filled

## Tools to Use
- `browser_navigator` — for AI-driven navigation and form interaction
- `advanced_browser` — for precise Playwright actions (goto, fill, type, screenshot)

## Important Notes
- **Do NOT submit** the signup form — this is a fill-only demo
- Use test/demo data only — no real credentials
- If GitHub shows a CAPTCHA or verification challenge, capture the screenshot of whatever state the page is in and report it

## Expected Output
A base64-encoded screenshot of the filled (but unsubmitted) form, plus a textual summary of fields filled.
