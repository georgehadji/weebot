"""Replace prompt assembly block in _base.py with build_executor_prompt() call.

This script replaces the inline prompt assembly (lines 403-522) in
weebot/application/agents/executor/_base.py with a call to
build_executor_prompt() from _prompt_builder.py.

The replacement preserves:
- User profile lazy-init cache (loads before prompt builder call)
- OUTPUT_ROOT injection
- Persistent memory snapshot injection
- Conversation buffer building (unchanged)
- WORKSPACE_ROOT import
"""
from __future__ import annotations

import re
from pathlib import Path

BASE_PATH = Path("weebot/application/agents/executor/_base.py")


def replace_prompt_block(content: str) -> str:
    """Replace the inline prompt assembly block with a builder call."""

    # Add import if not present
    if "from weebot.application.agents.executor._prompt_builder import build_executor_prompt" not in content:
        content = content.replace(
            "from weebot.application.ports.event_bus_port import EventBusPort",
            "from weebot.application.agents.executor._prompt_builder import build_executor_prompt\nfrom weebot.application.ports.event_bus_port import EventBusPort",
        )

    # Find the boundaries of the old block
    old_start = "        system_prompt = self._load_prompt()"
    old_end = '            logger.warning("Persistent memory snapshot unavailable: %s", exc)'

    start_idx = content.find(old_start)
    end_idx = content.find(old_end) + len(old_end)

    if start_idx == -1 or end_idx == -1:
        print("ERROR: Block boundaries not found")
        return content

    old_block = content[start_idx:end_idx]

    new_block = """        base_prompt = self._load_prompt()

        # ── User profile from dialectic consolidation (lazy-init) ──
        if not hasattr(self, '_user_profile_cache'):
            try:
                import hashlib
                repo = self._state_repo
                if repo is not None:
                    key = hashlib.sha256(b"user_model_profile").hexdigest()[:16]
                    for row in await repo.get_low_salience_entries(threshold=1.01, limit=5):
                        if row.get("entry_hash") == key:
                            txt = row.get("entry_text", "")
                            self._user_profile_cache = txt[:500] if txt and txt != "No user data collected yet." else ""
                            break
                    else:
                        self._user_profile_cache = ""
                else:
                    self._user_profile_cache = ""
            except Exception:
                self._user_profile_cache = ""

        # ── Build system prompt via extracted builder ─────────────
        system_prompt = await build_executor_prompt(
            step_description=step.description,
            base_prompt=base_prompt,
            harness_block=self._harness_instruction_block,
            skill_prompt=self._skill_prompt,
            skill_retriever=self._skill_retriever,
            behavioral_learner=self._behavioral_learner,
            state_repo=self._state_repo,
            personality=self._personality,
            profile_name=self._profile_name,
        )

        # ── Append extra components not handled by builder ────────
        if getattr(self, '_user_profile_cache', ''):
            system_prompt += f"\\n\\n## User Profile\\n{self._user_profile_cache}"

        self._system_prompt = system_prompt
        # Inject OUTPUT_ROOT so tools resolve paths consistently
        from weebot.core.output_path import output_path as _op
        self._system_prompt = self._system_prompt + (
            f"\\n\\nOUTPUT_ROOT = {_op('Output')}"
            "\\nALL file writes MUST use this absolute path prefix. "
            'Example: Set-Content -Path "{OUTPUT_ROOT}/refactor/file.md" -Value \'...\''
        )
        # Inject persistent memory snapshot
        try:
            from weebot.tools.persistent_memory import PersistentMemoryTool
            snapshot = await PersistentMemoryTool.load_snapshot()
            if snapshot:
                self._system_prompt = self._system_prompt + "\\n\\n" + snapshot
        except Exception as exc:
            logger.warning("Persistent memory snapshot unavailable: %s", exc)"""

    content = content[:start_idx] + new_block + content[end_idx:]
    print(f"Replaced {len(old_block)} chars with {len(new_block)} chars")
    return content


def main():
    content = Path(BASE_PATH).read_text(encoding="utf-8")
    result = replace_prompt_block(content)
    Path(BASE_PATH).write_text(result, encoding="utf-8", newline="")
    print("Done")


if __name__ == "__main__":
    main()
