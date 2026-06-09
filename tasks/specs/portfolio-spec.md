# Portfolio Website — Maya Rivera

> **Project:** Single-File HTML5 Portfolio for Maya Rivera, Freelance Web Designer  
> **Status:** Spec v1.0  
> **Date:** 2026-06-02

---

## 1. Design Tokens (CSS Variables)

All colours, fonts, and spacing are defined as custom properties on `:root`.

```css
:root {
  /* ── Palette ─────────────────────────────── */
  --color-bg-dark:       #1a1a1a;   /* page / section backgrounds */
  --color-bg-card:       #222222;   /* portfolio-card, form card */
  --color-bg-elevated:   #2a2a2a;   /* sticky header, hover states */
  --color-text-primary:  #f0f0f0;   /* body copy */
  --color-text-secondary:#aaaaaa;   /* muted / meta text */
  --color-accent:        #FF6B6B;   /* coral — buttons, links, highlights */
  --color-accent-hover:  #e05555;   /* darker coral for :hover */
  --color-border:        #333333;   /* subtle dividers, input borders */
  --color-white:         #ffffff;   /* headings, hero name */

  /* ── Typography ───────────────────────────── */
  --font-body:    'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --font-heading: 'Inter', sans-serif;
  --font-mono:    'Fira Code', 'Cascadia Code', monospace;

  --fs-base:   1rem;        /* 16 px */
  --fs-small:  0.875rem;    /* 14 px */
  --fs-h1:     3rem;        /* 48 px */
  --fs-h2:     2.25rem;     /* 36 px */
  --fs-h3:     1.5rem;      /* 24 px */

  /* ── Spacing ──────────────────────────────── */
  --space-xs:  0.25rem;     /*  4 px */
  --space-sm:  0.5rem;      /*  8 px */
  --space-md:  1rem;        /* 16 px */
  --space-lg:  1.5rem;      /* 24 px */
  --space-xl:  2rem;        /* 32 px */
  --space-2xl: 3rem;        /* 48 px */
  --space-3xl: 4rem;        /* 64 px */

  /* ── Layout ───────────────────────────────── */
  --max-width: 1200px;
  --header-height: 64px;
  --border-radius: 12px;
  --transition-fast: 200ms ease;
  --transition-normal: 300ms ease;
}
```

---

## 2. Component List & Hierarchy

```
┌─────────────────────────────────────────────┐
│  HEADER (sticky, glassmorphism)             │
│  ├── Logo / site-title ("Maya Rivera")      │
│  ├── Desktop nav links (Home, Work, About,  │
│  │   Contact)                               │
│  └── Mobile hamburger toggle (☰ / ✕)       │
├─────────────────────────────────────────────┤
│  HERO                                       │
│  ├── Headline (h1)                          │
│  ├── Sub-headline / tagline (p)             │
│  ├── CTA button ("View My Work")            │
│  └── Decorative accent shape / gradient     │
├─────────────────────────────────────────────┤
│  PORTFOLIO GRID                             │
│  ├── Section heading (h2)                   │
│  ├── Grid container (CSS Grid)              │
│  │   ├── Card 1 (thumbnail, title, tags)    │
│  │   ├── Card 2                             │
│  │   ├── Card 3                             │
│  │   ├── Card 4                             │
│  │   ├── Card 5                             │
│  │   └── Card 6                             │
│  └── (optional) "Load More" button          │
├─────────────────────────────────────────────┤
│  ABOUT                                      │
│  ├── Section heading (h2)                   │
│  ├── Profile photo / avatar (placeholder)   │
│  ├── Bio paragraph(s)                       │
│  └── Skill tags / badges                    │
├─────────────────────────────────────────────┤
│  CONTACT FORM                               │
│  ├── Section heading (h2)                   │
│  ├── Form card                              │
│  │   ├── Name input                         │
│  │   ├── Email input                        │
│  │   ├── Subject input                      │
│  │   ├── Message textarea                   │
│  │   └── Submit button (coral)              │
│  └── Success / error feedback area          │
├─────────────────────────────────────────────┤
│  FOOTER                                     │
│  ├── Copyright line                         │
│  ├── Social links (GitHub, LinkedIn,        │
│  │   Dribbble, Twitter/X)                   │
│  └── "Back to top" link                     │
└─────────────────────────────────────────────┘
```

---

## 3. Interaction Behaviours

### 3.1 Sticky Header Scroll
- `position: sticky; top: 0; z-index: 1000;`
- On scroll > 50 px, add class `.scrolled` which applies:
  - `background: rgba(26, 26, 26, 0.85);` (glassmorphism)
  - `backdrop-filter: blur(12px);`
  - `box-shadow: 0 2px 20px rgba(0,0,0,0.3);`
- Transition duration: `var(--transition-normal)`

### 3.2 Mobile Menu Toggle
- **Breakpoint:** `<= 768 px` viewport width
- Hamburger icon (☰) visible; desktop nav links hidden
- On click: hamburger → close icon (✕), nav links slide in from top/right
- Menu overlay covers full viewport height minus header
- Clicking a nav link **or** tapping the close icon dismisses the menu
- `aria-expanded` attribute toggled for accessibility

### 3.3 Smooth Scroll Navigation
- All anchor links (`href="#hero"`, `href="#work"`, etc.) use `scroll-behavior: smooth` on `html`
- Optional JS `preventDefault` + `element.scrollIntoView({ behavior: 'smooth' })` for offset-aware scrolling (accounting for sticky header height)

### 3.4 Portfolio Card Hover
- On `:hover` / `:focus-visible`:
  - Card lifts slightly (`transform: translateY(-6px)`)
  - Box shadow intensifies
  - Overlay with project title appears (if using image-only cards)
  - Transition: `var(--transition-normal)`

### 3.5 Form Submission Prevention
- On submit, `event.preventDefault()` is called
- Client-side validation:
  - All fields required (check `value.trim() !== ''`)
  - Email field validated against simple regex (`/^[^\s@]+@[^\s@]+\.[^\s@]+$/`)
- On success: show green success message ("Thanks, Maya will be in touch!")
- On error: show red error message with field-specific hints
- **No actual HTTP POST** — form is purely demonstrative

### 3.6 Intersection Observer Animations (Optional Enhancement)
- Sections fade + slide up when they enter the viewport
- Uses `IntersectionObserver` with `threshold: 0.15`
- Adds class `.visible` which triggers `opacity: 1; transform: translateY(0);`

---

## 4. Viewport Breakpoints

| Breakpoint | Layout Rule | Notes |
|-----------|-------------|-------|
| **≤ 768 px** (mobile) | Single-column layout | Header collapses to hamburger; portfolio grid 1 col; form full-width |
| **> 768 px** (tablet/desktop) | Two-column grid | Portfolio grid switches to 2 columns; header shows inline nav; about section side-by-side |
| **≥ 1024 px** (desktop) | Max-width container centred | Portfolio grid can use 3 columns; more generous whitespace |

### Grid Behaviour Details

```css
/* Mobile-first default: 1 column */
.portfolio-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--space-lg);
}

/* Tablet+ : 2 columns */
@media (min-width: 769px) {
  .portfolio-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

/* Desktop : 3 columns */
@media (min-width: 1024px) {
  .portfolio-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}
```

### Header Responsive Behaviour

| Viewport | Nav Display | Toggle |
|----------|-------------|--------|
| ≤ 768 px | Hidden (off-screen menu) | ☰ hamburger visible |
| > 768 px | Inline flex row | ☰ hidden |

### About Section Responsive

| Viewport | Layout |
|----------|--------|
| ≤ 768 px | Stacked: photo above bio |
| > 768 px | Side-by-side: photo left, bio right (2-column flex) |

---

## 5. Accessibility Requirements

- All interactive elements focusable and have visible `:focus-visible` outlines (coral ring)
- Skip-to-content link as first focusable element
- Semantic HTML: `<header>`, `<main>`, `<section>`, `<nav>`, `<footer>`
- Alt text on all images (even if empty `alt=""` for decorative)
- ARIA labels on icon-only buttons (hamburger toggle, social links)
- Colour contrast ratios meet WCAG AA:
  - `#f0f0f0` on `#1a1a1a` → ratio ~15.4:1 ✅
  - `#FF6B6B` on `#1a1a1a` → ratio ~5.5:1 ✅ (AA for large text)
  - `#FF6B6B` on `#222222` → ratio ~4.8:1 ✅ (AA for large text)

---

## 6. Performance Budget

- **Total file size:** ≤ 50 KB (single HTML file, no external dependencies)
- **External resources:** Zero — no CDN fonts, no icon libraries, no analytics
- **Fonts:** System font stack (Inter fallback via `-apple-system`, etc.)
- **Images:** Inline SVG icons only; portfolio thumbnails use CSS gradient placeholders
- **JavaScript:** Vanilla JS only, no libraries, < 5 KB minified

---

## 7. File Structure

```
portfolio-website/
└── index.html          ← Single self-contained file (all HTML, CSS, JS inline)
```

No build step, no server required. Open directly in browser.

---

## 8. Acceptance Criteria

1. [ ] Dark background (`#1a1a1a`) with coral (`#FF6B6B`) accent throughout
2. [ ] Sticky header with glassmorphism effect on scroll
3. [ ] Mobile hamburger menu that toggles open/close at ≤ 768 px
4. [ ] Portfolio grid: 1 col ≤ 768 px, 2 cols > 768 px, 3 cols ≥ 1024 px
5. [ ] Contact form prevents actual submission, validates fields, shows feedback
6. [ ] Smooth scroll for all anchor links
7. [ ] All sections present: header, hero, portfolio grid, about, contact form, footer
8. [ ] No external dependencies — single file, zero CDN requests
9. [ ] Accessible: semantic HTML, focus styles, ARIA labels, skip-to-content link
10. [ ] File size ≤ 50 KB