"""TaskCategory — what kind of step a task is.

Lives in the domain so ``weebot.config`` (capability profiles) and
``application.services.task_model_router`` can share it without config
importing application.
"""

from __future__ import annotations

from enum import Enum


class TaskCategory(Enum):
    CODING = "coding"
    FILE_OPS = "file_ops"
    RESEARCH = "research"
    REVIEW = "review"
    BROWSER = "browser"
    PLANNING = "planning"
    SECURITY = "security"
    SUMMARIZATION = "summarization"
    GENERAL = "general"
