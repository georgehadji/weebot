---
name: desktop-automation
description: Automate desktop applications on Windows/Mac/Linux using mouse, keyboard, screenshots, and accessibility tree enumeration. Covers window management, form filling, GUI testing, and multi-app workflows. Triggered for any desktop automation, RPA, GUI scripting, or application control task.
metadata:
  emoji: 🖥️
  trust: trusted
  provenance:
    origin: human
  requires_toolsets: ["computer_use"]
  fallback_for_toolsets: []
---

# Desktop Automation

You can control real desktop applications using screenshots, mouse/keyboard actions, and accessibility tree enumeration.

## Critical Rules

1. OBSERVE BEFORE YOU ACT — use `screen_capture` or `desktop_a11y` to understand the current state
2. VERIFY AFTER ACTING — take a screenshot after every action to confirm the intended effect
3. CHECK WINDOW FOCUS — use `get_active_window` before typing; use `focus_window` to switch apps
4. EXHAUST FALLBACKS — if one approach fails, try the next: a11y → OCR → fixed coordinates → CLI

## Tool Reference

| Goal | Tool | Action |
|---|---|---|
| See the desktop | `screen_capture` | `capture(monitor=0)` → returns PNG screenshot |
| List UI elements | `desktop_a11y` | Returns flat JSON of interactive elements |
| Move mouse | `computer_use` | `action="move_mouse", x=..., y=...` |
| Click | `computer_use` | `action="click", x=..., y=..., button="left"` |
| Double-click | `computer_use` | `action="double_click", x=..., y=...` |
| Type text | `computer_use` | `action="type", text="hello"` |
| Press key | `computer_use` | `action="press_key", key="enter"` |
| Hotkey | `computer_use` | `action="press_key", key="c", modifiers=["ctrl"]` |
| Check window | `computer_use` | `action="get_active_window"` |
| Focus window | `computer_use` | `action="focus_window", window_title="Notepad"` |
| Hover+verify | `computer_use` | `action="hover_and_verify", x=..., y=...` → returns screenshot |
| Element OCR | `screenshot_with_ocr` | Returns text positions on screen |

## Workflow Pattern

```
1. screen_capture           → See what's on screen
2. desktop_a11y             → Find interactive elements (name, role, position)
3. focus_window("AppName")  → Make sure correct window is active
4. computer_use click(x,y)  → Click the target element
5. screen_capture           → Verify the click worked
6. computer_use type(text)  → Enter data
7. screen_capture           → Confirm data entered correctly
```

## DPI Scaling

Use `dpi_scale` on `computer_use` actions when the target screen has different DPI than your local display:
- 125% scaling → `dpi_scale=1.25`
- 150% scaling → `dpi_scale=1.5`
- 200% (HiDPI/Retina) → `dpi_scale=2.0`

## Error Recovery

| Problem | Fix |
|---|---|
| Click missed target | Use `hover_and_verify` first, check screenshot, adjust coords |
| Wrong window focused | `get_active_window` → `focus_window` to correct app |
| Element not found in a11y | Fall back to `screen_capture` + visual inspection |
| Typing in wrong field | Click the field first, verify with screenshot, then type |
| Popup/dialog appeared | `screen_capture` → identify popup → dismiss (click close or press Escape) |
