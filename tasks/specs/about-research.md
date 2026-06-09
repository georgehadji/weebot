# Research Section Specification

## Section Overview
This specification defines the Research section (id="research") for the single-page academic website for Dr. Sophia Nikolaou, Professor of Classical Archaeology at Aristotle University of Thessaloniki. The section provides a concise scholarly introduction followed by a visual grid of her primary research areas. It uses a clean, professional, warm Mediterranean academic aesthetic with a limited color palette emphasizing scholarly gravitas and classical heritage.

**Primary Purpose**:
- Deliver an accessible overview of Dr. Nikolaou's research focus immediately after the hero.
- Present four core research areas in an elegant, scannable 4-column card grid.
- Build academic credibility while remaining approachable for students, colleagues, and the public.
- Enable smooth navigation from the hero CTA ("Explore Research").

**Design Principles**:
- Warm, earthy Mediterranean palette evoking ancient Greek heritage (terracotta, cream, deep blue).
- High contrast for readability and accessibility (WCAG AA minimum).
- Minimalist typography with serif accents for academic feel (use system serif for headings where appropriate).
- Card-based layout for research areas to create visual hierarchy and easy scanning.
- Responsive: Desktop-first (4-col → 2-col → 1-col).
- Self-contained: All styles embedded in the final HTML; reuse CSS custom properties defined in header/hero.
- Interaction: Subtle, tasteful hover states that feel scholarly rather than playful.

## Color Palette (Exact CSS Values)
Use these exact hex values (inherited from header-hero.md). Define as CSS custom properties at the root for consistency across the site.

```css
:root {
  --deep-blue: #0a2f5c;      /* Primary: section headings, card titles, borders, nav */
  --cream: #f5f0e6;          /* Backgrounds: section bg, subtle card tints */
  --terracotta: #b85c38;     /* Accent: card left borders, hover states, decorative elements, CTAs */
  --warm-white: #faf8f3;     /* Card backgrounds, light surfaces */
  --dark-text: #2c2c2c;      /* Body text, descriptions */
  --light-text: #f5f0e6;     /* Text on dark (not heavily used here) */
  --card-shadow: rgba(10, 47, 92, 0.08);  /* Soft shadow for cards */
  --card-hover-shadow: rgba(10, 47, 92, 0.15);
}
```

**Usage Notes**:
- Deep blue (#0a2f5c) for all structural headings and card titles.
- Cream (#f5f0e6) as the section background.
- Terracotta (#b85c38) for subtle left accent bars on cards and hover underlines/highlights.
- Warm white (#faf8f3) for card backgrounds to provide gentle contrast against cream.
- Avoid pure black/white; always use palette variants for warmth.
- All text uses --dark-text for body; headings use --deep-blue.

## Component List and Structure

### 1. Section Container & Header
- **id**: `research`
- **Background**: Solid `--cream` (#f5f0e6)
- **Vertical Padding**: 5rem top and bottom (3rem on mobile)
- **Container**: Centered, max-width `1200px`, horizontal padding `2rem`
- **Heading**:
  - Text: "Research"
  - Font: 2.25rem (36px) desktop / 1.875rem (30px) mobile, font-weight: 700, color: #0a2f5c, line-height: 1.1
  - Margin-bottom: 0.5rem
- **Introductory Bio Paragraph** (the "about/bio paragraph"):
  - 2–3 sentences, ~140 words max.
  - Text (example content — finalize with real bio later):
    "Dr. Nikolaou's research centers on the material culture of the ancient Mediterranean, with particular emphasis on how objects, landscapes, and ritual spaces shaped identities across the Aegean from the Bronze Age through the Roman period. Her fieldwork combines traditional excavation with landscape survey and digital documentation methods, exploring questions of connectivity, heritage, and the lived experience of ancient communities. She has directed or co-directed projects in Greece, Cyprus, and the wider eastern Mediterranean, and her work appears in leading journals in classical archaeology and heritage studies."
  - Font: 1.05rem (17px), line-height: 1.7, color: #2c2c2c
  - Max-width: 720px for comfortable reading
  - Margin-bottom: 2.5rem (before grid)

### 2. Research Areas Grid (4-column card layout)
- **Layout**: CSS Grid
  - Desktop (≥1024px): 4 columns, gap: 1.5rem
  - Tablet (≥768px): 2 columns, gap: 1.25rem
  - Mobile (<768px): 1 column, gap: 1rem
- **Each Card** (4 total):
  - Background: #faf8f3 (warm-white)
  - Border: 1px solid #e5e0d6 (subtle warm gray derived from cream)
  - Left accent bar: 4px solid #b85c38 (terracotta) — full height of card
  - Padding: 1.25rem (top/right/bottom), 1.5rem left (to account for accent)
  - Border-radius: 6px
  - Box-shadow: 0 2px 8px var(--card-shadow)
  - Min-height: ~180px (content-driven)
  - **Card Title**:
    - 1.05rem (17px), font-weight: 600, color: #0a2f5c, margin-bottom: 0.5rem
    - No icon required (text-only for scholarly tone); optional small terracotta dot or line if desired
  - **Card Description**:
    - 0.95rem (15px), line-height: 1.6, color: #2c2c2c
    - 3–4 lines max per card
  - **Research Areas** (exact titles + short descriptions):
    1. **Aegean Bronze Age Material Culture**
       "Examines pottery, metalwork, and settlement patterns across the Cyclades and Crete, with focus on trade networks and craft specialization in the second millennium BCE."
    2. **Greek Sanctuaries and Ritual Landscapes**
       "Investigates the architecture, votive practices, and spatial organization of sanctuaries from the Archaic to Hellenistic periods, including recent work at sites in Attica and the Peloponnese."
    3. **Mediterranean Connectivity and Mobility**
       "Studies long-distance exchange, migration, and cultural interaction through ceramic and isotopic analysis, bridging Aegean archaeology with broader eastern Mediterranean contexts."
    4. **Heritage, Identity, and Contemporary Archaeology**
       "Explores how ancient material remains inform modern Greek identity, museum practices, and public engagement, including collaborative projects on site preservation and community archaeology."

### 3. Interactions & Behaviors
- **Card Hover** (desktop and tablet):
  - `transform: translateY(-4px)`
  - `box-shadow: 0 8px 20px var(--card-hover-shadow)`
  - Left accent bar color intensifies or remains; optional subtle border color change to #b85c38
  - Transition: 180ms ease-out (all properties)
  - No scale or color flash — keep elegant and restrained
- **No click expansion** by default (keep simple); cards are purely informational. If future enhancement needed, add `cursor: pointer` and aria-expanded logic.
- **Accessibility**:
  - Cards use `<article>` or semantic `<div role="region">` if needed
  - Sufficient color contrast (all text ≥ 4.5:1)
  - Focus states on any future interactive elements use terracotta outline
- **Scroll behavior**: Section uses `scroll-margin-top: 80px;` to account for fixed header (consistent with header-hero spec).

## HTML Structure Sketch
```html
<section id="research" class="research-section">
  <div class="container">
    <h2 class="section-heading">Research</h2>
    
    <p class="research-intro">
      Dr. Nikolaou's research centers on the material culture of the ancient Mediterranean...
    </p>

    <div class="research-grid">
      <div class="research-card">
        <h3 class="card-title">Aegean Bronze Age Material Culture</h3>
        <p class="card-desc">Examines pottery, metalwork, and settlement patterns across the Cyclades and Crete, with focus on trade networks and craft specialization in the second millennium BCE.</p>
      </div>
      <!-- repeat for 3 more cards -->
    </div>
  </div>
</section>
```

## CSS Classes to Use (exact for consistency)
- `.research-section`
- `.research-section .container`
- `.section-heading`
- `.research-intro`
- `.research-grid`
- `.research-card`
- `.research-card .card-title`
- `.research-card .card-desc`
- `.research-card::before` (for the left terracotta accent bar via pseudo-element)

## Responsive Behavior
- Desktop (≥1024px): 4-column grid, generous padding, larger heading.
- Tablet (768px–1023px): 2-column grid, slightly reduced card padding.
- Mobile (<768px): Single column, full-width cards, heading scales down, intro paragraph remains readable.
- All transitions and shadows remain active on touch devices where hover is emulated.

## Asset Paths
- None required for this section (pure text + CSS).
- If decorative elements are added later (e.g., small inline SVG icons for each research area), place them in `assets/icons/` and reference as `<svg class="research-icon">` or data URIs for self-contained HTML.
- No external images or fonts.

## Implementation Notes
- This section must appear immediately after the Hero (or after an optional "About" section if added in a later spec).
- Reuse button styles and typography scale from header-hero.md where applicable.
- All custom properties should be defined once at `:root` in the final single-file HTML.
- Content is placeholder — replace descriptions with accurate, sourced text from Dr. Nikolaou's CV/publications when available.
- Keep total section height reasonable (avoid excessive whitespace); target ~650–750px on desktop.

## Next Steps / Dependencies
- Depends on header-hero.md for color tokens, typography, and scroll behavior.
- Will be referenced by later specs (e.g., Publications, Teaching) for consistent card styling.
- Image generation or additional assets not needed here.
