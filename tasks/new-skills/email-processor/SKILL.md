---
name: email-processor
description: "Use when processing, classifying, or responding to emails. Trigger: email, inbox, mail, reply, classify emails."
license: MIT
---
# Email Processor

## When to use
Process emails from a mailbox file or text export — classify, extract, or draft replies.

## Workflow
1. **Load** — read .mbox, .eml, or plain text email export.
2. **Parse** — extract sender, subject, date, body per email.
3. **Classify** — categorize as: urgent, newsletter, invoice, personal, spam, other.
4. **Extract** — action items, deadlines, attachments list.
5. **Draft replies** — for actionable emails, draft a contextual response.
6. **Report** — summary by category with action items.

## Output
Email digest with classification, action items, and draft replies.