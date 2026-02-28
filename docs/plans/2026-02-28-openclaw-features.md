# OpenClaw Features Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add 9 Windows-native capabilities inspired by OpenClaw to weebot: log rotation, smart notification categorization, Windows toast notifications, screen capture tool, granular exec approval policy, sub-session tracking, activity stream, reconnect backoff, and system tray app.

**Architecture:** Each feature is isolated — new files or additive changes to existing ones. Notification features layer on top of the existing `NotificationManager` channel system. New tools (screen capture) follow the same pattern as existing tools in `weebot/tools/`. The tray app in `weebot/tray.py` is a standalone entry point that wraps the existing agent.

**Tech Stack:** Python 3.12, winotify (Windows toasts), mss (screen capture), pystray (system tray), Pillow (image handling, already installed), existing SQLite + aiohttp infrastructure.

---

## Progress Tracker

| Task | Feature | Status |
|------|---------|--------|
| 1 | Log rotation | ⬜ |
| 2 | Smart notification categorization | ⬜ |
| 3 | Windows toast channel | ⬜ |
| 4 | Screen capture tool | ⬜ |
| 5 | ExecApprovalPolicy | ⬜ |
| 6 | Sub-sessions in StateManager | ⬜ |
| 7 | Activity stream | ⬜ |
| 8 | Reconnect backoff | ⬜ |
| 9 | System tray app | ⬜ |

---

## Task 1: Log Rotation

**Files:**
- Modify: `weebot/utils/logger.py`
- Test: `tests/unit/test_logger.py`

**Context:** Current `AgentLogger` uses a plain `FileHandler`. No rotation. File grows forever. Target: rotate at 5MB, keep 1 backup (`.log.old` pattern from OpenClaw).

**Step 1: Write the failing test**

```python
# tests/unit/test_logger.py
"""Unit tests for AgentLogger with rotation."""
import pytest
from pathlib import Path
from weebot.utils.logger import AgentLogger


class TestLogRotation:
    def test_logger_creates_log_file(self, tmp_path):
        log_file = tmp_path / "agent.log"
        logger = AgentLogger(log_path=log_file)
        logger.get_logger().info("hello")
        assert log_file.exists()

    def test_logger_rotates_at_5mb(self, tmp_path):
        log_file = tmp_path / "agent.log"
        # Pre-fill file past 5MB
        log_file.write_bytes(b"x" * (5 * 1024 * 1024 + 1))
        logger = AgentLogger(log_path=log_file)
        logger.get_logger().info("trigger rotation check")
        # After any write, original should be backed up
        assert (tmp_path / "agent.log.old").exists() or log_file.stat().st_size < 5 * 1024 * 1024 + 100

    def test_logger_accepts_custom_path(self, tmp_path):
        log_file = tmp_path / "subdir" / "custom.log"
        logger = AgentLogger(log_path=log_file)
        assert logger.log_path == log_file

    def test_logger_default_path_unchanged(self):
        from pathlib import Path
        logger = AgentLogger()
        assert "agent.log" in str(logger.log_path)
```

**Step 2: Run test to verify it fails**

```
pytest tests/unit/test_logger.py -v
```
Expected: FAIL — `AgentLogger.__init__` takes no `log_path` argument.

**Step 3: Implement**

Replace `weebot/utils/logger.py` with:

```python
"""Logging utility for weebot."""
import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Union

LOG_FILE = Path("logs/agent.log")
MAX_BYTES = 5 * 1024 * 1024  # 5 MB


class AgentLogger:
    def __init__(self, log_path: Union[Path, str, None] = None) -> None:
        self.log_path = Path(log_path) if log_path else LOG_FILE
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

        self.logger = logging.getLogger("WeebotAgent")
        # Avoid duplicate handlers if called multiple times
        if self.logger.handlers:
            return
        self.logger.setLevel(logging.DEBUG)

        # Rotating file handler: 5 MB max, 1 backup
        file_handler = logging.handlers.RotatingFileHandler(
            self.log_path,
            maxBytes=MAX_BYTES,
            backupCount=1,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(module)-12s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))

        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)

    def get_logger(self) -> logging.Logger:
        return self.logger


def get_logger(log_path: Union[Path, str, None] = None) -> logging.Logger:
    return AgentLogger(log_path=log_path).get_logger()
```

**Step 4: Run tests**

```
pytest tests/unit/test_logger.py -v
```
Expected: all PASS.

**Step 5: Full suite check**

```
pytest tests/ -v --tb=short
```
Expected: all 73+ tests PASS.

**Step 6: Commit**

```bash
git add weebot/utils/logger.py tests/unit/test_logger.py
git commit -m "feat: add log rotation at 5MB with RotatingFileHandler"
```

---

## Task 2: Smart Notification Categorization

**Files:**
- Create: `weebot/notifications_categorizer.py`
- Test: `tests/unit/test_notifications_categorizer.py`

**Context:** Port OpenClaw's `NotificationCategorizer` to Python. Three-tier pipeline: (1) structured metadata on `Notification.metadata`, (2) user-defined regex rules, (3) built-in keyword matching, (4) default `info`. Integrate into `NotificationManager` so every `Notification` gets a `.category` assigned before dispatch.

**Step 1: Write the failing tests**

```python
# tests/unit/test_notifications_categorizer.py
"""Unit tests for NotificationCategorizer."""
import pytest
from weebot.notifications_categorizer import NotificationCategorizer, UserRule


class TestBuiltinKeywords:
    def setup_method(self):
        self.cat = NotificationCategorizer()

    def test_urgent_keyword(self):
        assert self.cat.categorize("urgent task needed", {}) == "urgent"

    def test_health_keyword(self):
        assert self.cat.categorize("blood sugar is 120", {}) == "health"

    def test_reminder_keyword(self):
        assert self.cat.categorize("reminder: take medicine", {}) == "reminder"

    def test_email_keyword(self):
        assert self.cat.categorize("new email in inbox", {}) == "email"

    def test_calendar_keyword(self):
        assert self.cat.categorize("meeting in 10 minutes", {}) == "calendar"

    def test_build_keyword(self):
        assert self.cat.categorize("CI build failed on main", {}) == "build"

    def test_error_keyword(self):
        assert self.cat.categorize("error: connection refused", {}) == "error"

    def test_default_when_no_match(self):
        assert self.cat.categorize("hello world", {}) == "info"


class TestMetadataOverride:
    def setup_method(self):
        self.cat = NotificationCategorizer()

    def test_metadata_category_wins_over_keywords(self):
        # Even though message has "urgent", metadata says "calendar"
        result = self.cat.categorize("urgent meeting", {"category": "calendar"})
        assert result == "calendar"

    def test_metadata_intent_used_when_no_category(self):
        result = self.cat.categorize("your glucose is high", {"intent": "health"})
        assert result == "health"


class TestUserRules:
    def setup_method(self):
        self.cat = NotificationCategorizer(user_rules=[
            UserRule(pattern="invoice|receipt", is_regex=True, category="email"),
            UserRule(pattern="standup", is_regex=False, category="calendar"),
        ])

    def test_regex_rule_matches(self):
        assert self.cat.categorize("new invoice available", {}) == "email"

    def test_literal_rule_matches(self):
        assert self.cat.categorize("standup in 5 mins", {}) == "calendar"

    def test_rule_wins_over_keywords(self):
        # "invoice" has no built-in keyword, but rule fires before default
        assert self.cat.categorize("invoice due", {}) == "email"

    def test_metadata_wins_over_user_rules(self):
        result = self.cat.categorize("invoice due", {"category": "urgent"})
        assert result == "urgent"
```

**Step 2: Run to verify failure**

```
pytest tests/unit/test_notifications_categorizer.py -v
```
Expected: FAIL — `weebot.notifications_categorizer` does not exist.

**Step 3: Implement `weebot/notifications_categorizer.py`**

```python
"""Smart notification categorization (ported from OpenClaw)."""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional


BUILTIN_CATEGORIES: Dict[str, List[str]] = {
    "health":    ["blood sugar", "glucose", "cgm", "heart rate", "blood pressure"],
    "urgent":    ["urgent", "critical", "emergency", "asap"],
    "reminder":  ["reminder", "don't forget", "remember"],
    "email":     ["email", "inbox", "gmail", "mail from"],
    "calendar":  ["calendar", "meeting", "event", "appointment", "standup"],
    "error":     ["error", "failed", "exception", "traceback"],
    "build":     ["build", "ci", "deploy", "pipeline", "test failed"],
}


@dataclass
class UserRule:
    pattern: str
    is_regex: bool
    category: str
    enabled: bool = True


class NotificationCategorizer:
    """
    Three-tier categorization pipeline (first match wins):
    1. Structured metadata (category / intent fields)
    2. User-defined rules (regex or literal)
    3. Built-in keyword matching
    4. Default: "info"
    """

    def __init__(self, user_rules: Optional[List[UserRule]] = None) -> None:
        self._user_rules = [r for r in (user_rules or []) if r.enabled]
        # Pre-compile regex rules
        self._compiled = [
            (re.compile(r.pattern, re.IGNORECASE) if r.is_regex else None, r)
            for r in self._user_rules
        ]

    def categorize(self, message: str, metadata: Dict) -> str:
        """Return category string for the given message + metadata."""
        # Tier 1: structured metadata
        if metadata.get("category"):
            return metadata["category"]
        if metadata.get("intent"):
            return metadata["intent"]

        # Tier 2: user rules
        msg_lower = message.lower()
        for compiled_re, rule in self._compiled:
            if compiled_re:
                if compiled_re.search(message):
                    return rule.category
            else:
                if rule.pattern.lower() in msg_lower:
                    return rule.category

        # Tier 3: built-in keywords
        for category, keywords in BUILTIN_CATEGORIES.items():
            if any(kw in msg_lower for kw in keywords):
                return category

        return "info"
```

**Step 4: Integrate into `Notification` dataclass**

In `weebot/notifications.py`, add `category: str = "info"` field to `Notification` and populate it in `NotificationManager.notify()`:

```python
# At top of notifications.py — add import:
from weebot.notifications_categorizer import NotificationCategorizer

# In Notification dataclass — add field:
category: str = "info"

# In NotificationManager.__init__ — add:
self._categorizer = NotificationCategorizer()

# In NotificationManager.notify() — add before dispatch:
notification.category = self._categorizer.categorize(
    notification.message, notification.metadata or {}
)
```

**Step 5: Run tests**

```
pytest tests/unit/test_notifications_categorizer.py tests/unit/test_settings.py -v
```
Expected: all PASS.

**Step 6: Commit**

```bash
git add weebot/notifications_categorizer.py weebot/notifications.py \
        tests/unit/test_notifications_categorizer.py
git commit -m "feat: add smart notification categorization (3-tier pipeline)"
```

---

## Task 3: Windows Toast Notifications Channel

**Files:**
- Create: `weebot/tools/windows_toast.py`
- Modify: `weebot/notifications.py` (add `WindowsToastChannel`)
- Modify: `requirements.txt`
- Test: `tests/unit/test_windows_toast.py`

**Context:** `winotify` sends Windows 10/11 toast notifications. Add as an optional 4th channel. If `winotify` is not importable (non-Windows), the channel silently skips. Category from Task 2 maps to icons.

**Step 1: Install dependency**

```bash
pip install winotify
```

Add to `requirements.txt` under `# Windows Integration`:
```
winotify>=1.1.0; platform_system=="Windows"
```

**Step 2: Write the failing tests**

```python
# tests/unit/test_windows_toast.py
"""Unit tests for WindowsToastChannel."""
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime
from weebot.notifications import Notification, NotificationLevel, WindowsToastChannel


class TestWindowsToastChannel:
    def _make_notification(self, title="Test", message="body", category="info"):
        return Notification(
            title=title, message=message,
            level=NotificationLevel.INFO,
            timestamp=datetime.now(),
            category=category,
        )

    @pytest.mark.asyncio
    async def test_send_returns_true_when_winotify_available(self):
        mock_toast_cls = MagicMock()
        mock_toast = MagicMock()
        mock_toast_cls.return_value = mock_toast
        with patch.dict("sys.modules", {"winotify": MagicMock(Notification=mock_toast_cls)}):
            ch = WindowsToastChannel(app_name="weebot-test")
            result = await ch.send(self._make_notification())
        assert result is True

    @pytest.mark.asyncio
    async def test_send_returns_false_when_winotify_missing(self):
        with patch.dict("sys.modules", {"winotify": None}):
            ch = WindowsToastChannel(app_name="weebot-test")
            result = await ch.send(self._make_notification())
        assert result is False

    @pytest.mark.asyncio
    async def test_urgent_notification_uses_looping_audio(self):
        mock_winotify = MagicMock()
        mock_toast = MagicMock()
        mock_winotify.Notification.return_value = mock_toast
        mock_winotify.audio = MagicMock()
        with patch.dict("sys.modules", {"winotify": mock_winotify}):
            ch = WindowsToastChannel(app_name="weebot-test")
            await ch.send(self._make_notification(category="urgent"))
        mock_toast.set_audio.assert_called_once()

    def test_category_to_icon_mapping(self):
        ch = WindowsToastChannel(app_name="weebot-test")
        assert ch._icon_for_category("urgent") == "ms-appx:///Assets/urgent.png" or \
               isinstance(ch._icon_for_category("urgent"), str)
        assert ch._icon_for_category("info") == ch._icon_for_category("unknown_cat")
```

**Step 3: Run to verify failure**

```
pytest tests/unit/test_windows_toast.py -v
```
Expected: FAIL — `WindowsToastChannel` not importable.

**Step 4: Implement `WindowsToastChannel` in `weebot/notifications.py`**

Add at the end of `notifications.py`:

```python
class WindowsToastChannel:
    """Windows 10/11 native toast notification channel via winotify."""

    CATEGORY_ICONS: Dict[str, str] = {
        "health":   "ms-appx:///Assets/StoreLogo.png",
        "urgent":   "ms-appx:///Assets/StoreLogo.png",
        "reminder": "ms-appx:///Assets/StoreLogo.png",
        "email":    "ms-appx:///Assets/StoreLogo.png",
        "calendar": "ms-appx:///Assets/StoreLogo.png",
        "build":    "ms-appx:///Assets/StoreLogo.png",
        "error":    "ms-appx:///Assets/StoreLogo.png",
        "info":     "ms-appx:///Assets/StoreLogo.png",
    }

    def __init__(self, app_name: str = "weebot") -> None:
        self.app_name = app_name

    def _icon_for_category(self, category: str) -> str:
        return self.CATEGORY_ICONS.get(category, self.CATEGORY_ICONS["info"])

    async def send(self, notification: "Notification") -> bool:
        try:
            import winotify
        except (ImportError, TypeError):
            return False

        try:
            toast = winotify.Notification(
                app_id=self.app_name,
                title=notification.title,
                msg=notification.message,
                icon=self._icon_for_category(getattr(notification, "category", "info")),
            )
            if getattr(notification, "category", "info") == "urgent":
                toast.set_audio(winotify.audio.Default, loop=True)
            toast.show()
            return True
        except Exception as e:
            print(f"Windows toast failed: {e}")
            return False
```

Also update `NotificationManager.__init__` to auto-add `WindowsToastChannel` on Windows:

```python
import sys as _sys
if _sys.platform == "win32":
    self.channels.append(WindowsToastChannel())
```

**Step 5: Run tests**

```
pytest tests/unit/test_windows_toast.py -v
```
Expected: all PASS.

**Step 6: Full suite**

```
pytest tests/ -v --tb=short
```

**Step 7: Commit**

```bash
git add weebot/notifications.py tests/unit/test_windows_toast.py requirements.txt
git commit -m "feat: add Windows toast notification channel via winotify"
```

---

## Task 4: Screen Capture Tool

**Files:**
- Create: `weebot/tools/screen_tool.py`
- Modify: `requirements.txt`
- Test: `tests/unit/test_screen_tool.py`

**Context:** `mss` captures the screen with no win32 dependency. Returns raw bytes (PNG) or saves to file. Exposes two operations: `list_screens()` (monitor list) and `capture(monitor_index)` (screenshot). Follows the same return signature as other tools: `{"success": bool, "output": str, "data": bytes | None}`.

**Step 1: Install**

```bash
pip install mss
```

Add to `requirements.txt` under `# Windows Integration`:
```
mss>=9.0.0
```

**Step 2: Write tests**

```python
# tests/unit/test_screen_tool.py
"""Unit tests for ScreenCaptureTool."""
import pytest
from unittest.mock import patch, MagicMock
from weebot.tools.screen_tool import ScreenCaptureTool


class TestListScreens:
    def test_returns_list(self):
        mock_mss = MagicMock()
        mock_mss.return_value.__enter__ = MagicMock(return_value=mock_mss.return_value)
        mock_mss.return_value.__exit__ = MagicMock(return_value=False)
        mock_mss.return_value.monitors = [
            {"left": 0, "top": 0, "width": 1920, "height": 1080}
        ]
        with patch("weebot.tools.screen_tool.mss", mock_mss):
            tool = ScreenCaptureTool()
            result = tool.list_screens()
        assert isinstance(result, list)

    def test_returns_dict_per_monitor(self):
        mock_mss = MagicMock()
        mock_mss.return_value.__enter__ = MagicMock(return_value=mock_mss.return_value)
        mock_mss.return_value.__exit__ = MagicMock(return_value=False)
        mock_mss.return_value.monitors = [
            {"left": 0, "top": 0, "width": 1920, "height": 1080}
        ]
        with patch("weebot.tools.screen_tool.mss", mock_mss):
            tool = ScreenCaptureTool()
            screens = tool.list_screens()
        for s in screens:
            assert "index" in s
            assert "width" in s
            assert "height" in s


class TestCapture:
    def _make_mock_mss(self):
        mock_img = MagicMock()
        mock_img.rgb = b"\xff\x00\x00" * 100
        mock_img.width = 10
        mock_img.height = 10
        mock_ctx = MagicMock()
        mock_ctx.monitors = [{"left": 0, "top": 0, "width": 1920, "height": 1080}]
        mock_ctx.grab.return_value = mock_img
        mock_mss = MagicMock()
        mock_mss.return_value.__enter__ = MagicMock(return_value=mock_ctx)
        mock_mss.return_value.__exit__ = MagicMock(return_value=False)
        return mock_mss

    def test_capture_returns_success(self):
        with patch("weebot.tools.screen_tool.mss", self._make_mock_mss()):
            with patch("weebot.tools.screen_tool.Image"):
                tool = ScreenCaptureTool()
                result = tool.capture(monitor_index=0)
        assert result["success"] is True

    def test_capture_result_has_data_key(self):
        with patch("weebot.tools.screen_tool.mss", self._make_mock_mss()):
            with patch("weebot.tools.screen_tool.Image"):
                tool = ScreenCaptureTool()
                result = tool.capture(monitor_index=0)
        assert "data" in result

    def test_capture_invalid_index_returns_error(self):
        mock_mss = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.monitors = [{"left": 0, "top": 0, "width": 1920, "height": 1080}]
        mock_mss.return_value.__enter__ = MagicMock(return_value=mock_ctx)
        mock_mss.return_value.__exit__ = MagicMock(return_value=False)
        with patch("weebot.tools.screen_tool.mss", mock_mss):
            tool = ScreenCaptureTool()
            result = tool.capture(monitor_index=999)
        assert result["success"] is False
        assert "error" in result["output"].lower() or "invalid" in result["output"].lower()
```

**Step 3: Run to verify failure**

```
pytest tests/unit/test_screen_tool.py -v
```
Expected: FAIL — module does not exist.

**Step 4: Implement `weebot/tools/screen_tool.py`**

```python
"""Screen capture tool using mss."""
import io
from typing import Any, Dict, List

try:
    import mss
    import mss.tools
    _MSS_AVAILABLE = True
except ImportError:
    _MSS_AVAILABLE = False

try:
    from PIL import Image
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False


class ScreenCaptureTool:
    """Capture screenshots of any connected monitor."""

    def list_screens(self) -> List[Dict[str, Any]]:
        """Return metadata for each connected monitor."""
        if not _MSS_AVAILABLE:
            return []
        with mss.mss() as sct:
            return [
                {"index": i, "width": m["width"], "height": m["height"],
                 "left": m["left"], "top": m["top"]}
                for i, m in enumerate(sct.monitors)
            ]

    def capture(self, monitor_index: int = 0, save_path: str = None) -> Dict[str, Any]:
        """
        Capture a screenshot.

        Returns:
            {"success": bool, "output": str, "data": bytes | None}
            data is PNG bytes if success, None otherwise.
        """
        if not _MSS_AVAILABLE:
            return {"success": False, "output": "mss not installed", "data": None}

        try:
            with mss.mss() as sct:
                monitors = sct.monitors
                if monitor_index >= len(monitors):
                    return {
                        "success": False,
                        "output": f"Invalid monitor index {monitor_index} (max {len(monitors)-1})",
                        "data": None,
                    }
                screenshot = sct.grab(monitors[monitor_index])

                # Convert to PNG bytes via Pillow
                if _PIL_AVAILABLE:
                    img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)
                    buf = io.BytesIO()
                    img.save(buf, format="PNG")
                    png_bytes = buf.getvalue()
                else:
                    png_bytes = mss.tools.to_png(screenshot.rgb, screenshot.size)

                if save_path:
                    with open(save_path, "wb") as f:
                        f.write(png_bytes)

                return {
                    "success": True,
                    "output": f"Captured monitor {monitor_index} ({screenshot.width}x{screenshot.height})",
                    "data": png_bytes,
                }
        except Exception as e:
            return {"success": False, "output": f"Capture error: {e}", "data": None}
```

**Step 5: Run tests**

```
pytest tests/unit/test_screen_tool.py -v
```

**Step 6: Full suite**

```
pytest tests/ -v --tb=short
```

**Step 7: Commit**

```bash
git add weebot/tools/screen_tool.py tests/unit/test_screen_tool.py requirements.txt
git commit -m "feat: add screen capture tool via mss"
```

---

## Task 5: ExecApprovalPolicy

**Files:**
- Create: `weebot/core/approval_policy.py`
- Modify: `weebot/core/safety.py` (use policy instead of global `CONFIRM_DELETE`)
- Test: `tests/unit/test_approval_policy.py`

**Context:** Port OpenClaw's `ExecApprovalPolicy`. Replaces the binary `CONFIRM_DELETE` global with a flexible policy engine: per-command whitelist/blacklist, undo hints, approval mode (auto-approve / always-ask / deny). The `SafetyChecker` checks the policy before generating Plan B.

**Step 1: Write tests**

```python
# tests/unit/test_approval_policy.py
"""Unit tests for ExecApprovalPolicy."""
import pytest
from weebot.core.approval_policy import ExecApprovalPolicy, ApprovalMode, CommandRule


class TestDefaultPolicy:
    def setup_method(self):
        self.policy = ExecApprovalPolicy()

    def test_non_critical_command_auto_approved(self):
        result = self.policy.evaluate("Get-ChildItem C:\\")
        assert result.approved is True
        assert result.requires_confirmation is False

    def test_delete_command_requires_confirmation_by_default(self):
        result = self.policy.evaluate("Remove-Item old_logs")
        assert result.requires_confirmation is True

    def test_format_command_denied_by_default(self):
        result = self.policy.evaluate("Format-Volume C")
        assert result.approved is False

    def test_result_has_undo_hint(self):
        result = self.policy.evaluate("Remove-Item log.txt")
        assert isinstance(result.undo_hint, str)


class TestCustomRules:
    def test_whitelist_rule_auto_approves(self):
        policy = ExecApprovalPolicy(rules=[
            CommandRule(pattern="Get-Process", mode=ApprovalMode.AUTO_APPROVE),
        ])
        result = policy.evaluate("Get-Process chrome")
        assert result.approved is True
        assert result.requires_confirmation is False

    def test_deny_rule_blocks_command(self):
        policy = ExecApprovalPolicy(rules=[
            CommandRule(pattern="curl", mode=ApprovalMode.DENY),
        ])
        result = policy.evaluate("curl http://example.com")
        assert result.approved is False

    def test_ask_rule_requires_confirmation(self):
        policy = ExecApprovalPolicy(rules=[
            CommandRule(pattern="npm install", mode=ApprovalMode.ALWAYS_ASK),
        ])
        result = policy.evaluate("npm install --save-dev")
        assert result.requires_confirmation is True

    def test_most_specific_rule_wins(self):
        policy = ExecApprovalPolicy(rules=[
            CommandRule(pattern="Remove-Item", mode=ApprovalMode.ALWAYS_ASK),
            CommandRule(pattern="Remove-Item C:\\Windows", mode=ApprovalMode.DENY),
        ])
        result = policy.evaluate("Remove-Item C:\\Windows\\system32")
        assert result.approved is False


class TestApprovalResult:
    def test_result_contains_command(self):
        policy = ExecApprovalPolicy()
        result = policy.evaluate("Get-ChildItem")
        assert result.command == "Get-ChildItem"
```

**Step 2: Run to verify failure**

```
pytest tests/unit/test_approval_policy.py -v
```

**Step 3: Implement `weebot/core/approval_policy.py`**

```python
"""Granular command execution approval policy (ported from OpenClaw)."""
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class ApprovalMode(Enum):
    AUTO_APPROVE = "auto_approve"
    ALWAYS_ASK   = "always_ask"
    DENY         = "deny"


@dataclass
class CommandRule:
    pattern: str
    mode: ApprovalMode
    is_regex: bool = False
    undo_hint: str = ""


@dataclass
class ApprovalResult:
    command: str
    approved: bool
    requires_confirmation: bool
    undo_hint: str
    reason: str = ""


# Built-in defaults: destructive → ask, format → deny, rest → auto
_DEFAULT_RULES: List[CommandRule] = [
    CommandRule("format", ApprovalMode.DENY,
                undo_hint="Formatting is irreversible. Use Diskpart carefully."),
    CommandRule("remove-item",   ApprovalMode.ALWAYS_ASK,
                undo_hint="Move to Recycle Bin first: Remove-Item -Confirm"),
    CommandRule("del ",          ApprovalMode.ALWAYS_ASK,
                undo_hint="Consider 'move' instead of permanent delete."),
    CommandRule("rm ",           ApprovalMode.ALWAYS_ASK,
                undo_hint="Consider 'mv' to a temp folder first."),
    CommandRule("stop-process",  ApprovalMode.ALWAYS_ASK,
                undo_hint="Note the PID before stopping in case restart is needed."),
    CommandRule("kill",          ApprovalMode.ALWAYS_ASK,
                undo_hint="Save PID/name before killing."),
]


class ExecApprovalPolicy:
    """
    Evaluates whether a shell command needs confirmation or should be denied.
    Rules are checked longest-match first (most specific wins).
    """

    def __init__(self, rules: Optional[List[CommandRule]] = None) -> None:
        # User rules first, then built-in defaults
        self._rules = (rules or []) + _DEFAULT_RULES

    def evaluate(self, command: str) -> ApprovalResult:
        cmd_lower = command.lower()

        # Find all matching rules, pick the most specific (longest pattern match)
        matches = []
        for rule in self._rules:
            if rule.is_regex:
                if re.search(rule.pattern, command, re.IGNORECASE):
                    matches.append(rule)
            else:
                if rule.pattern.lower() in cmd_lower:
                    matches.append(rule)

        if matches:
            # Most specific = longest pattern
            best = max(matches, key=lambda r: len(r.pattern))
            if best.mode == ApprovalMode.DENY:
                return ApprovalResult(
                    command=command, approved=False,
                    requires_confirmation=False,
                    undo_hint=best.undo_hint,
                    reason=f"Command denied by policy: {best.pattern}",
                )
            if best.mode == ApprovalMode.ALWAYS_ASK:
                return ApprovalResult(
                    command=command, approved=True,
                    requires_confirmation=True,
                    undo_hint=best.undo_hint,
                    reason="Confirmation required before execution.",
                )
            # AUTO_APPROVE
            return ApprovalResult(
                command=command, approved=True,
                requires_confirmation=False,
                undo_hint=best.undo_hint,
            )

        # No rule matched → auto-approve
        return ApprovalResult(
            command=command, approved=True,
            requires_confirmation=False,
            undo_hint="",
        )
```

**Step 4: Wire into `SafetyChecker`**

In `weebot/core/safety.py`, replace `CONFIRM_DELETE = True` usage:

```python
# Add import at top:
from weebot.core.approval_policy import ExecApprovalPolicy

# In SafetyChecker.__init__:
self.approval_policy = ExecApprovalPolicy()

# Update generate_plan_b return:
approval = self.approval_policy.evaluate(original_action)
return {
    "simulation_result": self._parse_safety_response(result.content),
    "original_action": original_action,
    "proceed": not approval.requires_confirmation,
    "undo_hint": approval.undo_hint,
}
```

**Step 5: Run tests**

```
pytest tests/unit/test_approval_policy.py tests/unit/test_safety.py -v
```
Expected: all PASS (safety tests still pass because `proceed` logic unchanged for default case).

**Step 6: Full suite**

```
pytest tests/ -v --tb=short
```

**Step 7: Commit**

```bash
git add weebot/core/approval_policy.py weebot/core/safety.py \
        tests/unit/test_approval_policy.py
git commit -m "feat: add ExecApprovalPolicy replacing binary CONFIRM_DELETE flag"
```

---

## Task 6: Sub-Sessions in StateManager

**Files:**
- Modify: `weebot/state_manager.py`
- Modify: `tests/integration/test_state_manager.py`

**Context:** Port OpenClaw's session model. Add `sub_sessions: List[SubSession]` to `ProjectState`. Each `SubSession` has `session_id`, `name`, `status`, `activity_kind` (Idle/Job/Exec/Read/Write/Search/Browser/Message), `started_at`, `ended_at`. The `ResumableTask` creates a sub-session automatically.

**Step 1: Write the new tests** (add class to existing integration test file)

```python
# Add to tests/integration/test_state_manager.py:

class TestSubSessions:
    def test_create_project_has_empty_sub_sessions(self, sm):
        state = sm.create_project("ss-proj", "sub-session test")
        assert state.sub_sessions == []

    def test_start_sub_session_adds_entry(self, sm):
        sm.create_project("ss-proj2", "test")
        sm.start_sub_session("ss-proj2", "task_a", activity_kind="exec")
        state = sm.load_state("ss-proj2")
        assert len(state.sub_sessions) == 1
        assert state.sub_sessions[0].name == "task_a"
        assert state.sub_sessions[0].activity_kind == "exec"

    def test_end_sub_session_sets_ended_at(self, sm):
        sm.create_project("ss-proj3", "test")
        sm.start_sub_session("ss-proj3", "task_b", activity_kind="read")
        sm.end_sub_session("ss-proj3", "task_b", status="completed")
        state = sm.load_state("ss-proj3")
        assert state.sub_sessions[0].ended_at is not None
        assert state.sub_sessions[0].status == "completed"

    def test_multiple_sub_sessions_tracked(self, sm):
        sm.create_project("ss-proj4", "test")
        sm.start_sub_session("ss-proj4", "step1", activity_kind="job")
        sm.start_sub_session("ss-proj4", "step2", activity_kind="write")
        state = sm.load_state("ss-proj4")
        assert len(state.sub_sessions) == 2
```

**Step 2: Run to verify new tests fail**

```
pytest tests/integration/test_state_manager.py::TestSubSessions -v
```

**Step 3: Implement in `weebot/state_manager.py`**

Add `SubSession` dataclass and extend `ProjectState`:

```python
from typing import Optional, Dict, Any, List  # already there
# Add after ProjectStatus enum:

ACTIVITY_KINDS = {"idle", "job", "exec", "read", "write", "edit",
                  "search", "browser", "message", "tool"}


@dataclass
class SubSession:
    session_id: str
    name: str
    activity_kind: str
    status: str = "running"     # running / completed / failed
    started_at: datetime = None
    ended_at: Optional[datetime] = None

    def __post_init__(self):
        if self.started_at is None:
            self.started_at = datetime.now()
```

In `ProjectState.__post_init__`, add:
```python
if self.sub_sessions is None:
    self.sub_sessions = []
```

Add field to `ProjectState`:
```python
sub_sessions: List["SubSession"] = None
```

Add methods to `StateManager`:

```python
def start_sub_session(self, project_id: str, name: str,
                      activity_kind: str = "job") -> str:
    """Create and persist a new sub-session."""
    state = self.load_state(project_id)
    if not state:
        raise ValueError(f"Project {project_id} not found")
    session_id = f"ss_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    state.sub_sessions.append(SubSession(
        session_id=session_id,
        name=name,
        activity_kind=activity_kind,
    ))
    self.save_state(state)
    return session_id

def end_sub_session(self, project_id: str, name: str,
                    status: str = "completed") -> None:
    """Mark a sub-session as ended."""
    state = self.load_state(project_id)
    if not state:
        return
    for ss in state.sub_sessions:
        if ss.name == name and ss.ended_at is None:
            ss.ended_at = datetime.now()
            ss.status = status
            break
    self.save_state(state)
```

**Step 4: Auto-track in `ResumableTask`**

In `__aenter__`:
```python
self.sm.start_sub_session(self.project_id, self.task_name, activity_kind="job")
```

In `__aexit__` success branch:
```python
self.sm.end_sub_session(self.project_id, self.task_name, status="completed")
```

In `__aexit__` failure branch:
```python
self.sm.end_sub_session(self.project_id, self.task_name, status="failed")
```

**Step 5: Run tests**

```
pytest tests/integration/test_state_manager.py -v
```

**Step 6: Full suite**

```
pytest tests/ -v --tb=short
```

**Step 7: Commit**

```bash
git add weebot/state_manager.py tests/integration/test_state_manager.py
git commit -m "feat: add sub-sessions tracking with activity kinds to StateManager"
```

---

## Task 7: Activity Stream

**Files:**
- Create: `weebot/activity_stream.py`
- Test: `tests/unit/test_activity_stream.py`

**Context:** In-memory ring buffer of recent agent events. Each event has `timestamp`, `kind` (from ACTIVITY_KINDS), `message`, `project_id`. `WeebotAgent` pushes events. CLI and tray can poll for display. Max 200 events in memory, overflow drops oldest.

**Step 1: Write tests**

```python
# tests/unit/test_activity_stream.py
"""Unit tests for ActivityStream."""
import pytest
from datetime import datetime
from weebot.activity_stream import ActivityStream, ActivityEvent


class TestActivityStream:
    def test_starts_empty(self):
        stream = ActivityStream()
        assert stream.recent() == []

    def test_push_adds_event(self):
        stream = ActivityStream()
        stream.push("proj-1", "job", "Started analysis")
        assert len(stream.recent()) == 1

    def test_recent_returns_newest_first(self):
        stream = ActivityStream()
        stream.push("p", "job", "first")
        stream.push("p", "tool", "second")
        events = stream.recent()
        assert events[0].message == "second"

    def test_recent_n_limits_results(self):
        stream = ActivityStream()
        for i in range(10):
            stream.push("p", "job", f"event {i}")
        assert len(stream.recent(n=3)) == 3

    def test_overflow_drops_oldest(self):
        stream = ActivityStream(max_size=5)
        for i in range(7):
            stream.push("p", "job", f"event {i}")
        events = stream.recent()
        assert len(events) == 5
        assert events[-1].message == "event 2"  # oldest kept

    def test_filter_by_project(self):
        stream = ActivityStream()
        stream.push("proj-a", "job", "task A")
        stream.push("proj-b", "job", "task B")
        filtered = stream.recent(project_id="proj-a")
        assert all(e.project_id == "proj-a" for e in filtered)
        assert len(filtered) == 1

    def test_event_has_timestamp(self):
        stream = ActivityStream()
        stream.push("p", "exec", "ran command")
        assert isinstance(stream.recent()[0].timestamp, datetime)

    def test_clear_empties_stream(self):
        stream = ActivityStream()
        stream.push("p", "job", "something")
        stream.clear()
        assert stream.recent() == []
```

**Step 2: Run to verify failure**

```
pytest tests/unit/test_activity_stream.py -v
```

**Step 3: Implement `weebot/activity_stream.py`**

```python
"""In-memory activity stream — ring buffer of recent agent events."""
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Deque, List, Optional


@dataclass
class ActivityEvent:
    project_id: str
    kind: str          # job / exec / read / write / tool / message / etc.
    message: str
    timestamp: datetime = field(default_factory=datetime.now)


class ActivityStream:
    """Thread-safe ring buffer of agent activity events."""

    def __init__(self, max_size: int = 200) -> None:
        self._buffer: Deque[ActivityEvent] = deque(maxlen=max_size)

    def push(self, project_id: str, kind: str, message: str) -> None:
        """Add a new event to the stream."""
        self._buffer.appendleft(ActivityEvent(
            project_id=project_id,
            kind=kind,
            message=message,
        ))

    def recent(self, n: int = 50,
               project_id: Optional[str] = None) -> List[ActivityEvent]:
        """Return the n most recent events, optionally filtered by project."""
        events = list(self._buffer)
        if project_id:
            events = [e for e in events if e.project_id == project_id]
        return events[:n]

    def clear(self) -> None:
        self._buffer.clear()
```

**Step 4: Wire into `WeebotAgent`**

In `weebot/agent_core_v2.py`:

```python
# Add import:
from weebot.activity_stream import ActivityStream

# In WeebotAgent.__init__:
self.activity_stream = ActivityStream()

# In run() before each task loop iteration:
self.activity_stream.push(self.config.project_id, "job", f"Starting task: {task_name}")

# In get_status():
"recent_activity": [
    {"kind": e.kind, "message": e.message,
     "timestamp": e.timestamp.isoformat()}
    for e in self.activity_stream.recent(n=10, project_id=self.config.project_id)
],
```

**Step 5: Run tests**

```
pytest tests/unit/test_activity_stream.py -v
```

**Step 6: Full suite**

```
pytest tests/ -v --tb=short
```

**Step 7: Commit**

```bash
git add weebot/activity_stream.py weebot/agent_core_v2.py \
        tests/unit/test_activity_stream.py
git commit -m "feat: add ActivityStream ring buffer for real-time agent monitoring"
```

---

## Task 8: Reconnect with Exponential Backoff

**Files:**
- Create: `weebot/utils/backoff.py`
- Modify: `weebot/notifications.py` (wrap `TelegramChannel.send` with backoff)
- Test: `tests/unit/test_backoff.py`

**Context:** Port OpenClaw's reconnect strategy: delays 1s → 2s → 4s → 8s → 15s → 30s → 60s (max), then resets on success. Implement as a standalone `RetryWithBackoff` async context manager usable anywhere. Apply to Telegram channel sends.

**Step 1: Write tests**

```python
# tests/unit/test_backoff.py
"""Unit tests for exponential backoff retry utility."""
import pytest
import asyncio
from unittest.mock import AsyncMock, patch
from weebot.utils.backoff import RetryWithBackoff, BackoffConfig


class TestBackoffConfig:
    def test_default_delays(self):
        cfg = BackoffConfig()
        assert cfg.delays == [1, 2, 4, 8, 15, 30, 60]

    def test_max_delay_capped(self):
        cfg = BackoffConfig(delays=[1, 2, 4], max_delay=3)
        assert all(d <= 3 for d in cfg.delays)

    def test_custom_delays(self):
        cfg = BackoffConfig(delays=[0.1, 0.2, 0.4])
        assert cfg.delays == [0.1, 0.2, 0.4]


class TestRetryWithBackoff:
    @pytest.mark.asyncio
    async def test_succeeds_on_first_try(self):
        mock_fn = AsyncMock(return_value="ok")
        retry = RetryWithBackoff(BackoffConfig(delays=[0.01]))
        result = await retry.call(mock_fn)
        assert result == "ok"
        assert mock_fn.call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_failure(self):
        mock_fn = AsyncMock(side_effect=[Exception("fail"), Exception("fail"), "ok"])
        retry = RetryWithBackoff(BackoffConfig(delays=[0.01, 0.01, 0.01]))
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await retry.call(mock_fn)
        assert result == "ok"
        assert mock_fn.call_count == 3

    @pytest.mark.asyncio
    async def test_raises_after_all_retries_exhausted(self):
        mock_fn = AsyncMock(side_effect=Exception("always fails"))
        retry = RetryWithBackoff(BackoffConfig(delays=[0.01]))
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(Exception, match="always fails"):
                await retry.call(mock_fn)

    @pytest.mark.asyncio
    async def test_resets_delay_index_after_success(self):
        calls = []
        async def fn():
            calls.append(1)
            if len(calls) < 3:
                raise Exception("not yet")
            return "done"
        retry = RetryWithBackoff(BackoffConfig(delays=[0.01, 0.01, 0.01]))
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await retry.call(fn)
        assert retry._delay_index == 0  # reset after success
```

**Step 2: Run to verify failure**

```
pytest tests/unit/test_backoff.py -v
```

**Step 3: Implement `weebot/utils/backoff.py`**

```python
"""Exponential backoff retry utility (ported from OpenClaw gateway client)."""
import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional


@dataclass
class BackoffConfig:
    delays: List[float] = field(default_factory=lambda: [1, 2, 4, 8, 15, 30, 60])
    max_delay: Optional[float] = None

    def __post_init__(self):
        if self.max_delay is not None:
            self.delays = [min(d, self.max_delay) for d in self.delays]


class RetryWithBackoff:
    """
    Async retry helper with configurable exponential backoff.

    Usage:
        retry = RetryWithBackoff()
        result = await retry.call(my_async_fn, arg1, arg2)
    """

    def __init__(self, config: Optional[BackoffConfig] = None) -> None:
        self._config = config or BackoffConfig()
        self._delay_index = 0

    async def call(self, fn: Callable, *args, **kwargs) -> Any:
        last_exc: Optional[Exception] = None
        attempts = len(self._config.delays) + 1

        for attempt in range(attempts):
            try:
                result = await fn(*args, **kwargs)
                self._delay_index = 0   # reset on success
                return result
            except Exception as exc:
                last_exc = exc
                if attempt < len(self._config.delays):
                    delay = self._config.delays[attempt]
                    self._delay_index = attempt + 1
                    await asyncio.sleep(delay)

        raise last_exc
```

**Step 4: Apply to `TelegramChannel`**

In `weebot/notifications.py`:

```python
# Add import:
from weebot.utils.backoff import RetryWithBackoff, BackoffConfig

# In TelegramChannel.__init__:
self._retry = RetryWithBackoff(BackoffConfig(delays=[1, 2, 4]))

# Wrap the HTTP post in send():
async def _post(session):
    async with session.post(f"{self.api_url}/sendMessage", json=payload) as resp:
        return resp.status == 200

async with aiohttp.ClientSession() as session:
    return await self._retry.call(_post, session)
```

**Step 5: Run tests**

```
pytest tests/unit/test_backoff.py -v
```

**Step 6: Full suite**

```
pytest tests/ -v --tb=short
```

**Step 7: Commit**

```bash
git add weebot/utils/backoff.py weebot/notifications.py \
        tests/unit/test_backoff.py
git commit -m "feat: add exponential backoff retry utility, apply to Telegram channel"
```

---

## Task 9: System Tray App

**Files:**
- Create: `weebot/tray.py`
- Modify: `requirements.txt`
- Test: `tests/unit/test_tray.py`

**Context:** `pystray` creates a system tray icon on Windows. The tray shows connection status (green/amber/red), a context menu with project list, quick actions (run/pause/status), and notifications count. It runs the existing `WeebotAgent` in a background asyncio thread. This is a standalone entry point — `python -m weebot.tray` or `run.py --tray`.

**Step 1: Install**

```bash
pip install pystray
```

Add to `requirements.txt`:
```
pystray>=0.19.0; platform_system=="Windows"
```

**Step 2: Write tests (focus on non-GUI logic)**

```python
# tests/unit/test_tray.py
"""Unit tests for tray app non-GUI logic."""
import pytest
from unittest.mock import MagicMock, patch
from weebot.tray import TrayStatusIcon, TrayStatus


class TestTrayStatus:
    def test_status_enum_has_expected_values(self):
        assert TrayStatus.CONNECTED.value == "connected"
        assert TrayStatus.CONNECTING.value == "connecting"
        assert TrayStatus.DISCONNECTED.value == "disconnected"
        assert TrayStatus.ERROR.value == "error"


class TestTrayStatusIcon:
    def test_initial_status_is_disconnected(self):
        icon = TrayStatusIcon.__new__(TrayStatusIcon)
        icon._status = TrayStatus.DISCONNECTED
        assert icon._status == TrayStatus.DISCONNECTED

    def test_status_to_color_mapping(self):
        icon = TrayStatusIcon.__new__(TrayStatusIcon)
        assert icon._color_for_status(TrayStatus.CONNECTED) == "green"
        assert icon._color_for_status(TrayStatus.CONNECTING) == "orange"
        assert icon._color_for_status(TrayStatus.ERROR) == "red"
        assert icon._color_for_status(TrayStatus.DISCONNECTED) == "gray"

    def test_generate_icon_returns_pil_image(self):
        from PIL import Image
        icon = TrayStatusIcon.__new__(TrayStatusIcon)
        img = icon._generate_icon_image("green")
        assert isinstance(img, Image.Image)

    def test_build_menu_items_returns_list(self):
        with patch("weebot.tray.pystray", MagicMock()):
            icon = TrayStatusIcon.__new__(TrayStatusIcon)
            icon._status = TrayStatus.DISCONNECTED
            icon._agent = None
            items = icon._build_menu_items()
            assert isinstance(items, list)
            assert len(items) > 0
```

**Step 3: Run to verify failure**

```
pytest tests/unit/test_tray.py -v
```

**Step 4: Implement `weebot/tray.py`**

```python
"""System tray application for weebot (pystray-based)."""
import asyncio
import threading
from enum import Enum
from typing import List, Optional

try:
    import pystray
    _PYSTRAY_AVAILABLE = True
except ImportError:
    _PYSTRAY_AVAILABLE = False

from PIL import Image, ImageDraw


class TrayStatus(Enum):
    CONNECTED    = "connected"
    CONNECTING   = "connecting"
    DISCONNECTED = "disconnected"
    ERROR        = "error"


class TrayStatusIcon:
    """Manages a system tray icon that reflects weebot agent status."""

    STATUS_COLORS = {
        TrayStatus.CONNECTED:    "green",
        TrayStatus.CONNECTING:   "orange",
        TrayStatus.DISCONNECTED: "gray",
        TrayStatus.ERROR:        "red",
    }

    def __init__(self) -> None:
        self._status = TrayStatus.DISCONNECTED
        self._agent = None
        self._icon = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def _color_for_status(self, status: TrayStatus) -> str:
        return self.STATUS_COLORS.get(status, "gray")

    def _generate_icon_image(self, color: str) -> Image.Image:
        """Draw a 64x64 circle icon in the given color."""
        size = 64
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([(4, 4), (size - 4, size - 4)], fill=color)
        return img

    def _build_menu_items(self) -> list:
        if not _PYSTRAY_AVAILABLE:
            return []
        items = [
            pystray.MenuItem(
                f"Status: {self._status.value.capitalize()}",
                None,
                enabled=False,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Show Status", self._on_show_status),
            pystray.MenuItem("Quit", self._on_quit),
        ]
        return items

    def _on_show_status(self, icon, item) -> None:
        if self._agent:
            status = self._agent.get_status()
            print(f"[weebot] {status}")

    def _on_quit(self, icon, item) -> None:
        icon.stop()

    def set_status(self, status: TrayStatus) -> None:
        self._status = status
        if self._icon:
            self._icon.icon = self._generate_icon_image(
                self._color_for_status(status)
            )
            self._icon.menu = pystray.Menu(*self._build_menu_items())

    def run(self) -> None:
        """Start the tray icon (blocking — call from main thread)."""
        if not _PYSTRAY_AVAILABLE:
            print("pystray not installed. Run: pip install pystray")
            return

        self._icon = pystray.Icon(
            name="weebot",
            icon=self._generate_icon_image(self._color_for_status(self._status)),
            title="weebot Agent",
            menu=pystray.Menu(*self._build_menu_items()),
        )
        self._icon.run()


def main() -> None:
    """Entry point for tray app."""
    tray = TrayStatusIcon()
    tray.set_status(TrayStatus.CONNECTING)
    tray.run()


if __name__ == "__main__":
    main()
```

**Step 5: Add `--tray` flag to `run.py`**

```python
# In run.py argparse section, add:
parser.add_argument("--tray", action="store_true", help="Run system tray app")

# In main block:
elif args.tray:
    from weebot.tray import main as run_tray
    run_tray()
```

**Step 6: Run tests**

```
pytest tests/unit/test_tray.py -v
```

**Step 7: Full suite**

```
pytest tests/ -v --tb=short
```

Expected: all 100+ tests PASS.

**Step 8: Commit**

```bash
git add weebot/tray.py run.py tests/unit/test_tray.py requirements.txt
git commit -m "feat: add system tray app with status icon via pystray"
```

---

## Final Verification

After all 9 tasks:

```bash
# Install new dependencies
pip install winotify mss pystray

# Run full test suite
pytest tests/ -v --tb=short

# Check all imports work
python -c "from weebot.utils.logger import AgentLogger; print('logger OK')"
python -c "from weebot.notifications_categorizer import NotificationCategorizer; print('categorizer OK')"
python -c "from weebot.notifications import WindowsToastChannel; print('toast OK')"
python -c "from weebot.tools.screen_tool import ScreenCaptureTool; print('screen OK')"
python -c "from weebot.core.approval_policy import ExecApprovalPolicy; print('policy OK')"
python -c "from weebot.activity_stream import ActivityStream; print('activity OK')"
python -c "from weebot.utils.backoff import RetryWithBackoff; print('backoff OK')"
python -c "from weebot.tray import TrayStatusIcon; print('tray OK')"

# Verify diagnostic still passes
python run.py --diagnostic
```

---

## Dependency Summary

New packages to add to `requirements.txt`:

```
# New (Tasks 3, 4, 9)
winotify>=1.1.0; platform_system=="Windows"
mss>=9.0.0
pystray>=0.19.0; platform_system=="Windows"
```

Install command:
```bash
pip install winotify mss pystray
```
