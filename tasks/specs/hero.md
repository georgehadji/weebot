# Hero Section Specification

## Overview
Full-width neobrutalist hero section for the AI Portfolio single-page website. Designed to immediately communicate raw power, bold creativity, and AI innovation through aggressive typography, high-contrast yellow/black palette, heavy borders, and 3D floating elements. The hero makes a strong first impression with the statement: "I BUILD AI APPS THAT REDEFINE REALITY".

---

## Project Context
- **Project:** Neobrutalism AI Portfolio Website
- **Persona:** AI builder / developer who creates apps that "redefine reality"
- **Design Language:** Neobrutalism — raw, unpolished, high-impact, inspired by brutalist architecture and 90s web aesthetics
- **Output path:** `tasks/portfolio.html` (hero will be the first `<section>` inside `<main>` or directly in `<body>`)
- **This spec:** `tasks/specs/hero.md`

---

## Business / Personal Identity
- **Name / Handle:** (To be filled — e.g. "Jorgis" or AI persona name)
- **Bold Statement:** "I BUILD AI APPS THAT REDEFINE REALITY"
- **Sub-statement:** "Full-stack AI developer crafting tools that blur the line between code and magic."
- **CTA:** "EXPLORE MY WORK" (links to #projects or scroll)
- **Secondary CTA:** "VIEW GITHUB" (external link)

---

## Layout & Structure

### Container
- Full viewport width (`width: 100%`)
- Minimum height: `100vh` (all breakpoints)
- `position: relative`
- `overflow: hidden` for parallax and floating elements
- 3D perspective container: `perspective: 1000px; transform-style: preserve-3d;`

### Content Stack (Mobile-First, Centered)
1. **Small label / badge** (e.g. "AI × WEB × REALITY")
2. **Main Bold Statement** (H1)
3. **Sub-statement** (p or H2)
4. **CTA Buttons** (primary + secondary)
5. **3D Floating Elements** (decorative AI-themed shapes, positioned absolutely with transform)

### Visual Hierarchy
- H1 is massive, stacked, impactful
- All text uppercase where appropriate for brutalist feel
- Heavy use of negative space + aggressive positioning

---

## Visual Design (Neobrutalism)

### Background
- **Primary Color:** `#FFEB3B` (bright yellow — exact neobrutalism yellow)
- **Secondary / Accents:** `#000000` (pure black)
- **No gradients** — flat, raw color blocks
- **Optional subtle texture:** CSS noise or repeating small pattern (e.g. `background-image: url('data:...')` or simple dots) — keep performance light

### Exact CSS Base (from planned neobrutalism)
```css
.hero {
  background: #FFEB3B;
  border: 8px solid #000;
  box-shadow: 12px 12px 0 #000;
  font-family: Impact, Haettenschweiler, "Arial Black", sans-serif;
  color: #000;
  position: relative;
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 2rem;
  overflow: hidden;
}

.hero-inner {
  perspective: 1000px;
  transform-style: preserve-3d;
  max-width: 1200px;
  width: 100%;
  text-align: center;
  z-index: 2;
}
```

### Typography
| Element | Font Family | Weight | Size (Desktop) | Size (Tablet) | Size (Mobile) | Line Height | Letter Spacing | Text Transform |
|---------|-------------|--------|----------------|---------------|---------------|-------------|----------------|----------------|
| H1 (Bold Statement) | Impact, Haettenschweiler, "Arial Black", sans-serif | 900 (Black) | `6rem` (96px) | `4.5rem` (72px) | `3rem` (48px) | 0.9 | `-0.04em` | uppercase |
| Sub-statement (p) | System UI / Arial Black fallback | 700 (Bold) | `1.75rem` (28px) | `1.5rem` (24px) | `1.25rem` (20px) | 1.2 | `0.02em` | uppercase |
| Badge / Label | Same sans-serif | 700 | `1rem` (16px) | `0.875rem` (14px) | `0.75rem` (12px) | 1 | `0.1em` | uppercase |
| CTA Buttons | Same | 800 | `1.125rem` (18px) | `1rem` (16px) | `1rem` (16px) | 1 | `0.05em` | uppercase |

### Colors
| Element | Color |
|---------|-------|
| Background | `#FFEB3B` |
| All text | `#000000` |
| Borders / Shadows | `#000000` |
| CTA Primary Background | `#000000` |
| CTA Primary Text | `#FFEB3B` |
| CTA Secondary Background | `#FFEB3B` |
| CTA Secondary Text / Border | `#000000` |

---

## Spacing

### Padding
| Breakpoint | Horizontal Padding | Top Padding | Bottom Padding |
|------------|-------------------|-------------|----------------|
| Desktop (≥1024px) | `4rem` (64px) | `8rem` (128px) | `6rem` (96px) |
| Tablet (768–1023px) | `2.5rem` (40px) | `6rem` (96px) | `5rem` (80px) |
| Mobile (<768px) | `1.5rem` (24px) | `5rem` (80px) | `4rem` (64px) |

### Element Gaps
- Between badge and H1: `1.5rem` (24px)
- Between H1 and sub-statement: `1.25rem` (20px)
- Between sub-statement and CTAs: `2.5rem` (40px)
- Between CTA buttons: `1rem` (16px)

---

## 3D & Floating Elements

### Container
- `.hero { perspective: 1000px; }`
- Inner content wrapper uses `transform-style: preserve-3d;`

### Floating Elements (3D AI-themed)
- 4–6 absolute-positioned decorative elements (e.g. cubes, neural nodes, glitch rectangles)
- Use `transform: translateZ(XXpx) rotateX(XXdeg) rotateY(XXdeg);`
- Example classes:
  - `.float-cube` — black square with thick border, different Z depths
  - `.float-node` — small circles or hexagons representing AI
  - `.glitch-bar` — horizontal black bars that offset on scroll
- Parallax: JS-driven on scroll (translateY based on scrollY * factor, different speeds per layer)
- Initial positions: scattered around the hero (top-left, top-right, bottom corners) with `z-index` layering

### Parallax Effect (JS)
- On `window.scroll`, update `transform` of floating elements with different multipliers:
  - Background layer: `scrollY * 0.1`
  - Mid layer: `scrollY * 0.25`
  - Foreground: `scrollY * 0.4`
- Use `requestAnimationFrame` for smooth performance
- Elements should feel like they "float" in 3D space

---

## CTA Button Specification

### Primary CTA ("EXPLORE MY WORK")
- Background: `#000000`
- Text Color: `#FFEB3B`
- Padding: `1rem 2.5rem` (16px 40px)
- Border: `4px solid #000000`
- Border Radius: `0` (sharp, no rounding — brutalist)
- Font: Impact / bold sans, uppercase, 1.125rem
- Box Shadow: `6px 6px 0 #000` (hard offset shadow)

### Secondary CTA ("VIEW GITHUB")
- Background: `#FFEB3B`
- Text Color: `#000000`
- Border: `4px solid #000000`
- Same padding, no radius
- Box Shadow: `6px 6px 0 #000`

### Hover State (both)
- Primary: `background: #FFEB3B; color: #000; transform: translate(-2px, -2px); box-shadow: 8px 8px 0 #000;`
- Secondary: `background: #000; color: #FFEB3B; transform: translate(-2px, -2px); box-shadow: 8px 8px 0 #000;`
- Transition: `all 0.1s ease` (snappy, not smooth)

### Active / Press State
- `transform: translate(2px, 2px);`
- `box-shadow: 2px 2px 0 #000;`
- Hard, immediate response — no easing on active

### Focus State (Accessibility)
- `outline: 4px solid #000;`
- `outline-offset: 4px;`

---

## Responsive Behavior

### Desktop (≥1024px)
- H1 at full 6rem
- Floating elements fully visible and 3D
- CTAs side-by-side

### Tablet (768–1023px)
- H1 scaled to 4.5rem
- Reduce floating element sizes and Z-depths
- CTAs stack or remain inline with smaller padding

### Mobile (<768px)
- H1 at 3rem
- All floating elements hidden or heavily reduced (performance + clutter)
- CTAs full-width stacked (`width: 100%`, max-width 320px, centered)
- Touch targets minimum 48px height
- Parallax disabled or reduced to simple translateY

---

## Accessibility Requirements
- H1 must be the only H1 on the page (or first major heading)
- Color contrast: Black (#000) on Yellow (#FFEB3B) = **19.56:1** (exceeds WCAG AAA)
- All interactive elements (CTAs) must have visible focus indicator
- Semantic HTML: `<section class="hero">`, `<h1>`, `<p>`, `<a>` or `<button>` for CTAs
- `aria-label` on CTAs if icons added later
- Keyboard accessible (tab order logical)
- Reduced motion: respect `prefers-reduced-motion` — disable parallax and heavy transforms

---

## Animation / Enhancement Notes
- **Parallax:** JS scroll-driven (as described)
- **Entrance:** Optional hard cut-in or scale + translate on load (no soft fades — brutalist)
- **Floating elements:** Subtle continuous bob or rotate on idle (CSS animation, low intensity)
- **No soft shadows or blurs** — everything is hard edges, thick borders, flat colors
- **Performance:** Keep floating elements to <6, use `will-change: transform` sparingly

---

## Assets
- **Hero image / illustration:** `assets/hero.png` (if used — can be a 3D-rendered AI element or abstract brutalist graphic; otherwise pure CSS)
- **Fallback:** Pure CSS + text for zero external dependencies in MVP
- **Icon set:** None for hero (text + shapes only)

---

## Implementation Notes for Developer
- Implement hero as first child of `<main>` or top of body
- Use `<section class="hero">` with inner `.hero-inner` for 3D
- Add floating elements as direct children or in a `.hero-decor` wrapper
- Parallax JS can live in a small `<script>` block or separate `js/hero-parallax.js`
- Ensure the hero sets the tone for the rest of the site (subsequent sections should continue neobrutalist language: thick borders, yellow accents, Impact headings, zero-radius buttons)
- After implementation, run visual QA against this spec (exact colors, shadows, typography sizes, 3D transforms)

---

## Files
- **Target HTML:** `tasks/portfolio.html`
- **This spec:** `tasks/specs/hero.md`

