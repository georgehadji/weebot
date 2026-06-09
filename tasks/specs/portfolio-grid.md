# Portfolio Grid — Project Cards Spec

## Overview
A three-project-card grid section for Maya Rivera's portfolio. Each card features an SVG placeholder image, project title, category label, and an internal link. The grid is responsive, moving from 3 columns on desktop to a single column on mobile.

---

## Design Tokens

| Token           | Value       | Usage                            |
|-----------------|-------------|----------------------------------|
| `--bg`          | `#1A1A1A`   | Page background                  |
| `--bg-card`     | `#222222`   | Card surface                     |
| `--text`        | `#FFFFFF`   | Card title text                  |
| `--text-muted`  | `#B0B0B0`   | Category label, card description |
| `--accent`      | `#FF6B6B`   | Category label accent, link text |
| `--accent-hov`  | `#FF8585`   | Link hover state                 |
| `--border`      | `#333333`   | Card border                      |
| `--shadow`      | `rgba(0,0,0,0.3)` | Card shadow (default state) |

---

## Section Layout

### Container
- **Width**: max-width `960px`, centered with `auto` margins
- **Padding**: `80px 24px` (top/bottom 80px, left/right 24px)
- **Heading**: Section title "My Work" — white, `clamp(1.75rem, 3vw, 2.5rem)`, centered, margin-bottom `48px`
- **Label above heading**: "PORTFOLIO" — Accent (`#FF6B6B`), uppercase, `0.875rem`, letter-spacing `0.1em`, text-align center, margin-bottom `8px`

### Grid
- **Display**: CSS Grid
- **Desktop (≥768px)**: 3 equal columns, `gap: 24px`
- **Tablet (640–768px)**: 2 columns, `gap: 20px`
- **Mobile (<640px)**: 1 column, `gap: 20px`

---

## Project Cards (3 Cards)

### Card 1 — "Bold & Minimal"
| Property | Value |
|----------|-------|
| Category | Brand Identity |
| Title | Bold & Minimal |
| Description | A rebrand for a creative studio focusing on clean typography and bold color blocks. |
| Link | `#` (placeholder, text: "View Project") |

### Card 2 — "Bloom"
| Property | Value |
|----------|-------|
| Category | Web Design |
| Title | Bloom |
| Description | An e-commerce experience for a sustainable florist, built for speed and delight. |
| Link | `#` (placeholder, text: "View Project") |

### Card 3 — "Nomad"
| Property | Value |
|----------|-------|
| Category | UI/UX |
| Title | Nomad |
| Description | A travel dashboard that simplifies trip planning with an intuitive interface. |
| Link | `#` (placeholder, text: "View Project") |

---

## Card Specs

### Dimensions & Box Model
| Property | Value |
|----------|-------|
| Width | 100% (grid cell fills column) |
| Border-radius | `12px` |
| Overflow | `hidden` (keeps image corners clipped) |
| Background | `--bg-card` |
| Border | `1px solid --border` |
| Box-shadow | `0 4px 12px --shadow` |
| Transition | `transform 0.3s ease, box-shadow 0.3s ease` |

### Card Structure (top-to-bottom)
```
┌─────────────────────────┐
│   SVG Placeholder Image │  ← 100% width, 200px fixed height
│   (project thumbnail)   │
├─────────────────────────┤
│                         │
│  CATEGORY LABEL         │  ← uppercase, 0.75rem, accent color
│                         │
│  Project Title          │  ← 1.25rem, bold, white
│                         │
│  Description text...    │  ← 0.9rem, muted color, line-height 1.5
│                         │
│  View Project →         │  ← inline link, accent color
│                         │
└─────────────────────────┘
```

- **Padding (content area)**: `24px` all around
- **SVG Image** has NO padding — it spans full width

---

## SVG Placeholder Details

### General Specs
- **Format**: Inline `<svg>` element (no external file)
- **Dimensions**: `width="100%"` `height="200"` (fixed height)
- **ViewBox**: `0 0 400 200`
- **Role**: `img` with `<title>` for accessibility

### SVG 1 — Bold & Minimal (Abstract geometric)
- **Background**: `#2A2A2A` (dark gray)
- **Foreground shapes**: 3-4 overlapping rectangles/rectangles in accent coral (`#FF6B6B`) and white (`#FFFFFF`) at varying opacities
- **Style**: Minimalist blocks, 20-30% opacity overlays

### SVG 2 — Bloom (Organic / nature-inspired)
- **Background**: `#1E2A1E` (dark green tint)
- **Foreground shapes**: Soft circles/ellipses in coral (`#FF6B6B`), light green (`#4CAF50`), and white — suggestive of petals/leaves
- **Style**: Rounded organic shapes, soft opacity blends

### SVG 3 — Nomad (Tech / travel-inspired)
- **Background**: `#1A1A2E` (dark blue tint)
- **Foreground shapes**: Simplified map pin icon + dotted path lines in coral (`#FF6B6B`) and light blue/sky tones
- **Style**: Line-based, clean, map-like aesthetic

### SVG Code Template
```html
<svg width="100%" height="200" viewBox="0 0 400 200" role="img" aria-label="[Project Name] preview">
  <title>[Project Name] — [Category]</title>
  <rect width="400" height="200" fill="[bg_color]"/>
  <!-- foreground decorative shapes -->
</svg>
```

---

## Hover Effects

### Card Hover
| Property | Default | Hover |
|----------|---------|-------|
| `transform` | `none` | `translateY(-6px)` |
| `box-shadow` | `0 4px 12px rgba(0,0,0,0.3)` | `0 12px 28px rgba(0,0,0,0.45)` |
| `border-color` | `#333333` | `#FF6B6B` (accent, at 50% opacity) |

Transition: `all 0.3s ease`

### Link Hover
- Default: Accent (`#FF6B6B`), no underline
- Hover: Accent hover (`#FF8585`), underline
- Transition: `color 0.2s ease`

### SVG Image Hover
- On card hover, the SVG's decorative shapes should subtly scale up (1.05x) or shift position for depth
- Implementation: Apply a `transform` via the parent card hover — or keep it simple and use only the card-level effect (preferred for MVP)

---

## Links Styling

### "View Project" Link
| Property | Value |
|----------|-------|
| Display | `inline-flex` |
| Align | `align-items: center` |
| Gap | `6px` between text and arrow |
| Color | `--accent` (`#FF6B6B`) |
| Font | `0.875rem`, weight `600` |
| Text decoration | `none` (default), `underline` (hover) |
| Transition | `color 0.2s ease` |
| Pseudo-element | Optional `→` arrow via `::after` with `content: "→"` |

### Arrow implementation
```css
.project-card .card-link::after {
  content: "→";
  display: inline-block;
  transition: transform 0.2s ease;
}
.project-card .card-link:hover::after {
  transform: translateX(4px);
}
```

---

## Responsive Behavior

| Breakpoint | Grid Columns | Card Image Height | Padding |
|------------|-------------|-------------------|---------|
| ≥768px     | 3 columns   | 200px             | 24px    |
| 640–768px  | 2 columns   | 180px             | 20px    |
| <640px     | 1 column    | 160px             | 20px    |

On mobile (<640px), the section heading remains centered and cards stack full-width with reduced gutters (`16px` on left/right container padding).

---

## Accessibility
- All card links (`<a>`) must have `:focus-visible` outline: `2px solid #FF6B6B`, `outline-offset: 2px`
- SVG placeholders must include `<title>` for screen readers
- Cards should use `<article>` elements for semantic markup
- Category labels should be wrapped in a `<p>` or `<span>` with appropriate contrast (accent on card background passes 4.5:1)

---

## Code Structure Skeleton

```html
<section id="portfolio">
  <div class="container">
    <p class="section-label">PORTFOLIO</p>
    <h2>My Work</h2>
    <div class="grid">
      <article class="project-card">
        <svg><!-- SVG 1 --></svg>
        <div class="card-content">
          <p class="card-category">Brand Identity</p>
          <h3 class="card-title">Bold & Minimal</h3>
          <p class="card-desc">A rebrand for a creative studio...</p>
          <a href="#" class="card-link">View Project</a>
        </div>
      </article>
      <!-- Repeat for Card 2 & Card 3 -->
    </div>
  </div>
</section>
```

---

## File Output
- All CSS for this section lives in the single `<style>` block within `index.html`
- SVG placeholders are inline in the HTML
- No external image assets required