---
name: git-best-practices
description: Git best practices for app and website development — conventional commits, branching, secrets safety, and meaningful history.
metadata:
  emoji: "📦"
  env: []
  platforms: []
  hermes:
    platforms: []
    config: []
    fallback_for_toolsets: []
    requires_toolsets: ["bash"]
---

# Git Best Practices for Development

When building apps, websites, or any software project, you MUST follow these Git
practices. They ensure the codebase is maintainable, reviewable, and safe.

---

## 1. Repository Initialization

Before writing ANY code for a new project, initialize git:

```bash
git init
```

Then create a `.gitignore` appropriate for the project type:

| Project Type | Key .gitignore entries |
|---|---|
| **Node.js / Next.js** | `node_modules/`, `.next/`, `.env`, `.env.local`, `dist/`, `.turbo/` |
| **Python** | `__pycache__/`, `*.pyc`, `.venv/`, `venv/`, `dist/`, `*.egg-info/` |
| **Static HTML** | `.DS_Store`, `Thumbs.db`, `.vscode/` |
| **General** | `.env*`, `*.log`, `.cache/`, `tmp/`, `.temp/` |

**Never commit:** `.env` files, API keys, tokens, passwords, `node_modules/`, build artifacts.

---

## 2. Commit Convention (Conventional Commits)

Every commit message MUST follow the Conventional Commits format:

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

### Types

| Type | When to use |
|------|------------|
| `feat` | New feature or page (e.g., `feat(hero): add hero section with CTA`) |
| `fix` | Bug fix (e.g., `fix(nav): correct mobile menu toggle`) |
| `style` | CSS, formatting, visual changes (e.g., `style(cards): add hover shadow`) |
| `refactor` | Code restructuring without behavior change |
| `docs` | Documentation, README, comments |
| `test` | Adding or updating tests |
| `chore` | Build config, dependencies, gitignore |
| `perf` | Performance improvement |
| `assets` | Images, fonts, SVGs (e.g., `assets(images): add hero background SVG`) |

### Scope

Use the component or section name: `hero`, `nav`, `footer`, `contact`, `api`, `config`, `styles`.

### Examples

```
feat(hero): add responsive hero section with gradient background
style(cards): add gold hover border and shadow transition
fix(contact): correct form validation for Greek phone numbers
assets(icons): add dental service icon set
chore(git): add .gitignore for Next.js project
refactor(css): extract brand colors into CSS custom properties
```

---

## 3. Commit Frequency and Granularity

Commit after EACH logical unit of work. Do NOT batch unrelated changes.

**Good — one commit per component:**
```
[commit 1] feat(hero): add hero section with CTA buttons
[commit 2] feat(nav): add sticky navigation with mobile menu
[commit 3] feat(services): add services grid with icon cards
[commit 4] style(theme): apply brand colors and typography
[commit 5] feat(contact): add contact form with validation
[commit 6] feat(footer): add footer with clinic info and map link
```

**Bad — one giant commit:**
```
[commit 1] "build website" (ALL files in one commit — unreviewable)
```

---

## 4. Branching Strategy

For multi-feature projects, use feature branches:

```bash
# Start a new feature
git checkout -b feat/hero-section

# Work, commit, then merge back
git checkout main
git merge feat/hero-section
```

| Branch Pattern | Purpose |
|---|---|
| `feat/<name>` | New features or pages |
| `fix/<name>` | Bug fixes |
| `style/<name>` | Visual/design changes |
| `refactor/<name>` | Code restructuring |

For single-page websites or small projects (<5 files), work directly on `main`.

---

## 5. Commit BEFORE Reviewing

Per Will's Anthropic workshop rule about "fresh mind" sub-agents:

**Commit your work BEFORE asking another agent to review it.** This ensures:
- The reviewer sees the exact state you intended
- You can revert if the review suggests major changes
- The git history shows the iteration

```bash
# Producer (you):
git add .
git commit -m "feat(api): implement user authentication endpoints"
# Now ask the reviewer sub-agent to review

# If reviewer finds issues:
# Fix them, then:
git add .
git commit -m "fix(api): address review — add rate limiting and input validation"
```

---

## 6. Secrets Safety (CRITICAL)

**NEVER commit secrets.** Before every commit, mentally check:

- [ ] No API keys (`sk-...`, `OPENROUTER_API_KEY=...`)
- [ ] No passwords
- [ ] No tokens or JWT secrets
- [ ] No `.env` files (add to `.gitignore`)
- [ ] No private URLs or internal IPs

If you accidentally commit a secret:
```bash
git reset HEAD~1          # undo the commit
# Remove the secret from the file
git add .
git commit -m "your message"
```

---

## 7. Commit Messages for Generated Content

When committing AI-generated content (images, copy, SVGs):

```
assets(images): generate hero banner SVG for dental clinic
feat(copy): add Greek and English homepage copy
style(svg): create service icon set in brand colors
```

Always describe WHAT was generated and WHERE it's used — not HOW it was generated.

---

## 8. Pull Request / Final Summary

When the project is complete, provide a summary commit:

```
chore(release): finalize dentist website v1.0

Sections: Hero, Services, About, Contact, Footer
Languages: Greek + English
Images: 5 SVG assets (hero, icons, logo, avatars)
Colors: Navy #0A1628, Gold #C5A46E, Ivory #F8F5F0
```
