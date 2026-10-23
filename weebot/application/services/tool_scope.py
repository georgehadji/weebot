"""Which tool definitions a step is sent (ICM B1: load only what the step needs).

Every executor call used to send all ~171 definitions (~49k tokens, 114 of
them MCP) whatever the step. A step now gets:

- a core set every step may need;
- the tools its category (``task_model_router.classify_step``) and its words
  call for;
- the MCP tools of a service it names (Jira, HubSpot, Apify, Postiz);
- any tool named in the step outright.

Nothing is removed from the collection: a tool outside the set is still
callable by name, and the executor lists those names (without definitions).
"""

from __future__ import annotations

import re

from weebot.application.services.task_model_router import TaskCategory, classify_step

CORE: frozenset[str] = frozenset(
    {
        "web_search", "file_editor", "python_execute", "bash", "powershell",
        "advanced_browser", "ask_human", "terminate", "todo_write", "knowledge",
    }
)

_BY_CATEGORY: dict[TaskCategory, frozenset[str]] = {
    TaskCategory.RESEARCH: frozenset(
        {"vane_search", "moli_fetch", "agent_reach", "search_history", "web_scraper",
         "apify_google_search", "apify_website_to_markdown"}
    ),
    TaskCategory.BROWSER: frozenset(
        {"browser_inspector", "camofox_browser", "web_scraper", "computer_use", "screen_capture"}
    ),
    TaskCategory.FILE_OPS: frozenset({"ocr", "ocr_structured"}),
    TaskCategory.PLANNING: frozenset({"dispatch_parallel_tasks", "workflow_orchestrator", "schedule"}),
    TaskCategory.REVIEW: frozenset({"audit_session", "debate"}),
    TaskCategory.SUMMARIZATION: frozenset({"search_history"}),
}

# word in the step (lower case, whole word) -> tools
_BY_WORD: dict[str, frozenset[str]] = {
    "weather": frozenset({"weather"}),
    "forecast": frozenset({"weather"}),
    "image": frozenset({"image_gen", "search_images"}),
    "images": frozenset({"image_gen", "search_images"}),
    "picture": frozenset({"image_gen", "search_images"}),
    "photo": frozenset({"image_gen", "search_images"}),
    "logo": frozenset({"image_gen"}),
    "illustration": frozenset({"image_gen"}),
    "icon": frozenset({"image_gen"}),
    "video": frozenset({"video_gen", "remotion_video", "video_ingest", "youtube_download"}),
    "youtube": frozenset({"youtube_download", "video_ingest", "apify_youtube_transcript"}),
    "transcript": frozenset({"apify_youtube_transcript", "video_ingest"}),
    "email": frozenset({"atomic_mail", "apify_email_finder"}),
    "emails": frozenset({"atomic_mail"}),
    "mail": frozenset({"atomic_mail"}),
    "inbox": frozenset({"atomic_mail"}),
    "schedule": frozenset({"schedule"}),
    "remind": frozenset({"schedule"}),
    "voice": frozenset({"voice_output", "voice_input"}),
    "speak": frozenset({"voice_output"}),
    "audio": frozenset({"voice_output", "voice_input"}),
    "screen": frozenset({"screen_capture", "computer_use", "screenshot_ocr"}),
    "screenshot": frozenset({"screen_capture", "screenshot_ocr", "ocr"}),
    "desktop": frozenset({"computer_use", "desktop_a11y", "screen_capture"}),
    "window": frozenset({"computer_use", "desktop_a11y"}),
    "ocr": frozenset({"ocr", "ocr_structured"}),
    "scan": frozenset({"ocr", "ocr_structured"}),
    "scrape": frozenset({"web_scraper", "apify_web_scraper", "apify_website_to_markdown"}),
    "crawl": frozenset({"web_scraper", "apify_website_to_markdown"}),
    "reddit": frozenset({"apify_reddit_scraper"}),
    "twitter": frozenset({"apify_twitter_scraper"}),
    "tweet": frozenset({"apify_twitter_scraper"}),
    "tweets": frozenset({"apify_twitter_scraper"}),
    "jobs": frozenset({"apify_linkedin_jobs"}),
    "bing": frozenset({"apify_bing_search"}),
    "product": frozenset({"product"}),
    "roadmap": frozenset({"product"}),
    "design": frozenset({"design_system"}),
    "debate": frozenset({"debate"}),
    "perspectives": frozenset({"debate"}),
    "parallel": frozenset({"dispatch_parallel_tasks", "swarm"}),
    "prove": frozenset({"reasoner"}),
    "proof": frozenset({"reasoner"}),
    "papers": frozenset({"berb"}),
    "literature": frozenset({"berb"}),
    "remember": frozenset({"persistent_memory"}),
    "memory": frozenset({"persistent_memory"}),
    "history": frozenset({"search_history"}),
}

# MCP server -> words that mean the step is about that service
_MCP_SERVICE_WORDS: dict[str, tuple[str, ...]] = {
    "jira": ("jira", "ticket", "tickets", "issue", "issues", "sprint", "backlog", "epic"),
    "hubspot": ("hubspot", "crm", "contact", "contacts", "deal", "deals", "lead", "leads"),
    "apify": ("apify", "actor", "actors", "scrape", "scraper", "scraping"),
    "postiz": ("postiz", "social", "instagram", "facebook", "linkedin", "post", "posts"),
}

_WORD = re.compile(r"[a-z0-9_]+")


def select_tools(step_text: str, available: set[str] | frozenset[str]) -> set[str]:
    """The tool names step *step_text* is sent, out of *available*."""
    text = (step_text or "").lower()
    words = set(_WORD.findall(text))
    chosen: set[str] = set(CORE)
    chosen |= _BY_CATEGORY.get(classify_step(step_text or ""), frozenset())
    for word in words & _BY_WORD.keys():
        chosen |= _BY_WORD[word]
    for server, service_words in _MCP_SERVICE_WORDS.items():
        if words.intersection(service_words):
            prefix = f"mcp__{server}__"
            chosen |= {n for n in available if n.startswith(prefix)}
    chosen |= {n for n in available if n.lower() in words}  # named outright
    return chosen & set(available)
