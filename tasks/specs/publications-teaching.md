# Publications & Teaching Sections Specification

## Section Overview
This specification defines the Publications (id="publications") and Teaching (id="teaching") sections for the single-page academic website for Dr. Sophia Nikolaou, Professor of Classical Archaeology at Aristotle University of Thessaloniki. These sections appear after Research and provide evidence of scholarly impact and pedagogical commitment. The design continues the clean, professional, warm Mediterranean academic aesthetic with the established color palette emphasizing scholarly gravitas and classical heritage.

**Primary Purpose**:
- Publications: Present a curated selection of peer-reviewed work in an accessible, scannable format that highlights key contributions without overwhelming the reader.
- Teaching: Showcase current and representative courses, demonstrating breadth of expertise and commitment to student mentorship.
- Build academic credibility for colleagues, prospective students, and collaborators.
- Enable smooth navigation from hero CTAs ("View Publications") and internal nav.

**Design Principles**:
- Warm, earthy Mediterranean palette evoking ancient Greek heritage (terracotta, cream, deep blue).
- High contrast for readability and accessibility (WCAG AA minimum).
- Minimalist typography with serif accents for academic feel (use system serif for headings where appropriate).
- Card-based or structured list layouts for easy scanning.
- Responsive: Desktop-first (3/2-col grids → 1-col).
- Self-contained: All styles embedded in the final HTML; reuse CSS custom properties defined in header-hero.md and about-research.md.
- Interaction: Subtle, tasteful hover states that feel scholarly rather than playful. No heavy modals unless specified.
- Content is placeholder — replace with accurate, sourced entries from Dr. Nikolaou's CV when available.

## Color Palette (Exact CSS Values)
Use these exact hex values (inherited from header-hero.md and about-research.md). Define as CSS custom properties at the root for consistency across the site.

```css
:root {
  --deep-blue: #0a2f5c;      /* Primary: section headings, card titles, borders, nav */
  --cream: #f5f0e6;          /* Backgrounds: section bg, subtle card tints */
  --terracotta: #b85c38;     /* Accent: year badges, card left borders, hover states, decorative elements, CTAs */
  --warm-white: #faf8f3;     /* Card backgrounds, light surfaces */
  --dark-text: #2c2c2c;      /* Body text, descriptions */
  --light-text: #f5f0e6;     /* Text on dark (not heavily used here) */
  --card-shadow: rgba(10, 47, 92, 0.08);  /* Soft shadow for cards */
  --card-hover-shadow: rgba(10, 47, 92, 0.15);
  --border-subtle: #e5e0d6;  /* Subtle warm gray for borders */
}
```

**Usage Notes**:
- Deep blue (#0a2f5c) for all structural headings, titles, and primary text.
- Cream (#f5f0e6) as the section background.
- Terracotta (#b85c38) for year badges, left accent bars, hover underlines, and CTAs.
- Warm white (#faf8f3) for card/list item backgrounds.
- All text uses --dark-text for body; headings use --deep-blue.
- Avoid pure black/white; always use palette variants for warmth.

## Component List and Structure

### 1. Publications Section (id="publications")
- **Background**: Solid `--cream` (#f5f0e6)
- **Vertical Padding**: 5rem top and bottom (3rem on mobile)
- **Container**: Centered, max-width `1200px`, horizontal padding `2rem`
- **Heading**:
  - Text: "Selected Publications"
  - Font: 2.25rem (36px) desktop / 1.875rem (30px) mobile, font-weight: 700, color: #0a2f5c, line-height: 1.1
  - Margin-bottom: 0.5rem
- **Introductory Paragraph**:
  - 1–2 sentences, ~80 words max.
  - Text (placeholder):
    "A selection of peer-reviewed articles, book chapters, and monographs reflecting Dr. Nikolaou's contributions to Aegean and Mediterranean archaeology. Full CV and complete bibliography available upon request."
  - Font: 1.05rem (17px), line-height: 1.7, color: #2c2c2c
  - Max-width: 720px
  - Margin-bottom: 2rem

#### Publications List (Card or Structured List)
- **Layout**: CSS Grid or flex column of publication entries.
  - Desktop (≥1024px): 2-column grid, gap: 1.5rem
  - Tablet (≥768px): 1-column (or 2 if space allows)
  - Mobile: Single column, stacked
- **Each Publication Entry** (use `<article class="pub-item">` or similar):
  - Background: #faf8f3 (warm-white)
  - Border: 1px solid #e5e0d6
  - Left accent bar: 4px solid #b85c38 (terracotta) — full height
  - Padding: 1.25rem (top/right/bottom), 1.5rem left
  - Border-radius: 6px
  - Box-shadow: 0 2px 8px var(--card-shadow)
  - **Year Badge** (top-right or integrated):
    - Small pill: background #b85c38, color #faf8f3, font-size 0.75rem, font-weight 600, padding 0.15rem 0.5rem, border-radius 9999px
    - Text: e.g. "2023"
  - **Title**:
    - 1.05rem (17px), font-weight: 600, color: #0a2f5c, margin-bottom: 0.35rem, line-height: 1.3
  - **Authors** (short form):
    - 0.85rem, font-style: italic, color: #2c2c2c, margin-bottom: 0.25rem
  - **Venue & Details**:
    - 0.9rem, color: #2c2c2c
    - Format example: "Journal of Mediterranean Archaeology 36(2), 145–172"
  - **Optional Link**:
    - Small "View PDF" or "DOI" link in terracotta, font-size 0.8rem (opens in new tab or placeholder)
- **Selected Publications** (exact placeholder entries — 5–6 total):
  1. **Ceramic Exchange Networks in the Early Cyclades**
     Authors: S. Nikolaou, M. Papadopoulos
     Venue: Journal of Mediterranean Archaeology, 36(2), 2023
  2. **Sanctuary Architecture and Ritual Practice at Brauron**
     Authors: S. Nikolaou
     Venue: Hesperia: The Journal of the American School of Classical Studies at Athens, 90(4), 2021
  3. **Mobility and Material Culture in the Late Bronze Age Aegean**
     Authors: S. Nikolaou, A. Vassiliou, K. Dimitriadis
     Venue: In: Connectivity in the Ancient Mediterranean (edited volume), Oxford University Press, 2020
  4. **Landscape Survey and Heritage Management in Attica**
     Authors: S. Nikolaou et al.
     Venue: Archaeological Reports, 65, 2019
  5. **Votive Practices and Identity Formation in Greek Sanctuaries**
     Authors: S. Nikolaou
     Venue: American Journal of Archaeology, 122(3), 2018

### 2. Teaching Section (id="teaching")
- **Background**: Solid `--cream` (#f5f0e6)
- **Vertical Padding**: 5rem top and bottom (3rem on mobile)
- **Container**: Centered, max-width `1200px`, horizontal padding `2rem`
- **Heading**:
  - Text: "Teaching & Mentorship"
  - Font: 2.25rem (36px) desktop / 1.875rem (30px) mobile, font-weight: 700, color: #0a2f5c
  - Margin-bottom: 0.5rem
- **Introductory Paragraph**:
  - 1–2 sentences.
  - Text (placeholder):
    "Dr. Nikolaou teaches undergraduate and graduate courses in classical archaeology, Aegean prehistory, and heritage studies. She supervises MA and PhD students and regularly offers field schools and seminars."
  - Font: 1.05rem (17px), line-height: 1.7, color: #2c2c2c
  - Max-width: 720px
  - Margin-bottom: 2rem

#### Teaching Courses Grid
- **Layout**: CSS Grid
  - Desktop (≥1024px): 3 columns, gap: 1.5rem
  - Tablet (≥768px): 2 columns, gap: 1.25rem
  - Mobile (<768px): 1 column, gap: 1rem
- **Each Course Card** (4–6 total):
  - Background: #faf8f3 (warm-white)
  - Border: 1px solid #e5e0d6
  - Left accent bar: 4px solid #b85c38 (terracotta)
  - Padding: 1.25rem top/right/bottom, 1.5rem left
  - Border-radius: 6px
  - Box-shadow: 0 2px 8px var(--card-shadow)
  - **Course Code + Title**:
    - 1.0rem (16px), font-weight: 600, color: #0a2f5c, margin-bottom: 0.35rem
    - Format: "CLAR 312 — Aegean Prehistory"
  - **Level / Semester** (small tag):
    - 0.75rem, color: #b85c38, font-weight: 500 (e.g., "Undergraduate • Spring")
  - **Description**:
    - 0.9rem (14.5px), line-height: 1.55, color: #2c2c2c
    - 3–4 lines max
  - **Courses** (placeholder):
    1. **CLAR 210 — Introduction to Classical Archaeology**
       "Survey of material culture from the Bronze Age to the Roman period with emphasis on Greece and the Aegean. Includes museum visits and object handling sessions."
       Level: Undergraduate, Fall
    2. **CLAR 312 — Aegean Prehistory**
       "Advanced seminar on Cycladic, Minoan, and Mycenaean societies. Focus on recent fieldwork, ceramic analysis, and theoretical approaches to connectivity."
       Level: Undergraduate/Graduate, Spring
    3. **CLAR 450 — Greek Sanctuaries and Ritual Landscapes**
       "Explores the architecture, votives, and spatial organization of sanctuaries. Students conduct independent research projects using primary sources."
       Level: Graduate seminar, Fall (alternate years)
    4. **CLAR 520 — Heritage, Identity, and Contemporary Archaeology**
       "Graduate course examining the role of archaeology in modern Greek society, museum ethics, and community engagement. Includes fieldwork component."
       Level: Graduate, Spring
    5. **Field School: Excavations in Attica**
       "Annual summer field school combining excavation, survey, and post-excavation analysis at active sites in Attica."
       Level: Undergraduate/Graduate, Summer

### 3. Interactions & Behaviors
- **Card / Item Hover** (desktop and tablet):
  - `transform: translateY(-3px)`
  - `box-shadow: 0 8px 20px var(--card-hover-shadow)`
  - Left accent bar intensifies slightly (or remains); subtle border color shift toward #b85c38
  - Transition: 160ms ease-out (all properties)
  - Keep restrained and elegant.
- **Year Badges** (Publications):
  - Hover: slight scale (1.05) or color intensification.
- **Links**:
  - "View PDF" / "DOI" links: color #b85c38, underline on hover, no full card click (to avoid confusion).
- **Accessibility**:
  - Use semantic `<section>`, `<article>`, `<h2>`, `<h3>`.
  - Sufficient color contrast (all text ≥ 4.5:1).
  - Focus states use terracotta outline (2px solid #b85c38, offset 2px).
  - ARIA labels where appropriate (e.g., for external links).
- **Scroll behavior**: Sections use `scroll-margin-top: 80px;` to account for fixed header (consistent with prior specs).
- **No heavy interactions** by default. If "expand for full citation" is desired later, use `<details>` or simple JS toggle (keep minimal for single-file).

## HTML Structure Sketch
```html
<!-- Publications -->
<section id="publications" class="publications-section">
  <div class="container">
    <h2 class="section-heading">Selected Publications</h2>
    <p class="section-intro">A selection of peer-reviewed articles...</p>
    
    <div class="publications-grid">
      <article class="pub-item">
        <span class="pub-year">2023</span>
        <h3 class="pub-title">Ceramic Exchange Networks in the Early Cyclades</h3>
        <p class="pub-authors">S. Nikolaou, M. Papadopoulos</p>
        <p class="pub-venue">Journal of Mediterranean Archaeology, 36(2), 145–172</p>
        <a href="#" class="pub-link" target="_blank" rel="noopener">View PDF</a>
      </article>
      <!-- repeat for other publications -->
    </div>
  </div>
</section>

<!-- Teaching -->
<section id="teaching" class="teaching-section">
  <div class="container">
    <h2 class="section-heading">Teaching & Mentorship</h2>
    <p class="section-intro">Dr. Nikolaou teaches...</p>
    
    <div class="teaching-grid">
      <article class="course-card">
        <h3 class="course-title">CLAR 210 — Introduction to Classical Archaeology</h3>
        <span class="course-level">Undergraduate • Fall</span>
        <p class="course-desc">Survey of material culture...</p>
      </article>
      <!-- repeat for other courses -->
    </div>
  </div>
</section>
```

## CSS Classes to Use (exact for consistency)
- `.publications-section`, `.teaching-section`
- `.publications-section .container`, `.teaching-section .container`
- `.section-heading` (shared with research)
- `.section-intro`
- `.publications-grid`, `.pub-item`, `.pub-year`, `.pub-title`, `.pub-authors`, `.pub-venue`, `.pub-link`
- `.teaching-grid`, `.course-card`, `.course-title`, `.course-level`, `.course-desc`
- `.pub-item::before`, `.course-card::before` (for left terracotta accent via pseudo-element)

## Responsive Behavior
- Desktop (≥1024px): 2-col pubs grid, 3-col teaching grid, generous padding.
- Tablet (768px–1023px): 1-col pubs, 2-col teaching, slightly reduced padding.
- Mobile (<768px): Single column for both, full-width items, heading scales down, intro remains readable. Year badges stack nicely.
- All transitions and shadows remain active on touch devices.

## Asset Paths
- None required (pure text + CSS).
- If future enhancement adds small icons (e.g., book icon for pubs, mortarboard for teaching), place in `assets/icons/` and reference inline or as data URIs.
- No external images or fonts.

## Implementation Notes
- These sections must appear after Research (and before Contact if present).
- Reuse button styles, typography scale, and CSS custom properties from header-hero.md and about-research.md.
- All custom properties defined once at `:root` in the final single-file HTML.
- Content is placeholder — replace with accurate citations and course descriptions from Dr. Nikolaou's official materials.
- Keep total height reasonable; target combined ~900–1100px on desktop.
- For publications, consider adding a "Full CV (PDF)" button at the bottom of the publications section (use secondary button style from hero).
- Publications list can be switched to a more traditional bulleted chronological list in implementation if preferred for density, but card style matches the Research aesthetic.

## Next Steps / Dependencies
- Depends on header-hero.md and about-research.md for color tokens, typography, scroll behavior, and card styling patterns.
- Will be referenced by later specs (e.g., Contact, Footer) for consistent section structure.
- Image generation not needed here.
- When implementing the full site, ensure nav links point to `#publications` and `#teaching`.
- Future: Consider adding a "Download CV" CTA that links to a hosted PDF.