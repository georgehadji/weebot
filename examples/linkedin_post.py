#!/usr/bin/env python3
"""
LinkedIn Post Creator — weebot browser automation example.

Uses weebot's BrowserTool (browser-use + Playwright) to:
1. Navigate to LinkedIn
2. Log in with your credentials
3. Compose and post a status update
4. Screenshot the result

PREREQUISITES:
    pip install browser-use langchain-openai
    Set env: LINKEDIN_EMAIL, LINKEDIN_PASSWORD, OPENAI_API_KEY

RUN:
    python examples/linkedin_post.py "Your post text here"

Or run via weebot CLI:
    python -m cli.main flow run "Post to LinkedIn: 'Your text'"
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def post_to_linkedin(post_text: str, email: str = "", password: str = "") -> None:
    """Post a status update to LinkedIn using browser automation."""
    from browser_use import Browser, Agent as BrowserAgent
    from langchain_openai import ChatOpenAI

    email = email or os.getenv("LINKEDIN_EMAIL", "")
    password = password or os.getenv("LINKEDIN_PASSWORD", "")

    if not email or not password:
        print("ERROR: Set LINKEDIN_EMAIL and LINKEDIN_PASSWORD environment variables.")
        return

    # ── Build the task prompt ─────────────────────────────────────────
    task = f"""
You are an assistant helping a user post to LinkedIn.

YOUR TASK:
1. Go to https://www.linkedin.com/login
2. Enter the email "{email}" in the email field
3. Enter the password in the password field
4. Click "Sign in"
5. Wait for the feed to load (look for "Start a post" or the post composer)
6. Click the post composer ("Start a post" button or text area at the top of the feed)
7. In the post dialog that appears, type the following text exactly:

{post_text}

8. Click the "Post" button to publish
9. Wait 3 seconds for the post to appear
10. Take a screenshot and confirm the post appeared

IMPORTANT:
- If LinkedIn asks for 2FA, tell me what type and I'll handle it.
- If a "You're all set" welcome modal appears, dismiss it.
- Do NOT navigate away from LinkedIn.
- Do NOT change account settings.
- If the post button is disabled, check if the text was entered correctly.
"""

    print(f"Posting to LinkedIn ({len(post_text)} chars)...")
    print(f"Post text: {post_text[:80]}{'...' if len(post_text) > 80 else ''}")

    # ── Run the browser agent ─────────────────────────────────────────
    llm = ChatOpenAI(model="gpt-4o", temperature=0)
    browser = Browser(headless=False)
    agent = BrowserAgent(task=task, llm=llm, browser=browser)

    try:
        result = await agent.run()
        print(f"\nDone! Result: {result}")
    finally:
        await browser.close()


def main() -> None:
    post_text = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else ""
    if not post_text:
        print("Usage: python examples/linkedin_post.py \"Your post text here\"")
        print("\nSet LINKEDIN_EMAIL and LINKEDIN_PASSWORD env vars.")
        sys.exit(1)
    asyncio.run(post_to_linkedin(post_text))


if __name__ == "__main__":
    main()
