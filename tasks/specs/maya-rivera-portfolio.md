# Maya Rivera — Portfolio Page Spec

## Overview
A single-file, dark-themed portfolio landing page for **Maya Rivera**, a web designer. All CSS must be inline (embedded `<style>` block in `<head>`). No external assets, no external fonts, no external images. Everything self-contained in one `.html` file.

---

## Design Tokens

| Token          | Value       | Usage                          |
|----------------|-------------|--------------------------------|
| `--bg`         | `#111`      | Page background                |
| `--bg-card`    | `#1a1a1a`   | Card / section backgrounds     |
| `--text`       | `#e0e0e0`   | Body text color                |
| `--text-light` | `#888`      | Muted / secondary text         |
| `--accent`     | `#FF6B6B`   | Coral accent (headings, CTAs)  |
| `--accent-hov` | `#ff5252`   | Accent hover state             |
| `--border`     | `#333`      | Subtle borders / dividers      |

---

## Page Structure

### 1. Header (`<header>`)
- **Logo / name**: "Maya Rivera" in white, bold, ~1.5rem
- **Navigation**: inline links — *Work*, *About*, *Contact*
  - Links: `#e0e0e0`, hover → `#FF6B6B`
- **Layout**: flexbox, space-between, sticky top, `background: #111`, bottom border `1px solid #333`
- **Padding**: `1rem 2rem`

### 2. Hero Section (`<section id="hero">`)
- **Headline**: "Designs that speak." — large (~3rem), bold, white
- **Subheadline**: "I craft clean, user-centered web experiences." — `#888`, ~1.2rem
- **CTA Button**: "View My Work" — `background: #FF6B6B`, white text, rounded `8px`, padding `0.8rem 2rem`, hover → `#ff5252`
- **Layout**: centered text, min-height `80vh`, flexbox column, centered

### 3. Skills Section (`<section id="skills">`)
- **Section heading**: "What I Do" — white, ~2rem, centered
- **Skill cards** (3 cards in a flex row, gap 1.5rem):
  - **Card 1 — UI/UX Design**: icon placeholder (unicode or emoji), title, description
  - **Card 2 — Front-End Dev**: icon placeholder, title, description
  - **Card 3 — Branding**: icon placeholder, title, description
- **Card styling**: `background: #1a1a1a`, `border: 1px solid #333`, `border-radius: 12px`, padding `2rem`, text centered
- **Card title**: white, bold, ~1.3rem
- **Card description**: `#888`, ~0.95rem

### 4. Footer (`<footer>`)
- **Text**: "© 2025 Maya Rivera. All rights reserved." — `#888`, centered
- **Social links row**: 3 placeholder links (e.g., Dribbble, LinkedIn, GitHub) — `#888`, hover → `#FF6B6B`
- **Layout**: flexbox column, centered, padding `2rem`, top border `1px solid #333`

---

## Responsive Behavior
- **Desktop (≥768px)**: skills cards in a 3-column flex row
- **Mobile (<768px)**: skills cards stack vertically (flex-wrap, flex-basis 100%)
- Header nav stays inline on all sizes (no hamburger needed for this MVP)

---

## Accessibility
- All interactive elements (`<a>`, `<button>`) must have `:focus-visible` outline (2px solid `#FF6B6B`)
- Use semantic HTML5 elements (`<header>`, `<section>`, `<footer>`)
- Minimum contrast ratio 4.5:1 for body text (`#e0e0e0` on `#111`)

---

## File Output
- Single file: `index.html`
- All CSS in `<style>` block inside `<head>`
- No external dependencies
