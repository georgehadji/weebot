# Maya Rivera Portfolio Website — Technical Spec

## Overview
Single-file HTML portfolio website for Maya Rivera, a web designer. Dark theme with coral accent, inline CSS only, minimal and clean layout.

---

## Theme

| Token | Value | Usage |
|-------|-------|-------|
| Background | `#1A1A1A` | Page background |
| Surface | `#222222` | Cards, nav backdrop |
| Primary Text | `#FFFFFF` | Headings, body text |
| Secondary Text | `#B0B0B0` | Captions, meta text |
| Accent | `#FF6B6B` | Links, buttons, highlights |
| Accent Hover | `#FF8585` | Button/link hover state |
| Border | `#333333` | Subtle dividers |
| Nav Backdrop | `rgba(26,26,26,0.9)` | Sticky nav background |

---

## Typography

- **Headings**: Inter or system sans-serif, 700 weight
  - H1 (Hero): `clamp(2.5rem, 6vw, 4rem)`, line-height 1.1
  - H2 (Section): `clamp(1.75rem, 3vw, 2.5rem)`, line-height 1.2
  - H3 (Card): `1.25rem`, line-height 1.3
- **Body**: System sans-serif, 400 weight, `1rem` (16px), line-height 1.6
- **Accent / Label**: 500 weight, `0.875rem`, uppercase, letter-spacing 0.05em, color Secondary Text

---

## Responsive Breakpoints

| Name | Width | Behavior |
|------|-------|----------|
| Mobile | < 640px | Single column, stacked layout |
| Desktop | ≥ 640px | Full layout, max-width 960px centered |

---

## Layout Sections

### 1. Header
- **Position**: Static (top of page), full width
- **Height**: Auto, padding `24px 0`
- **Background**: Background color
- **Content**:
  - Left: Logo text "Maya Rivera" in Primary Text, font-weight 700, `1.25rem`
  - Right: Nav links — Work, About, Contact — plain text links in Secondary Text, hover Accent
- **Layout**: Flex row, space-between, align-center
- **Mobile**: Same layout, links may wrap if needed

### 2. Hero
- **Height**: `80vh` (min-height 400px)
- **Layout**: Centered flex column, text-align center
- **Content**:
  - Label: "WEB DESIGNER" — Accent color, uppercase, letter-spacing 0.1em, `0.875rem`
  - H1: "Maya Rivera"
  - Subtitle: "I design clean, modern websites that help businesses grow."
  - CTA Button: "View My Work" — Accent background, white text, rounded `6px`, padding `12px 28px`, hover brightness shift
- **Background**: Pure Background color

### 3. Skills (3 Items)
- **Section Padding**: `80px 0`
- **Layout**: 3-column grid on desktop (gap `24px`), single column on mobile
- **Content**:
  - Section label: "SKILLS" — Accent color, uppercase, centered, `0.875rem`, margin-bottom `40px`
  - 3 skill cards:
    1. **UI/UX** — "Creating intuitive user interfaces and seamless experiences."
    2. **HTML/CSS** — "Building responsive, performant websites with clean code."
    3. **Figma** — "Designing and prototyping with modern collaborative tools."
- **Card Style**:
  - Surface background, rounded `12px`, padding `32px`
  - Icon placeholder: 48×48px circle, Accent background at 20% opacity, centered icon (emoji or simple shape)
  - H3: Primary Text, margin-top `20px`
  - Description: Secondary Text, `0.95rem`

### 4. Footer
- **Layout**: Full width, centered text
- **Padding**: `40px 0`
- **Border-top**: 1px solid Border
- **Content**:
  - Contact: "hello@mayarivera.design" — link in Accent color
  - "© 2026 Maya Rivera. All rights reserved."
- **Text**: Secondary Text, `0.875rem`

---

## Interactions & Behaviors

| Interaction | Implementation |
|-------------|----------------|
| Button hover | `transition: filter 0.2s ease`, hover `brightness(1.1)` |
| Link hover | `transition: color 0.2s ease` |
| Card hover | Optional `transition: transform 0.3s ease`, hover `translateY(-4px)` |

---

## File Output

- **Single HTML file**: `index.html`
- **Inline CSS only** — all styles in `<style>` tag within `<head>`
- **No external dependencies** — pure HTML/CSS
- **No JavaScript required** — static page
