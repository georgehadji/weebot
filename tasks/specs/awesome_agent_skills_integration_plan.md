# awesome-agent-skills Integration Plan

**Repo audited:** `heilcheng/awesome-agent-skills` (5,500+ stars)  
**Target:** Wire the curated index of 300+ SKILL.md-format skills into weebot's existing skill infrastructure  
**Architecture:** Hexagonal (Clean Architecture). All changes must respect the dependency rule:  
`Interfaces → Infrastructure → Application → Domain`

---

## Context: what already exists

Before adding anything, understand the full landscape that was discovered during the audit:

| Component | File | Role |
|---|---|---|
| `SkillRegistry` | `weebot/application/skills/skill_registry.py` | Discovers, loads, and indexes SKILL.md files from 3 search paths |
| `FormatDetector` | `weebot/application/skills/format_detector.py` | Detects 5 skill formats; SKILL.md+YAML = `SourceFormat.MANUS` (already works) |
| `SkillConverter` | `weebot/application/skills/skill_converter.py` | Converts MANUS/OPENCLAW/MYMANUS/AgenticSeek to weebot's manifest.json format |
| `SkillPackager` | `weebot/application/skills/skill_packager.py` | Installs, validates, and dynamically loads manifest.json-based skills |
| `ClawHubImporter` | `weebot/application/skills/clawhub_importer.py` | Clones `awesome-openclaw-skills`, generates **stub-only** SKILL.md files |
| `SkillIndexPort` | `weebot/application/ports/skill_index_port.py` | Abstract port: `fetch_index()`, `search()`, `download()` |
| `GitHubSkillIndexAdapter` | `weebot/infrastructure/adapters/skill_index_github.py` | Reads a JSON index from a GitHub raw URL; SHA-256 + tarball download |
| `AgentskillsIndexAdapter` | `weebot/infrastructure/adapters/agentskills_index.py` | Reads an `agentskills.io` JSON API — **different from** awesome-agent-skills |
| `BM25SkillRetriever` | `weebot/application/services/bm25_skill_retriever.py` | BM25 (+ optional Cohere rerank) retrieval; injected into executor at step time |
| `SkillCurator` | `weebot/application/services/skill_curator.py` | Weekly LLM review of stale skills; runs every Sunday at 02:00 |
| `SkillsMixin` | `weebot/application/di/_skills.py` | DI wiring for retriever and curator |
| CLI `skill` group | `cli/commands/skills.py` | `convert`, `convert-all`, `list`, `install`, `update`, `test` |
| `skill update --source` | `cli/commands/skills.py:129` | Dead stub: `agentskills` is accepted but **silently ignored** (also missing from function signature) |
| `skillhub_index_url` | `weebot/config/settings.py:83` | Points to `weebot-community/skillhub/main/index.json` — **this repo does not exist** |
| Existing test coverage | `tests/unit/tools/test_skill_index.py` | Covers `GitHubSkillIndexAdapter`; asserts `"weebot-community" in settings.skillhub_index_url` |
| Existing test coverage | `tests/unit/test_agentskills.py` | Covers `AgentskillsIndexAdapter` (`agentskills_index.py`) — NOT the new adapter |

**Critical discoveries:**
1. `AgentskillsIndexAdapter` already exists and targets a JSON API at `agentskills.io`. The new adapter must be a **separate** file — do not touch `agentskills_index.py`.
2. The `skill update` function signature at line 130 does not accept `source` as a parameter: `def skill_update(skill_name: str | None, check: bool) -> None`. The `--source` option is declared but never passed to the function body. This is a two-character bug plus a branch addition.
3. `SkillCurator._classify()` falls through to `age_days = 999` for any skill with no `evolution_log` and no `versions`. Every newly installed awesome-agent-skills skill will be immediately classified as `archive-candidate` on the next Sunday cron run.
4. `BM25SkillRetriever.refresh()` is synchronous (not async). The docstring and `SkillRetrieverPort` define `refresh()` as `async`, but the BM25 implementation is sync. Any caller must handle this.
5. Do NOT change `skillhub_index_url` in `settings.py` — the existing test `TestSkillHubSettings.test_default_index_url` asserts `"weebot-community" in settings.skillhub_index_url`. Add a new setting instead.

---

## Scope: four targeted changes

```
Fix 1 — SkillCurator: mtime fallback for freshly imported skills
Fix 2 — CLI: wire the dead --source agentskills stub  
Fix 3 — Infrastructure: implement AwesomeAgentSkillsAdapter(SkillIndexPort)
Fix 4 — CLI: call BM25 refresh after skill install/update
```

Each fix is independent and can be implemented and tested in isolation. Recommended order: 1 → 3 → 2 → 4 (3 must precede 2 because 2 imports 3).

---

## Fix 1 — SkillCurator: mtime fallback for freshly imported skills

### Problem

`SkillCurator._classify()` (`weebot/application/services/skill_curator.py:91`) reaches `age_days = 999` for any skill with neither `evolution_log` nor a `versions` entry with `accepted_at`. All 14 currently installed awesome-agent-skills skills are in this state. On Sunday at 02:00, the curator will call the LLM for each one and likely recommend `ARCHIVE`, silently corrupting their `evolution_log`.

### Change

**File:** `weebot/application/services/skill_curator.py`  
**Lines to modify:** the `else` branch at lines 111-112

**Before:**
```python
        else:
            age_days = 999
```

**After:**
```python
        else:
            # Last resort: use the SKILL.md file's mtime so freshly
            # installed skills are classified as active, not archive-candidate.
            if skill.source_path:
                try:
                    from pathlib import Path
                    mtime = Path(skill.source_path).stat().st_mtime
                    age_days = (now - datetime.fromtimestamp(mtime, tz=timezone.utc)).days
                except OSError:
                    age_days = 999
            else:
                age_days = 999
```

**Why `source_path`:** `Skill.source_path` is set by `SkillRegistry._parse_skill()` to the absolute path of the SKILL.md file (line 97 in `skill_registry.py`). It is always populated for file-system-loaded skills.

**Why not add a field to `SkillMetadata`:** Adding `imported_at: Optional[datetime]` would be cleaner long-term but requires a migration for all existing persisted `Skill` objects. The mtime approach is zero-migration and correct for the immediate use case. The field can be added as a follow-up.

### Tests to write

**File:** `tests/unit/tools/test_skill_curator_classify.py` (new)

```python
class TestSkillCuratorClassifyMtime:
    def test_no_history_with_source_path_recent_is_active(self, tmp_path):
        # Create a SKILL.md written just now
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\nname: new-skill\ndescription: x\n---\n")
        skill = Skill(name="new-skill", source_path=str(skill_md))
        now = datetime.now(timezone.utc)
        result = SkillCurator._classify(skill, now)
        assert result == "active"

    def test_no_history_no_source_path_is_archive_candidate(self):
        skill = Skill(name="orphan-skill")
        now = datetime.now(timezone.utc)
        result = SkillCurator._classify(skill, now)
        assert result == "archive-candidate"

    def test_no_history_with_old_file_is_stale(self, tmp_path):
        import os, time
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\nname: old-skill\ndescription: x\n---\n")
        # Backdate mtime by 60 days
        old_mtime = time.time() - (60 * 86400)
        os.utime(skill_md, (old_mtime, old_mtime))
        skill = Skill(name="old-skill", source_path=str(skill_md))
        now = datetime.now(timezone.utc)
        result = SkillCurator._classify(skill, now)
        assert result == "stale"
```

---

## Fix 2 — CLI: wire the dead `--source agentskills` stub

### Problem

`cli/commands/skills.py:126-162`. Two bugs:
1. `source` is not in the function signature (line 130): `def skill_update(skill_name: str | None, check: bool) -> None`
2. Inside `_run()`, `GitHubSkillIndexAdapter()` is always used regardless of `source`

### Change

**File:** `cli/commands/skills.py`

**Step 1** — Add `source` to the function signature:

**Before (line 130):**
```python
def skill_update(skill_name: str | None, check: bool) -> None:
```

**After:**
```python
def skill_update(skill_name: str | None, check: bool, source: str) -> None:
```

**Step 2** — Replace the hardcoded `GitHubSkillIndexAdapter()` with a factory branch inside `_run()`:

**Before (lines 133-139):**
```python
    async def _run():
        from weebot.application.skills.skill_registry import SkillRegistry
        from weebot.infrastructure.adapters.skill_index_github import GitHubSkillIndexAdapter
        registry = SkillRegistry(); registry.load_all()
        local = {s.name: s for s in registry.list_skills()}
        if not local:
            console.print("[dim]No local skills found.[/dim]"); return
        index = GitHubSkillIndexAdapter()
```

**After:**
```python
    async def _run():
        from weebot.application.skills.skill_registry import SkillRegistry
        registry = SkillRegistry(); registry.load_all()
        local = {s.name: s for s in registry.list_skills()}
        if not local:
            console.print("[dim]No local skills found.[/dim]"); return

        if source == "agentskills":
            from weebot.infrastructure.adapters.awesome_agent_skills_adapter import (
                AwesomeAgentSkillsAdapter,
            )
            index = AwesomeAgentSkillsAdapter()
        else:
            from weebot.infrastructure.adapters.skill_index_github import GitHubSkillIndexAdapter
            index = GitHubSkillIndexAdapter()
```

**Everything else in `_run()` (lines 140-161) is unchanged.** The `AwesomeAgentSkillsAdapter` implements `SkillIndexPort` with the same `fetch_index()`, `search()`, `download()`, and `close()` contract.

**Note on `skill_update --check` with `agentskills`:** The version comparison `remote_map[n].version != str(local[n].current_version)` at line 145 will always show updates from the awesome-agent-skills source because it returns `version="latest"` for all skills. For the initial implementation this is acceptable — the `--check` path will list all indexed skills as "available". A `v2` of the adapter could compute a content hash and use it as the version string.

### Tests to write

**File:** `tests/unit/tools/test_skill_cli.py` (extend the existing class)

```python
class TestSkillUpdateCLISourceRouting:
    def test_agentskills_source_uses_awesome_adapter(self, monkeypatch):
        """--source agentskills instantiates AwesomeAgentSkillsAdapter."""
        from click.testing import CliRunner
        from cli.commands.skills import skill_update

        captured = {}

        class FakeAdapter:
            async def fetch_index(self): return []
            async def close(self): pass

        def fake_awesome(*a, **kw):
            captured["used"] = "agentskills"
            return FakeAdapter()

        monkeypatch.setattr(
            "weebot.infrastructure.adapters.awesome_agent_skills_adapter.AwesomeAgentSkillsAdapter",
            fake_awesome,
        )
        runner = CliRunner()
        runner.invoke(skill_update, ["--source", "agentskills"])
        assert captured.get("used") == "agentskills"

    def test_skillhub_source_uses_github_adapter(self, monkeypatch):
        """Default --source skillhub instantiates GitHubSkillIndexAdapter."""
        # Mirror pattern above for GitHubSkillIndexAdapter
        ...
```

---

## Fix 3 — Infrastructure: implement `AwesomeAgentSkillsAdapter`

### Problem

There is no adapter that reads from `heilcheng/awesome-agent-skills`. The existing `AgentskillsIndexAdapter` (`weebot/infrastructure/adapters/agentskills_index.py`) targets a JSON API at `agentskills.io` — it is unrelated and must NOT be modified.

### Design decisions

**Index source:** The README contains the master skill listing as markdown links. However, parsing markdown is fragile — the structure changes as the community adds sections. A more robust approach: parse links of the form `https://agent-skill.co/<owner>/skills/<slug>` and resolve each to its raw GitHub URL `https://raw.githubusercontent.com/<owner>/skills/main/skills/<slug>/SKILL.md`. This is the canonical pattern used by all official publishers in the index (Anthropic, getsentry, trailofbits, vercel-labs, etc.).

**Download format:** awesome-agent-skills skills are plain SKILL.md files, not tarballs. The `GitHubSkillIndexAdapter.download()` extracts `.tar.gz` archives. The new adapter's `download()` writes a raw SKILL.md directly — no tarball, no SHA-256 needed (GitHub raw content is served over TLS; the content itself is the ground truth).

**Fallback resolution:** Not all publishers host skills at `<owner>/skills/main/skills/<slug>/SKILL.md`. For example, `getsentry/skills` uses `skills/<slug>/SKILL.md` (one level up from the pattern). The adapter must attempt the canonical path and fall back to an alternative pattern before returning `False`.

**New setting:** Add `awesome_agent_skills_index_url` to `WeebotSettings` so the README URL can be overridden in tests without patching. Do NOT change `skillhub_index_url` (existing test asserts its value).

### New setting

**File:** `weebot/config/settings.py`

After line 85 (`skillhub_index_url`), add:

```python
    # awesome-agent-skills — curated GitHub index (heilcheng/awesome-agent-skills)
    awesome_agent_skills_index_url: str = (
        "https://raw.githubusercontent.com/heilcheng/awesome-agent-skills/main/README.md"
    )  # env: AWESOME_AGENT_SKILLS_INDEX_URL
```

### New file

**File:** `weebot/infrastructure/adapters/awesome_agent_skills_adapter.py`

```python
"""AwesomeAgentSkillsAdapter — SkillIndexPort backed by heilcheng/awesome-agent-skills.

Parses the curated README index and fetches SKILL.md files directly from
each publisher's GitHub repository. Implements SkillIndexPort so the CLI
`skill update --source agentskills` flow works without changes to the
update command logic.

Index resolution:
  README link:  https://agent-skill.co/<owner>/skills/<slug>
  Primary URL:  https://raw.githubusercontent.com/<owner>/skills/main/skills/<slug>/SKILL.md
  Fallback URL: https://raw.githubusercontent.com/<owner>/skills/main/<slug>/SKILL.md

Both URLs are tried before returning False from download().
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

import httpx

from weebot.application.ports.skill_index_port import RemoteSkill, SkillIndexPort

logger = logging.getLogger(__name__)

# Matches:  - [display](https://agent-skill.co/<owner>/skills/<slug>) - description
_LINK_RE = re.compile(
    r"-\s*\[([^\]]+)\]\(https://agent-skill\.co/([^/]+)/skills/([^)]+)\)\s*[-–—]\s*(.+?)(?:\n|$)"
)

_HTTP_TIMEOUT = 15.0


class AwesomeAgentSkillsAdapter(SkillIndexPort):
    """SkillIndexPort implementation for the awesome-agent-skills curated index.

    Args:
        index_url: URL of the README.md to parse for skill links.
            Defaults to ``WeebotSettings.awesome_agent_skills_index_url``.
        http_client: Optional pre-configured httpx.AsyncClient.
    """

    def __init__(
        self,
        index_url: Optional[str] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        if index_url is None:
            from weebot.config.settings import WeebotSettings
            index_url = WeebotSettings().awesome_agent_skills_index_url
        self._index_url = index_url
        self._client = http_client or httpx.AsyncClient(timeout=_HTTP_TIMEOUT)
        self._cached: list[RemoteSkill] = []

    # ── SkillIndexPort ───────────────────────────────────────────────

    async def fetch_index(self) -> list[RemoteSkill]:
        """Parse the README and return one RemoteSkill per indexed link.

        Returns an empty list on network failure (never raises).
        """
        try:
            resp = await self._client.get(self._index_url)
            resp.raise_for_status()
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            logger.warning("awesome-agent-skills index fetch failed: %s", exc)
            return []

        skills: list[RemoteSkill] = []
        for m in _LINK_RE.finditer(resp.text):
            owner = m.group(2)
            slug = m.group(3).strip("/")
            description = m.group(4).strip()

            primary_url = (
                f"https://raw.githubusercontent.com/{owner}/skills/main/skills/{slug}/SKILL.md"
            )
            skills.append(RemoteSkill(
                name=slug,
                version="latest",
                description=description,
                author=owner,
                download_url=primary_url,
                homepage=f"https://agent-skill.co/{owner}/skills/{slug}",
                tags=[owner, "awesome-agent-skills"],
            ))

        self._cached = skills
        logger.info(
            "awesome-agent-skills index: %d skills parsed from README", len(skills)
        )
        return list(self._cached)

    async def search(self, query: str) -> list[RemoteSkill]:
        """Case-insensitive search over name, description, and author.

        Fetches the index on first call.
        """
        if not self._cached:
            await self.fetch_index()

        q = query.lower()
        scored: list[tuple[RemoteSkill, int]] = []
        for skill in self._cached:
            score = 0
            if q in skill.name.lower():
                score += 10
            if q in skill.description.lower():
                score += 5
            if q in skill.author.lower():
                score += 3
            if score > 0:
                scored.append((skill, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [s for s, _ in scored]

    async def download(self, skill: RemoteSkill, target_dir: str) -> bool:
        """Download the raw SKILL.md to ``<target_dir>/SKILL.md``.

        Tries the primary URL from ``skill.download_url``, then a fallback
        path pattern before returning False.

        Unlike GitHubSkillIndexAdapter, there is no tarball or SHA-256
        verification — these are plain markdown files served over HTTPS from
        public GitHub repositories.

        Args:
            skill: RemoteSkill with a ``download_url`` pointing to a raw
                   GitHub SKILL.md.
            target_dir: Directory to write ``SKILL.md`` into.

        Returns:
            True on success, False on any failure.
        """
        urls_to_try = [skill.download_url]

        # Derive a fallback URL: <owner>/skills/main/<slug>/SKILL.md
        # (used by some publishers, e.g. getsentry/skills)
        if "/skills/main/skills/" in skill.download_url:
            fallback = skill.download_url.replace(
                "/skills/main/skills/", "/skills/main/"
            )
            urls_to_try.append(fallback)

        for url in urls_to_try:
            content = await self._fetch_raw(url)
            if content is not None:
                return self._write_skill_md(content, target_dir, skill.name)

        logger.warning(
            "Could not download SKILL.md for '%s' — tried: %s",
            skill.name, urls_to_try,
        )
        return False

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    # ── internals ────────────────────────────────────────────────────

    async def _fetch_raw(self, url: str) -> Optional[bytes]:
        """GET *url* and return content, or None on any error."""
        try:
            resp = await self._client.get(url)
            resp.raise_for_status()
            return resp.content
        except (httpx.RequestError, httpx.HTTPStatusError):
            return None

    @staticmethod
    def _write_skill_md(content: bytes, target_dir: str, skill_name: str) -> bool:
        """Write *content* to ``<target_dir>/SKILL.md``.

        Validates that the downloaded content looks like a SKILL.md
        (starts with '---' frontmatter) before writing.
        """
        text = content.decode("utf-8", errors="replace")
        if not text.lstrip().startswith("---"):
            logger.warning(
                "Skipping '%s' — downloaded content has no YAML frontmatter "
                "(not a valid SKILL.md)",
                skill_name,
            )
            return False

        out = Path(target_dir) / "SKILL.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(content)
        logger.info("Installed '%s' → %s", skill_name, out)
        return True


# ── module-level helper (mirrors agentskills_index._parse_agentskills_skill) ──

def _parse_awesome_skill(raw: dict) -> RemoteSkill:
    """Convert a dict (for testing) into a RemoteSkill.

    Mirrors the pattern in skill_index_github._parse_skill so tests can
    construct RemoteSkill objects without importing the full adapter.
    """
    return RemoteSkill(
        name=raw.get("name", ""),
        version=raw.get("version", "latest"),
        description=raw.get("description", ""),
        author=raw.get("author", ""),
        download_url=raw.get("download_url", ""),
        homepage=raw.get("homepage", ""),
        tags=raw.get("tags", ["awesome-agent-skills"]),
        license=raw.get("license", ""),
    )
```

### Tests to write

**File:** `tests/unit/tools/test_awesome_agent_skills_adapter.py` (new)

Cover the same surface as `test_skill_index.py` but for the new adapter:

```
TestAwesomeAgentSkillsAdapter
  test_fetch_index_parses_readme_links           — happy path: 2 links → 2 RemoteSkills
  test_fetch_index_http_error_returns_empty      — 404 → []
  test_fetch_index_network_error_returns_empty   — RequestError → []
  test_fetch_index_no_agent_skill_links          — README with no matching links → []
  test_search_by_name                            — match on skill name
  test_search_by_description                     — match on description substring
  test_search_by_author                          — match on owner/org name
  test_search_case_insensitive                   — uppercase query matches
  test_search_no_match_returns_empty             — []
  test_download_writes_skill_md                  — valid SKILL.md content → file written
  test_download_uses_fallback_url                — primary 404, fallback 200 → True
  test_download_no_frontmatter_returns_false     — content without '---' → False, no file
  test_download_both_urls_fail_returns_false     — both 404 → False

TestParseAwesomeSkill
  test_parse_awesome_skill_fields                — all fields populated correctly
  test_parse_awesome_skill_defaults              — missing fields get sensible defaults

TestAwesomeAgentSkillsSettings
  test_awesome_index_url_in_settings             — WeebotSettings has the field, URL contains "heilcheng"
```

**Sample test (fetch_index happy path):**

```python
SAMPLE_README = """
## Official Skills

- [anthropics/docx](https://agent-skill.co/anthropics/skills/docx) - Create Word documents
- [getsentry/code-review](https://agent-skill.co/getsentry/skills/code-review) - Perform code reviews
"""

@pytest.mark.asyncio
async def test_fetch_index_parses_readme_links():
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = SAMPLE_README
    mock_client.get = AsyncMock(return_value=mock_resp)

    adapter = AwesomeAgentSkillsAdapter(
        index_url="https://example.com/README.md",
        http_client=mock_client,
    )
    skills = await adapter.fetch_index()

    assert len(skills) == 2
    assert skills[0].name == "docx"
    assert skills[0].author == "anthropics"
    assert "anthropics" in skills[0].download_url
    assert skills[1].name == "code-review"
    assert skills[1].author == "getsentry"
    assert skills[1].description == "Perform code reviews"
```

---

## Fix 4 — CLI: call BM25 `refresh()` after `skill install` and `skill update`

### Problem

`BM25SkillRetriever` builds its index at construction time (`__init__` calls `refresh()`). After `skill install` or `skill update` writes new SKILL.md files, the running process's in-memory BM25 index is stale. The newly installed skills are invisible to the executor's Tier 1.2 retrieval until the process restarts.

**Important detail from code review:** `BM25SkillRetriever.refresh()` at line 49 is defined as a **synchronous** method (`def refresh(self) -> None`), not `async`. The `SkillRetrieverPort` abstract port defines it as `async`. The implementation is sync. Calling it requires no `await`.

### Change

**File:** `cli/commands/skills.py`

**After the success block in `skill_install` (after `console.print(f"[green]✓[/green]...")`):**

```python
        # Rebuild the BM25 skill index so newly installed skills are
        # immediately available to the executor's Tier 1.2 retrieval.
        _rebuild_bm25_index(console)
```

**After the download loop in `skill_update` (after `await index.close()`):**

```python
        _rebuild_bm25_index(console)
```

**New module-level helper function (add near the top of the file, below imports):**

```python
def _rebuild_bm25_index(console: Console) -> None:
    """Rebuild the BM25 skill index from the current registry.

    Called after install/update so newly added skills are immediately
    retrievable by the executor without a process restart.

    Non-fatal: any error is logged and swallowed so the CLI command
    still exits 0.
    """
    try:
        from weebot.application.skills.skill_registry import SkillRegistry
        from weebot.application.services.bm25_skill_retriever import BM25SkillRetriever

        registry = SkillRegistry()
        registry.load_all()
        retriever = BM25SkillRetriever(registry)  # refresh() is called in __init__
        n = len(retriever._skill_names)
        console.print(f"  [dim]BM25 index rebuilt ({n} skills)[/dim]")
    except Exception as exc:
        # Non-fatal: retriever will rebuild on next process start
        import logging
        logging.getLogger(__name__).debug("BM25 rebuild skipped: %s", exc)
```

**Why `BM25SkillRetriever(registry)` instead of calling `refresh()` on an existing instance:** The CLI commands do not hold a reference to the long-running `BM25SkillRetriever` instance managed by the DI container. Constructing a new one is the correct pattern for CLI context — it's throwaway, just validates the index builds cleanly.

### Tests to write

**File:** `tests/unit/tools/test_skill_cli.py` (extend existing class)

```python
class TestSkillInstallBM25Rebuild:
    def test_install_triggers_bm25_rebuild(self, tmp_path, monkeypatch):
        """Successful install calls BM25SkillRetriever constructor (index rebuild)."""
        from click.testing import CliRunner
        from cli.commands.skills import skill_install

        # Create a valid SKILL.md in tmp_path
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: test\n---\nHello"
        )

        rebuild_called = []

        class FakeRetriever:
            def __init__(self, registry): rebuild_called.append(True)
            _skill_names = ["my-skill"]

        monkeypatch.setattr(
            "cli.commands.skills.BM25SkillRetriever", FakeRetriever, raising=False
        )

        runner = CliRunner()
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(skill_install, [str(skill_dir)])

        assert result.exit_code == 0
        assert rebuild_called, "BM25SkillRetriever was not constructed after install"
```

---

## Dependency analysis

No new Python packages are required. All four fixes use only:
- `httpx` — already in `requirements.txt` (used by `GitHubSkillIndexAdapter`)
- `re` — stdlib
- `pathlib` — stdlib
- `datetime` — stdlib

---

## File change summary

| File | Change type | Fix |
|---|---|---|
| `weebot/application/services/skill_curator.py` | Edit (~10 lines) | Fix 1 |
| `weebot/config/settings.py` | Edit (3 lines) | Fix 3 |
| `weebot/infrastructure/adapters/awesome_agent_skills_adapter.py` | **New file** (~130 lines) | Fix 3 |
| `cli/commands/skills.py` | Edit (~20 lines) | Fix 2 + Fix 4 |
| `tests/unit/tools/test_skill_curator_classify.py` | **New file** (~40 lines) | Fix 1 tests |
| `tests/unit/tools/test_awesome_agent_skills_adapter.py` | **New file** (~120 lines) | Fix 3 tests |
| `tests/unit/tools/test_skill_cli.py` | Edit (~30 lines) | Fix 2 + Fix 4 tests |

Total: ~350 lines across 7 files (2 edits + 3 new files + 2 test files).

---

## What to NOT change

| What | Why |
|---|---|
| `agentskills_index.py` | Unrelated adapter; changing it would break `test_agentskills.py` |
| `skillhub_index_url` in `settings.py` | `test_skill_index.py:250` asserts `"weebot-community" in settings.skillhub_index_url` |
| `ClawHubImporter` | Stub-file pattern is useful for the openclaw ecosystem; do not generalize it |
| `SkillConverter._convert_manus()` | Correctly converts to manifest.json for SkillPackager; SKILL.md installs bypass it via the `skill install` direct-copy path |
| `SkillRetrieverPort.refresh()` signature | The abstract port declares it `async`; the BM25 impl is sync. Fixing this mismatch is a separate refactor with broader impact |

---

## Verification steps

After all four fixes are implemented:

```bash
# 1. Unit tests — all four fixes covered
pytest tests/unit/tools/test_skill_curator_classify.py -v
pytest tests/unit/tools/test_awesome_agent_skills_adapter.py -v
pytest tests/unit/tools/test_skill_cli.py -v
pytest tests/unit/tools/test_skill_index.py -v     # must still pass (no regression)
pytest tests/unit/test_agentskills.py -v           # must still pass (no regression)

# 2. Integration smoke test — install from awesome-agent-skills source
python -m cli.main skill update --source agentskills --check

# 3. Curator classification — confirm new skills are 'active', not 'archive-candidate'
python -c "
from weebot.application.services.skill_curator import SkillCurator
from weebot.domain.models.skill import Skill
from datetime import datetime, timezone
from pathlib import Path
import tempfile, os

with tempfile.NamedTemporaryFile(suffix='.md', delete=False) as f:
    f.write(b'---\nname: test\ndescription: x\n---\n')
    path = f.name

skill = Skill(name='test', source_path=path)
result = SkillCurator._classify(skill, datetime.now(timezone.utc))
print(f'Classification: {result}')  # expected: active
os.unlink(path)
"

# 4. BM25 index rebuild — confirm skill count increases after install
python -m cli.main skill list | wc -l
```
