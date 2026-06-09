# Header and Hero Section Specification

## Section Overview
This specification defines the top-level header and hero section for the single-page academic website for Dr. Sophia Nikolaou, Professor of Classical Archaeology at Aristotle University of Thessaloniki. The design uses a clean, professional, warm Mediterranean academic aesthetic with a limited color palette emphasizing scholarly gravitas and classical heritage.

**Primary Purpose**: 
- Establish institutional credibility and personal authority immediately.
- Provide clear navigation to all major sections of the single-page site.
- Deliver a compelling visual introduction with a professional portrait and concise bio hook.
- Enable smooth, accessible navigation without page reloads.

**Design Principles**:
- Warm, earthy Mediterranean palette evoking ancient Greek heritage (terracotta, cream, deep blue).
- High contrast for readability and accessibility (WCAG AA minimum).
- Minimalist typography with serif accents for academic feel.
- Responsive: Desktop-first with mobile hamburger menu.
- Self-contained: All styles embedded in the final HTML.

## Color Palette (Exact CSS Values)
Use these exact hex values throughout the section (and site-wide where applicable). Define as CSS custom properties at the root for consistency.

```css
:root {
  --deep-blue: #0a2f5c;      /* Primary: headers, nav links, accents, footer */
  --cream: #f5f0e6;          /* Backgrounds: body, cards, hero overlay */
  --terracotta: #b85c38;     /* Accent: buttons, highlights, hover states, decorative elements */
  --warm-white: #faf8f3;     /* Subtle text/background variant */
  --dark-text: #2c2c2c;      /* Body text */
  --light-text: #f5f0e6;     /* Text on dark backgrounds */
}
```

**Usage Notes**:
- Deep blue (#0a2f5c) for all structural text and borders.
- Cream (#f5f0e6) as primary background for hero and sections.
- Terracotta (#b85c38) for CTAs, active states, and subtle decorative lines (e.g., underlines, icons).
- Avoid pure black/white; always use palette variants for warmth.

## Component List and Structure

### 1. Header (Fixed / Sticky Navigation)
- **Location**: Top of page, fixed on scroll (position: sticky; top: 0; z-index: 100).
- **Height**: 72px (desktop), 64px (mobile).
- **Background**: Solid #0a2f5c with subtle bottom border in #b85c38 (1px).
- **Layout**: Flexbox, space-between.
  - Left: University branding (text or small logo).
  - Center/Right: Professor name + horizontal navigation.
  - Mobile: Hamburger icon (three lines in #f5f0e6) that toggles a full-screen or dropdown menu.

**Sub-components**:
- **University Name**: "Aristotle University of Thessaloniki" (small, uppercase, letter-spacing: 1.5px, font-weight: 400, color: #f5f0e6).
- **Professor Name (Nav Brand)**: "Dr. Sophia Nikolaou" (larger, serif or elegant sans, color: #f5f0e6, links back to top/hero).
- **Navigation Links** (desktop horizontal):
  - About
  - Research
  - Publications
  - Teaching
  - Contact
  - Each: 14-15px, font-weight: 500, color: #f5f0e6, hover: #b85c38 with underline transition.
- **Mobile Menu**: Slide-in or overlay with same links + close button. Use JS for toggle (or pure CSS checkbox hack for self-contained).

**HTML Structure Sketch**:
```html
<header class="site-header">
  <div class="header-inner">
    <div class="university-brand">Aristotle University of Thessaloniki</div>
    <a href="#hero" class="professor-brand">Dr. Sophia Nikolaou</a>
    <nav class="main-nav">
      <ul>
        <li><a href="#about">About</a></li>
        <!-- ... other links -->
      </ul>
    </nav>
    <button class="mobile-menu-toggle" aria-label="Toggle menu">☰</button>
  </div>
</header>
```

**CSS Classes to Use** (exact for consistency):
- `.site-header`
- `.header-inner`
- `.university-brand`
- `.professor-brand`
- `.main-nav`
- `.main-nav ul`, `.main-nav li`, `.main-nav a`
- `.mobile-menu-toggle` (hidden on desktop via media query)

### 2. Hero Section
- **Location**: Immediately below header, full viewport height minus header (min-height: 100vh or 620px).
- **Background**: Cream (#f5f0e6) with subtle texture or gradient overlay if needed (e.g., linear-gradient to bottom).
- **Layout**: Two-column flex (desktop): 
  - Left (55%): Portrait image.
  - Right (45%): Introductory text block (name, title, short bio, CTA buttons).
- **Mobile**: Stacked vertically, portrait above text, centered.

**Sub-components**:
- **Portrait Image**:
  - Asset path: `assets/portrait.png` (or `/assets/portrait.png` relative to HTML root).
  - Dimensions: 420x520px (desktop), scaled responsively (max-width: 100%).
  - Styling: Subtle border (2px solid #0a2f5c), soft drop shadow, rounded corners (4px) or slight classical frame effect.
  - Alt text: "Portrait of Dr. Sophia Nikolaou, Professor of Classical Archaeology".
  - Note: This image will be generated in a prior step using image_gen tool (warm academic style, classical archaeology context).

- **Introductory Text Block**:
  - **Name**: "Dr. Sophia Nikolaou" (large, 42-48px, font-weight: 600, color: #0a2f5c, serif font-family if available).
  - **Title**: "Professor of Classical Archaeology" (22px, color: #b85c38, font-weight: 500).
  - **Institution**: "Aristotle University of Thessaloniki" (18px, color: #2c2c2c).
  - **Short Bio / Hook** (2-3 sentences, ~120 words max):
    > "Specializing in the material culture of the ancient Mediterranean, Dr. Nikolaou's research bridges classical archaeology with contemporary questions of heritage, identity, and landscape. With over two decades of fieldwork in Greece and the Aegean, she leads excavations and teaches the next generation of scholars at one of Europe's oldest universities."
  - **CTA Buttons** (flex row):
    - Primary: "Explore Research" → href="#research" (background: #b85c38, color: #f5f0e6, hover: darken).
    - Secondary: "View Publications" → href="#publications" (border: 2px solid #0a2f5c, color: #0a2f5c, hover: #0a2f5c bg with light text).
  - **Scroll Indicator**: Subtle down arrow or "Scroll to learn more" text at bottom of hero (links to #about), using CSS animation.

**HTML Structure Sketch**:
```html
<section id="hero" class="hero">
  <div class="hero-inner">
    <div class="hero-image">
      <img src="assets/portrait.png" alt="Portrait of Dr. Sophia Nikolaou..." />
    </div>
    <div class="hero-content">
      <h1>Dr. Sophia Nikolaou</h1>
      <p class="title">Professor of Classical Archaeology</p>
      <p class="institution">Aristotle University of Thessaloniki</p>
      <div class="bio">...</div>
      <div class="hero-ctas">
        <a href="#research" class="btn btn-primary">Explore Research</a>
        <a href="#publications" class="btn btn-secondary">View Publications</a>
      </div>
    </div>
  </div>
  <a href="#about" class="scroll-indicator" aria-label="Scroll to About section">↓</a>
</section>
```

**CSS Classes**:
- `.hero`
- `.hero-inner`
- `.hero-image`
- `.hero-content`
- `.hero-content h1`, `.title`, `.institution`, `.bio`
- `.hero-ctas`, `.btn`, `.btn-primary`, `.btn-secondary`
- `.scroll-indicator`

## Asset Paths
- Portrait: `assets/portrait.png` (relative to the root HTML file).
- Recommended: Create `assets/` directory at project root. Image should be optimized (under 300KB, WebP fallback if possible but keep simple PNG for self-contained).
- No external dependencies for this section.

## Interaction Behaviors
- **Smooth Scrolling Navigation**:
  - All header nav links (`<a href="#section-id">`) must use `scroll-behavior: smooth;` on html/body.
  - Target sections must have matching `id` attributes (e.g., `id="about"`, `id="research"`).
  - Offset for fixed header: Use `scroll-margin-top: 80px;` on target sections or JS smooth scroll with offset if needed.
  - No page jump; animate over 600-800ms.

- **Header Interactions**:
  - On scroll: Header remains sticky with subtle shadow or border intensification.
  - Hover states: Nav links transition color to #b85c38 (200ms ease), add bottom border.
  - Active state: Current section highlight (can be enhanced with Intersection Observer in later JS, but basic CSS :focus/:hover sufficient for spec).
  - Professor brand always links to `#hero` or top.

- **Hero Interactions**:
  - Portrait: Subtle scale or shadow lift on hover (optional, 1.02 transform).
  - CTA Buttons: 
    - Primary: Background color shift + slight scale.
    - Secondary: Fill on hover.
  - Scroll indicator: Gentle bounce animation (CSS keyframes) until user scrolls past hero.

- **Accessibility**:
  - All interactive elements have proper ARIA labels.
  - Keyboard navigable (Tab order logical).
  - Focus visible states (outline in #b85c38).
  - Reduced motion respect: `@media (prefers-reduced-motion: reduce)` disables animations.

- **Mobile-Specific**:
  - Hamburger toggles mobile nav (add `aria-expanded`).
  - Hero stacks; image first, then text (order via flex-direction column).
  - Touch-friendly button sizes (min 44px).

## Responsive Breakpoints
- Desktop: > 1024px (two-column hero).
- Tablet: 768px–1024px (adjust widths).
- Mobile: < 768px (stacked, larger touch targets, hamburger).

## Implementation Notes for Self-Contained HTML
- All CSS for this section must be embedded in a single `<style>` tag in the final `index.html`.
- Use semantic HTML5 (`<header>`, `<nav>`, `<section>`, `<h1>`).
- No external CSS/JS files for core functionality (inline minimal JS for mobile menu if needed).
- This section sets the tone; subsequent specs (About, Research, etc.) must inherit the same CSS variables and button styles.

## Next Steps / Dependencies
- Portrait image generation (use image_gen tool with academic portrait prompt).
- Full site content creation (bio, research areas, etc.).
- Integration into complete single-file HTML.
- Testing: Smooth scroll, mobile menu, color contrast.

**File Location**: This spec lives at `tasks/specs/header-hero.md`. It will guide the implementation of the header and hero in the final build step.

---
*Spec Version: 1.0 | Aligned with overall project plan for warm Mediterranean academic website.*
