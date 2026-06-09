# Portfolio — Overall Site Specification

> **Project:** Single-File Portfolio Website  
> **Persona:** Maya Rivera — Graphic Designer & Visual Storyteller  
> **File:** `index.html` (single self-contained file)  
> **Status:** Draft spec

---

## 1. Site Structure (Section Order)

| # | Section ID        | Name              | Role                                      |
|---|-------------------|-------------------|-------------------------------------------|
| 1 | `#hero`           | Hero              | Full-viewport intro, tagline, CTA         |
| 2 | `#about`          | About             | Bio, photo, skills badges                 |
| 3 | `#work`           | Work              | Project grid (filterable)                 |
| 4 | `#testimonials`   | Testimonials      | Client quote carousel                     |
| 5 | `#contact`        | Contact           | Form + social links + footer              |

---

## 2. Color Palette

| Token            | Hex       | Usage                                              |
|------------------|-----------|----------------------------------------------------|
| `--color-bg`     | `#0f0f11` | Page background (dark charcoal)                    |
| `--color-surface`| `#1a1a1e` | Card / section background                          |
| `--color-primary`| `#c084fc` | Accent purple — buttons, links, highlights, borders|
| `--color-primary-dim`| `#a855f7` | Hover states, secondary accents                |
| `--color-text`   | `#f1f1f3` | Body text (near-white)                             |
| `--color-muted`  | `#888899` | Secondary text, labels, placeholders               |
| `--color-border` | `#2a2a30` | Subtle dividers, input borders                     |
| `--color-success`| `#34d399` | Form success feedback                              |
| `--color-error`  | `#f87171` | Form error feedback                                |

---

## 3. Typography

| Property              | Value                                      |
|-----------------------|--------------------------------------------|
| Base font             | `'Inter', system-ui, -apple-system, sans-serif` |
| Headings font         | `'Inter', sans-serif` (same family, weight 600–800) |
| Mono (code/badges)    | `'JetBrains Mono', 'Fira Code', monospace` |
| Base size             | `16px` (1rem)                              |
| Scale                 | Perfect Fourth (1.333)                     |
| h1                    | `clamp(2.5rem, 6vw, 4.5rem)` — Hero heading|
| h2                    | `clamp(2rem, 4vw, 3rem)` — Section titles  |
| h3                    | `clamp(1.25rem, 2.5vw, 1.75rem)` — Project titles |
| Body                  | `1rem` / `1.6` line-height                 |
| Small / caption       | `0.875rem`                                 |

---

## 4. Layout & Widths

| Context               | Max-width | Notes                                |
|-----------------------|-----------|--------------------------------------|
| Page wrapper          | `1200px`  | Centered with `margin-inline: auto`  |
| Section inner content | `1100px`  | Padded `1.5rem` on mobile            |
| Project grid          | 3 columns | 2 cols tablet, 1 col mobile          |
| Contact form          | `640px`   | Centered max-width                   |

---

## 5. Viewport Units & Spacing

| Token                  | Value              | Usage                          |
|------------------------|--------------------|--------------------------------|
| `--space-section`      | `clamp(4rem, 10vh, 8rem)` | Vertical gap between sections |
| `--space-block`        | `clamp(2rem, 5vh, 4rem)`  | Internal block padding        |
| `--space-inline`       | `clamp(1rem, 3vw, 2rem)`  | Horizontal padding            |
| `--space-gap`          | `clamp(1rem, 2vw, 1.5rem)`| Grid / flex gap               |
| Hero height            | `100dvh` (dynamic viewport)| Full-screen hero              |
| Sticky header height   | `64px`                     | Fixed nav bar                 |

---

## 6. Media Query Breakpoints

| Name       | Min-width | Target                        |
|------------|-----------|-------------------------------|
| `mobile`   | `0`       | Base styles (single column)   |
| `tablet`   | `640px`   | 2-column grid, larger type    |
| `desktop`  | `1024px`  | 3-column grid, full layout    |
| `wide`     | `1400px`  | Max-width lock, extra spacing |

**Approach:** Mobile-first — all base styles are mobile, then `@media (min-width: ...)` overrides.

---

## 7. Component List (per section)

### 7.1 Hero (`#hero`)
- Full-viewport background with subtle gradient overlay (`--color-bg` → `--color-surface`)
- Large heading: "Maya Rivera" + animated tagline "Graphic Designer & Visual Storyteller"
- Subtitle: short value prop (1 sentence)
- CTA button: "View My Work" (scrolls to `#work`)
- Secondary CTA: "Get in Touch" (scrolls to `#contact`)
- Decorative element: subtle floating shapes / gradient orb (CSS-only, no JS)
- **States:** idle (subtle pulse on CTA), hover (brighten primary), focus (ring)

### 7.2 About (`#about`)
- Two-column layout: photo (left) + bio text (right)
- Photo: circular `256px` image with border (`--color-primary`), lazy-loaded
- Bio: 2–3 paragraphs about Maya's background, philosophy, approach
- Skills badges: row of pill-shaped badges (e.g., "Branding", "Typography", "UI/UX", "Illustration", "Motion")
- **States:** badges have hover scale + color shift

### 7.3 Work (`#work`)
- Filter bar: row of buttons — "All", "Branding", "Web", "Print", "Illustration"
- Active filter has `--color-primary` background
- Project grid: CSS Grid, `repeat(auto-fill, minmax(300px, 1fr))`
- Each project card:
  - Thumbnail image (16:9 aspect ratio, `object-fit: cover`)
  - Overlay on hover: project title + "View Project" link
  - Category tag (top-left corner)
- **States:** default (card with subtle shadow), hover (scale 1.02, overlay appears), focus (ring)
- **Empty state:** "No projects match this category" message when filter yields 0 results

### 7.4 Testimonials (`#testimonials`)
- Horizontal carousel (CSS scroll-snap, no JS library)
- Each card: `320px` min-width, snap-align center
- Card content: quote text (italic), client name + title, optional avatar
- Navigation: dot indicators below carousel
- **States:** active dot highlighted with `--color-primary`

### 7.5 Contact (`#contact`)
- Centered form (`max-width: 640px`)
- Fields: Name (text), Email (email), Subject (text), Message (textarea)
- All fields required with HTML5 validation
- Submit button: "Send Message" with loading spinner state
- **States:**
  - Default: dark input fields with `--color-border`
  - Focus: border shifts to `--color-primary`
  - Valid: subtle green check (optional)
  - Error: red border + error message below field
  - Submitting: button shows spinner, disabled
  - Success: form replaced with thank-you message (green)
  - Error: "Something went wrong. Please try again."
- Below form: social links (Instagram, Dribbble, LinkedIn, GitHub) as icon row
- Footer: "© 2026 Maya Rivera. All rights reserved."

---

## 8. Animations & Transitions

| Element              | Trigger         | Property          | Duration | Easing           |
|----------------------|-----------------|-------------------|----------|------------------|
| Hero heading         | Page load       | `opacity`, `translateY` | 0.8s | `ease-out`       |
| Section entries      | Scroll into view| `opacity`, `translateY` | 0.6s | `ease-out`       |
| Project cards        | Hover           | `transform: scale`| 0.3s     | `ease`           |
| Filter buttons       | Hover / active  | `background`, `color` | 0.2s | `ease`           |
| Form inputs          | Focus           | `border-color`    | 0.2s     | `ease`           |
| Smooth scroll        | Anchor click    | `scroll-behavior` | —        | CSS native       |
| Gradient orb (hero)  | Continuous      | `translate`, `rotate` | 10s  | `linear` (loop)  |

---

## 9. Accessibility Requirements

- All images have `alt` text
- Skip-to-content link (visually hidden, visible on focus)
- Proper heading hierarchy: h1 → h2 → h3
- `aria-label` on icon-only links (social icons)
- `aria-current="page"` on nav (if multi-page, but N/A for single-page)
- Focus-visible ring on all interactive elements (`outline: 2px solid var(--color-primary)`)
- Color contrast: all text/background combos meet WCAG AA (4.5:1)
- Form inputs have associated `<label>` elements
- `prefers-reduced-motion` media query disables animations

---

## 10. Performance Budget

| Metric              | Target     |
|---------------------|------------|
| Total file size     | `< 150 KB` (HTML + CSS + inline SVG) |
| Images              | External placeholder service (picsum.photos or similar) |
| JavaScript          | Zero — all CSS, no JS frameworks    |
| Render-blocking     | None (inline critical CSS)          |
| Lighthouse Perf     | ≥ 95 (all categories)               |

---

## 11. File Structure (single file)

```
index.html
├── <head>
│   ├── <meta charset="UTF-8">
│   ├── <meta name="viewport" content="width=device-width, initial-scale=1.0">
│   ├── <title>Maya Rivera — Graphic Designer & Visual Storyteller</title>
│   ├── Google Fonts link (Inter + JetBrains Mono)
│   └── <style> /* All CSS in one block */ </style>
├── <body>
│   ├── <nav> Sticky header with logo + nav links </nav>
│   ├── <section id="hero"> ... </section>
│   ├── <section id="about"> ... </section>
│   ├── <section id="work"> ... </section>
│   ├── <section id="testimonials"> ... </section>
│   ├── <section id="contact"> ... </section>
│   └── <footer> ... </footer>
</html>
```

---

## 12. Dependencies (external)

| Resource              | URL / Source                          | Reason                |
|-----------------------|---------------------------------------|-----------------------|
| Google Fonts (Inter)  | `https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800` | Body + headings |
| Google Fonts (JetBrains Mono) | `https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500` | Badges / code |
| Placeholder images    | `https://picsum.photos/seed/{n}/600/400` | Project thumbnails |
| Avatar placeholder    | `https://picsum.photos/seed/avatar/256` | About photo      |
| Social icons          | Inline SVG (simple paths)             | No external icon lib |

---

## 13. Edge Cases & States

| Component     | State              | Behavior                                      |
|---------------|--------------------|-----------------------------------------------|
| Project grid  | Empty filter       | Show "No projects match this category" message|
| Project grid  | Loading images     | Skeleton shimmer placeholder                  |
| Contact form  | Network error      | Inline error message, form stays intact       |
| Contact form  | Double-submit      | Button disabled after first click             |
| Testimonials  | Single item        | Hide dot nav, center single card              |
| Testimonials  | No items           | Hide entire section (or show placeholder)     |
| Nav           | At top of page     | Transparent background                        |
| Nav           | Scrolled           | Solid `--color-surface` background + shadow   |
| Images        | Broken src         | Fallback gradient placeholder                 |
| Reduced motion| `prefers-reduced-motion` | Disable all animations, transitions = 0s |
| Dark/light    | N/A                | Dark mode only (no toggle)                    |
| Print         | `@media print`     | Remove backgrounds, show text only            |

---

## 14. Build Notes

- No build tools — single `.html` file, open directly in browser
- All CSS in `<style>` tag inside `<head>`
- All SVG icons inline (no external icon libraries)
- Zero JavaScript — all interactivity via CSS (`:target`, `:focus-within`, `scroll-behavior`, checkbox hack for filter)
- Form submission: use `mailto:` or `formspree.io` action URL (configurable)
- Test in: Chrome, Firefox, Safari (latest 2 versions), mobile Safari/Chrome