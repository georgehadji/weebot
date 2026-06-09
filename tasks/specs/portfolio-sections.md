# Maya Rivera Portfolio — Section Specification

## Overview
Single-file HTML portfolio page for web designer **Maya Rivera**. All styles must be **inline CSS** within a `<style>` block in the HTML head.

## Theme
- **Type:** Dark theme
- **Background:** `#1A1A1A`
- **Surface / Cards:** `#2A2A2A`
- **Primary Text:** `#F5F5F5` (off-white)
- **Secondary Text:** `#B0B0B0` (muted gray)
- **Accent Color:** `#FF6B6B` (coral)
- **Accent Hover:** `#FF8787` (lighter coral)
- **Font Family:** `Inter, system-ui, sans-serif`
- **Max Content Width:** `1200px`
- **Border Radius (cards / buttons):** `8px`

## Sections

### 1. Header
- **HTML:** `<header>` containing `<h1>Maya Rivera</h1>`
- Fixed top navigation bar (`position: fixed`, `z-index: 1000`)
- Background: `#1A1A1A` with `rgba(255,255,255,0.05)` bottom border
- Height: `64px`
- Layout: flex, space-between, align-center, max-width `1200px` centered
- `<h1>` brand name "Maya Rivera" in accent coral (`#FF6B6B`), font-weight `700`, size `1.25rem`
- Right: Navigation links — Work, About, Contact — color `#B0B0B0`, hover `#F5F5F5`

### 2. Hero
- **HTML:** `<section>` containing `<h2>` + `<p>`
- Full viewport height (`min-height: 100vh`), flex center
- Padding-top: `64px` to offset fixed header
- `<h2>` headline: "Hi, I'm Maya Rivera" — `clamp(2.5rem, 5vw, 4rem)`, font-weight `800`, color `#F5F5F5`
- `<p>` subheadline: "Web Designer crafting pixel-perfect digital experiences" — `1.25rem`, color `#B0B0B0`, max-width `560px`
- CTA Button: "View My Work" — background `#FF6B6B`, color `#1A1A1A`, font-weight `700`, padding `14px 32px`, border-radius `8px`, hover `#FF8787`
- Subtle decorative element: a small coral circle or gradient blob behind text at low opacity (`0.15`) for depth

### 3. Skills
- **HTML:** `<div>` containing `<ul>` with 3 `<li>` items
- Section heading: "Skills" — `2rem`, font-weight `700`, color `#F5F5F5`, centered
- `<ul>` with three skill cards in a responsive grid (`grid-template-columns: repeat(auto-fit, minmax(260px, 1fr))`, gap `24px`)
- Each `<li>` card:
  - Background: `#2A2A2A`
  - Border-radius: `8px`
  - Padding: `32px`
  - Border: `1px solid rgba(255,255,255,0.06)`
  - Icon placeholder: 40×40px rounded square in coral with 15% opacity background, icon color `#FF6B6B`
  - Title: `UI/UX Design`, `HTML & CSS`, or `Figma` — `1.25rem`, font-weight `600`, color `#F5F5F5`
  - Description: one short sentence per skill — color `#B0B0B0`, `0.95rem`
    - UI/UX: "Creating intuitive user experiences and seamless interfaces."
    - HTML/CSS: "Building responsive, accessible, and performant websites."
    - Figma: "Designing and prototyping with precision in collaborative workflows."

### 4. Footer
- Background: `#0F0F0F`
- Top border: `1px solid rgba(255,255,255,0.06)`
- Padding: `40px 0`
- Centered layout
- Text: "© 2024 Maya Rivera. All rights reserved." — color `#B0B0B0`, `0.875rem`
- Optional social links row: GitHub, LinkedIn, Dribbble — color `#B0B0B0`, hover `#FF6B6B`

## Technical Requirements
- Single `.html` file
- All CSS inside `<style>` in `<head>`
- No external CSS files
- Responsive: mobile-first with `@media (min-width: 768px)` for grid and nav adjustments
- Smooth scrolling: `html { scroll-behavior: smooth; }`
- No JavaScript required
