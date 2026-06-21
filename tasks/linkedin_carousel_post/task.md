# LinkedIn Document/Carousel Post — Multi-Slide Content

Use the browser to navigate to LinkedIn, create a carousel-style document post on a professional topic, write the accompanying caption, and publish or save as a draft.

## Topic
Create a carousel post: **"The Developer's Guide to Saying No (Without Burning Bridges)"** — 5 slides covering how to push back on unrealistic deadlines, scope creep, and bad technical decisions professionally.

## Steps

### 1. Create the Document Content Locally
Before opening LinkedIn, prepare the carousel content in a local file. Use `file_editor` or `python_execute` to create `Output/linkedin_carousel/carousel_content.md`:

```
# Slide 1: Title Slide
**The Developer's Guide to Saying "No"**
*(Without Burning Bridges)*
5 frameworks for pushing back professionally

---

# Slide 2: The Problem
Engineers are asked to do impossible things every week:
• "Can we launch by Friday?" (it's Wednesday)
• "Just add this one small feature" (it's a full rewrite)
• "The client wants it in purple" (your stack doesn't do purple)

Saying "yes" to everything → burnout, broken code, missed deadlines
Saying "no" wrong → labeled "difficult" or "not a team player"

There's a third way.

---

# Slide 3: Framework 1 — Trade-Off Triangle
**"We can do it, and here's what it costs."**

Every request has three levers: SCOPE, TIME, QUALITY.
You can have two. Pick.

Example:
"I can add that feature by Friday, but we'd need to drop the payment integration and skip QA. OR I can deliver both with full QA by next Wednesday. Which matters more?"

→ You didn't say no. You asked them to choose.

---

# Slide 4: Framework 2 — Data Over Emotion
**"Here's what the numbers say."**

Don't argue with opinions. Show data.

Example:
"The last time we rushed a Friday deploy, we spent 6 hours on Saturday fixing P0 bugs and lost 3 days of velocity the following week. I recommend we wait until Monday and ship clean."

→ Feelings are debatable. Data is not.

---

# Slide 5: Framework 3 — Yes-If Pattern
**"Yes, if [condition]."**

Never say "no" — say "yes, if."

• "Yes, we can add that feature — if we get a dedicated designer for 2 weeks."
• "Yes, we can hit that deadline — if we cut scope to just the core workflow."
• "Yes, the client can have purple — if they're okay with a 3-week delay for the refactor."

→ You're not blocking. You're enabling. With guardrails.
```

### 2. Convert to PDF (optional)
If Python is available, use `python_execute` to convert the markdown to a basic PDF:
```python
from fpdf import FPDF
# (or use reportlab, or just keep as a formatted text document)
```
If PDF conversion isn't possible, note that the content is ready as a document. LinkedIn accepts PDF, DOC, DOCX, PPT, and PPTX formats.

### 3. Navigate to LinkedIn
- Go to `https://www.linkedin.com`
- If already logged in, proceed
- If a login page appears, **stop immediately** — do not enter credentials

### 4. Compose the Post with Document
- Click "Start a post" or the post composer
- Click the "Document" icon (usually a document/paper icon) to attach a file
- In the file picker dialog, navigate to `Output/linkedin_carousel/` and select the document
- Wait for the upload to complete and the preview to render

### 5. Write the Accompanying Caption
In the post text area above/below the document, write:

```
I used to say "yes" to everything. Here's what it cost me:

→ 60-hour weeks for 6 months
→ A production outage at 2 AM on a Saturday
→ A project that shipped "on time" and was rewritten 3 months later

I finally learned: saying "no" isn't being difficult. It's being professional.

Swipe through for 3 frameworks I use now 👆

Which one would you try first?

#softwareengineering #careergrowth #developers #techleadership #communication
```

### 6. Post or Save
- Review the post with the attached document
- Take a screenshot of the composer
- Click "Post" (or note that it's ready for review)
- Confirm the post appears on your feed with the document attached

### 7. Report
Return:
- The full carousel content (slide titles)
- The accompanying caption text
- Screenshot of the composer with document attached
- Confirmation of publication or draft status

## Tools to Use
- `file_editor` — for creating the local document content
- `python_execute` — for optional PDF conversion
- `browser_navigator` — for AI-driven LinkedIn navigation and posting
- `advanced_browser` — for precise Playwright actions (click, upload, screenshot)

## Important
- If not logged into LinkedIn, stop and report — do NOT attempt login
- Do NOT modify your profile, send connection requests, or interact with other content
- If the file upload fails, capture the error and report what happened
- Carousel/document posts work best with PDF files under 10MB

## Expected Output
The carousel slide content, the caption text, a screenshot of the composer with the document, and confirmation of publication (or ready-for-review status).
