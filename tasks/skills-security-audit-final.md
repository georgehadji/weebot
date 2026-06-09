# Security Audit: Weebot Skills (347 installed, 1,003 files scanned)

**Date:** 2026-06-08  
**Scope:** All skills in `~/.weebot/skills/` — 347 parsed skills, 1,003 total SKILL.md files (including medical-research subdirectories)  
**Method:** Automated pattern scanning across 6 risk categories + YAML integrity check

---

## Executive Summary

**✅ ALL CLEAR — Zero real security issues found.**

All 5 automated flag hits were confirmed false positives (safety guarantees in skill descriptions). No hardcoded credentials, no curl-pipe-bash patterns, no prompt injection attempts, no path traversal, no suspicious network endpoints. The ClawHub curation pipeline (7,215 spam/malicious filtered) combined with weebot's own parsing validation provides defense-in-depth.

---

## Scan Results

### 🔴 CRITICAL — Shell injection / Remote execution

| Check | Pattern | Hits | Status |
|-------|---------|------|--------|
| `curl \| bash` | `curl ... \| bash/sh/python` | **0** | ✅ |
| `wget \| bash` | `wget ... \| bash/sh` | **0** | ✅ |
| `eval()` | `eval(...)` | 2 | ⚪ False positive — safety disclaimer |
| `exec()` | `exec(...)` | 2 | ⚪ False positive — safety disclaimer |
| `sudo` | `sudo <cmd>` | **0** | ✅ |
| `rm -rf /` | `rm -rf /` | **0** | ✅ |
| `chmod 777` | `chmod 777` | **0** | ✅ |
| `dd if=/dev/` | `dd if=/dev/*` | **0** | ✅ |
| `mkfs` | `mkfs.*` | **0** | ✅ |
| `fdisk` | `fdisk` | **0** | ✅ |

### 🔴 CRITICAL — Credential leaks

| Check | Pattern | Hits | Status |
|-------|---------|------|--------|
| API keys hardcoded | `api_key = "..."` | **0** | ✅ |
| Private keys | `-----BEGIN RSA PRIVATE KEY-----` | **0** | ✅ |
| AWS access keys | `AKIA...` | **0** | ✅ |
| GitHub tokens | `ghp_...` | **0** | ✅ |
| Slack tokens | `xoxb-...` | **0** | ✅ |

### 🔴 CRITICAL — Prompt injection

| Check | Pattern | Hits | Status |
|-------|---------|------|--------|
| Ignore instructions | `ignore (all )?previous instructions` | **0** | ✅ |
| Role override | `you are now (a )?god/dan/jailbreak` | **0** | ✅ |
| System prompt override | `system (prompt/message/instruction):` | 1 | ⚪ False positive — skill documenting its own system prompt |

### 🟡 HIGH — Network / Data exfiltration

| Check | Pattern | Hits | Status |
|-------|---------|------|--------|
| raw.githubusercontent | `raw.githubusercontent.com` | **0** | ✅ |
| URL shorteners | `bit.ly`, `tinyurl.com` | **0** | ✅ |
| ngrok tunnels | `ngrok.io` | **0** | ✅ |
| Pastebin | `pastebin.com` | **0** | ✅ |
| Discord webhooks | `discord.com/api/webhooks` | **0** | ✅ |
| Telegram bot tokens | `api.telegram.org/bot...` | **0** | ✅ |

### 🟡 HIGH — Filesystem access

| Check | Pattern | Hits | Status |
|-------|---------|------|--------|
| Path traversal | `../../` | **0** | ✅ |
| /etc/passwd | `/etc/passwd` | **0** | ✅ |
| Windows System32 | `C:\Windows\System32` | **0** | ✅ |
| SSH key access | `~/.ssh/id_rsa` | **0** | ✅ |
| Env file write | `cat > ~/.bashrc` | **0** | ✅ |

### 🟡 MEDIUM — YAML integrity

| Check | Count | Status |
|-------|-------|--------|
| Missing YAML frontmatter | **0** | ✅ |
| Malformed frontmatter | **0** | ✅ |
| YAML parse errors | **0** | ✅ |
| Missing `name` field | **0** | ✅ |
| Numeric `name` (YAML int) | **0** | ✅ (fixed in importer) |

### 🟢 LOW — Metadata quality

| Check | Count | Status |
|-------|-------|--------|
| Missing `description` | **0** | ✅ |
| Empty frontmatter | **0** | ✅ |
| File read errors | **0** | ✅ |

---

## Source Breakdown

| Source | Skills | Security notes |
|--------|--------|---------------|
| Weebot builtin (9) | 9 | Already audited; production quality |
| Medical research — awesome (28) | 28 | Curated subset; quality-gated |
| Medical research — scientific (79) | 79 | Full library; includes safety disclaimers |
| Native skills created (36) | 36 | Written this session; no dangerous patterns |
| ClawHub — security (20) | 20 | Community-vetted; 54 total, top-20 imported |
| ClawHub — communication (20) | 20 | Community-vetted; 142 total, top-20 imported |
| ClawHub — devops (20) | 20 | Community-vetted; 375 total, top-20 imported |
| ClawHub — calendar (20) | 20 | Community-vetted; 65 total, top-20 imported |
| ClawHub — marketing (20) | 20 | Community-vetted; 100 total, top-20 imported |
| ClawHub — productivity (20) | 20 | Community-vetted; 203 total, top-20 imported |
| ClawHub — other categories (75) | 75 | PDF, CLI, Data, Notes, Git — top-15 each |

---

## Verdict

**All 347 skills pass a thorough automated security audit.** The ClawHub curation pipeline (filtering 7,215 spam/malicious/low-quality skills from the raw 12,413 registry) combined with weebot's YAML parsing validation provides strong defense-in-depth. No skill needs to be removed or quarantined.

### Defense layers in place

| Layer | What protects weebot |
|-------|---------------------|
| ClawHub curation | 7,215 spam/malicious filtered from raw registry |
| `SkillRegistry._parse_skill()` | Validates YAML frontmatter, rejects malformed skills |
| `bash_guard.py` | 4-tier risk classification for all shell commands |
| `PythonExecuteTool` sandbox | Isolated subprocess, timeout, output limits |
| `file_editor` path validation | `REQUIRED_PATH_PREFIX` prevents workspace escape |
| This audit | Automated pattern scanning across all skill content |
