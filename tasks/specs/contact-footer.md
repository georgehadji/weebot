# Contact & Footer Specification

## Section Overview
This specification defines the Contact section (id="contact") and the site-wide Footer for the single-page academic website for Dr. Sophia Nikolaou, Professor of Classical Archaeology at Aristotle University of Thessaloniki. The design uses a clean, professional, warm Mediterranean academic aesthetic with a limited color palette emphasizing scholarly gravitas and classical heritage.

**Primary Purpose**:
- Provide direct, professional contact details for academic inquiries, research collaboration, student appointments, and media requests.
- Enable immediate email contact via a prominent mailto link.
- Display office location and regular office hours for in-person or scheduled meetings.
- Deliver a clean, institutional footer with copyright, university affiliation, and basic navigation/legal links.
- Serve as the final major section before the footer, reachable via the main navigation ("Contact").

**Design Principles**:
- Warm, earthy Mediterranean palette evoking ancient Greek heritage (terracotta, cream, deep blue).
- High contrast for readability and accessibility (WCAG AA minimum).
- Minimalist typography with serif accents for academic feel.
- Card-based or structured info layout for scannability.
- Responsive: Desktop-first with stacked mobile layout.
- Self-contained: All styles embedded in the final HTML; reuse CSS custom properties from prior sections (header-hero, research, publications-teaching).
- Interaction: Subtle, professional hover states; primary action is a direct email link (mailto:).

## Color Palette (Exact CSS Values)
Use these exact hex values (inherited from header-hero.md and research.md). Define as CSS custom properties at the root for consistency across the site.

```css
:root {
  --deep-blue: #0a2f5c;      /* Primary: section headings, card titles, footer bg, borders */
  --cream: #f5f0e6;          /* Backgrounds: section bg, subtle surfaces */
  --terracotta: #b85c38;     /* Accent: CTAs, mailto link, left accent bars, hover states */
  --warm-white: #faf8f3;     /* Card backgrounds, light surfaces */
  --dark-text: #2c2c2c;      /* Body text, descriptions, footer text */
  --light-text: #f5f0e6;     /* Text on dark backgrounds (footer) */
  --card-shadow: rgba(10, 47, 92, 0.08);  /* Soft shadow for contact cards */
  --card-hover-shadow: rgba(10, 47, 92, 0.15);
  --border-subtle: #e5e0d6;  /* Light borders */
}
```

**Usage Notes**:
- Deep blue (#0a2f5c) for all structural headings and footer background.
- Cream (#f5f0e6) as the contact section background.
- Terracotta (#b85c38) for the primary email CTA, accent bars, and interactive elements.
- Warm white (#faf8f3) for contact info cards.
- Avoid pure black/white; always use palette variants for warmth.
- All body text uses --dark-text; headings use --deep-blue.

## Component List and Structure

### 1. Contact Section (id="contact")
- **Background**: Solid `--cream` (#f5f0e6)
- **Vertical Padding**: 5rem top and bottom (3rem on mobile)
- **Container**: Centered, max-width `1200px`, horizontal padding `2rem`
- **Heading**:
  - Text: "Contact"
  - Font: 2.25rem (36px) desktop / 1.875rem (30px) mobile, font-weight: 700, color: #0a2f5c
  - Margin-bottom: 0.5rem
- **Introductory Paragraph**:
  - 1–2 sentences.
  - Text (placeholder):
    "I welcome inquiries from prospective students, collaborators, and colleagues. Please reach out via email or schedule a meeting during my office hours."
  - Font: 1.05rem (17px), line-height: 1.7, color: #2c2c2c
  - Max-width: 720px
  - Margin-bottom: 2.5rem

#### Contact Information Layout
- **Layout**: CSS Grid or Flex
  - Desktop (≥1024px): 3 columns, gap: 1.5rem
  - Tablet (≥768px): 2 columns or 3 if space allows, gap: 1.25rem
  - Mobile (<768px): 1 column, gap: 1rem
- **Each Contact Card** (3 total — Email, Office Location, Office Hours):
  - Background: #faf8f3 (warm-white)
  - Border: 1px solid #e5e0d6
  - Left accent bar: 4px solid #b85c38 (terracotta)
  - Padding: 1.5rem
  - Border-radius: 6px
  - Box-shadow: 0 2px 8px var(--card-shadow)
  - **Icon** (inline SVG or Unicode for self-containment):
    - Email: envelope icon
    - Location: map pin icon
    - Hours: clock icon
  - **Label** (small uppercase):
    - 0.75rem, font-weight: 600, color: #b85c38, letter-spacing: 0.5px, margin-bottom: 0.25rem
  - **Main Content**:
    - Email card:
      - "sophia.nikolaou@auth.gr"
      - Prominent `<a href="mailto:sophia.nikolaou@auth.gr" class="contact-email">Email me directly</a>` styled as primary button-like link (background #b85c38, color #f5f0e6, or inline with terracotta underline + hover fill).
    - Location card:
      - Full address block:
        "Office 312<br>
        Department of Classical Archaeology<br>
        Aristotle University of Thessaloniki<br>
        541 24 Thessaloniki, Greece"
      - Font: 0.95rem, line-height: 1.5, color: #2c2c2c
    - Hours card:
      - "Tuesdays: 14:00 – 16:00<br>
        Thursdays: 10:00 – 12:00<br>
        Or by appointment"
      - Note: "Please email in advance to confirm availability."
      - Font: 0.95rem, line-height: 1.5, color: #2c2c2c

**Accessibility note**: Use `<address>` element for the location block where semantically appropriate. All contact details should be machine-readable where possible.

### 2. Footer
- **Location**: Immediately after the contact section (no extra section wrapper needed).
- **Background**: Solid `--deep-blue` (#0a2f5c)
- **Text Color**: --light-text (#f5f0e6)
- **Padding**: 2rem top and bottom (1.5rem on mobile)
- **Container**: Centered, max-width `1200px`, horizontal padding `2rem`
- **Layout**: Flex (desktop: space-between or centered stack on mobile)
  - Left / Main: Copyright line + university affiliation
  - Right (desktop): Small institutional links (optional: Department page, University home)
- **Content**:
  - Copyright: "© 2025 Dr. Sophia Nikolaou. All rights reserved."
  - Affiliation line: "Aristotle University of Thessaloniki • Department of Classical Archaeology"
  - Links (small, subtle):
    - "University Website" → https://www.auth.gr (external, target="_blank" rel="noopener")
    - "Department of Archaeology" → placeholder or real dept URL
  - Font sizes: 0.85rem for copyright, 0.8rem for links
  - No heavy decoration; clean and institutional.

**HTML Structure Sketch** (combined for contact + footer):
```html
<!-- Contact -->
<section id="contact" class="contact-section">
  <div class="container">
    <h2 class="section-heading">Contact</h2>
    <p class="section-intro">I welcome inquiries from prospective students, collaborators, and colleagues. Please reach out via email or schedule a meeting during my office hours.</p>
    
    <div class="contact-grid">
      <!-- Email Card -->
      <div class="contact-card">
        <div class="contact-icon">✉️</div>
        <div class="contact-label">EMAIL</div>
        <a href="mailto:sophia.nikolaou@auth.gr" class="contact-link">sophia.nikolaou@auth.gr</a>
        <a href="mailto:sophia.nikolaou@auth.gr" class="btn btn-primary contact-cta">Email me directly</a>
      </div>
      
      <!-- Location Card -->
      <div class="contact-card">
        <div class="contact-icon">📍</div>
        <div class="contact-label">OFFICE</div>
        <address class="contact-address">
          Office 312<br>
          Department of Classical Archaeology<br>
          Aristotle University of Thessaloniki<br>
          541 24 Thessaloniki, Greece
        </address>
      </div>
      
      <!-- Hours Card -->
      <div class="contact-card">
        <div class="contact-icon">🕒</div>
        <div class="contact-label">OFFICE HOURS</div>
        <div class="contact-hours">
          Tuesdays: 14:00 – 16:00<br>
          Thursdays: 10:00 – 12:00<br>
          <span class="note">Or by appointment</span>
        </div>
      </div>
    </div>
  </div>
</section>

<!-- Footer -->
<footer class="site-footer">
  <div class="container">
    <div class="footer-content">
      <div class="footer-info">
        <p class="copyright">© 2025 Dr. Sophia Nikolaou. All rights reserved.</p>
        <p class="affiliation">Aristotle University of Thessaloniki • Department of Classical Archaeology</p>
      </div>
      <div class="footer-links">
        <a href="https://www.auth.gr" target="_blank" rel="noopener">University Website</a>
        <a href="https://www.auth.gr/en/school/..." target="_blank" rel="noopener">Department</a>
      </div>
    </div>
  </div>
</footer>
```

**CSS Classes to Use** (exact for consistency):
- `.contact-section`, `.container`, `.section-heading`, `.section-intro`
- `.contact-grid`, `.contact-card`, `.contact-icon`, `.contact-label`
- `.contact-link`, `.contact-address`, `.contact-hours`, `.note`
- `.btn`, `.btn-primary` (reuse from hero)
- `.site-footer`, `.footer-content`, `.footer-info`, `.footer-links`, `.copyright`, `.affiliation`

## Asset Paths
- No external image assets required for this section.
- Icons: Use inline Unicode emojis (✉️ 📍 🕒) or simple inline SVG elements for better accessibility and self-containment. Avoid external icon fonts.
- Recommended: Keep all icons as text or minimal SVG inside the cards (no separate asset files).

## Interaction Behaviors
- **Email Link & CTA**:
  - Primary `mailto:` link opens the user's default email client with pre-filled recipient.
  - Hover: Color shift or subtle background fill on the CTA button (terracotta to a slightly darker shade).
  - The email address itself is also clickable.
- **Contact Cards**:
  - Desktop hover: `transform: translateY(-2px)`, increased shadow (`--card-hover-shadow`), subtle accent bar intensification.
  - Transition: 160ms ease-out.
- **Footer Links**:
  - Subtle color change on hover (light-text to a warmer off-white or terracotta tint).
  - External links use `target="_blank" rel="noopener noreferrer"`.
- **Accessibility**:
  - Use semantic `<section>`, `<address>`, `<footer>`, `<h2>`.
  - Sufficient color contrast (all text ≥ 4.5:1).
  - Focus states: 2px solid #b85c38 outline with offset.
  - ARIA: `aria-label` on email links if needed; proper `alt` not applicable here.
  - Keyboard accessible (all links and CTAs reachable via Tab).
  - `scroll-margin-top: 80px;` on the `#contact` section (consistent with prior specs to offset fixed header).
- **Mobile-Specific**:
  - Cards stack vertically.
  - Larger touch targets (min 44px height for links/buttons).
  - Footer stacks into a single centered column.
- **No Form** (per this spec): This section focuses on static contact information + direct mailto. A full contact form is out of scope unless added in a future iteration (would require additional JS validation for self-contained HTML).

## Responsive Breakpoints
- Desktop: > 1024px (3-column contact grid)
- Tablet: 768px–1024px (2- or 3-column grid)
- Mobile: < 768px (single column cards, stacked footer)

## Implementation Notes for Self-Contained HTML
- All CSS for this section must be embedded in a single `<style>` tag in the final `index.html` (reuse and extend existing `:root` variables and `.btn` styles).
- Use semantic HTML5 (`<section>`, `<address>`, `<footer>`).
- No external CSS/JS files.
- This section closes the main content flow; the footer follows directly.
- Ensure the contact section appears after Teaching in the document order (matching nav order: About → Research → Publications → Teaching → Contact).

## Placeholder Content Notes
- Email address: `sophia.nikolaou@auth.gr` (replace with actual institutional address if different).
- Office details and hours are realistic academic placeholders — update with verified information before final deployment.
- Footer links: Use real department URL when known (e.g., https://www.auth.gr/en/departments/archaeology or equivalent).

## Next Steps / Dependencies
- Ensure prior sections (header-hero, about-research, publications-teaching) are implemented so CSS variables and button styles are already defined.
- Integrate into complete single-file HTML after all section specs are complete.
- Testing: mailto link functionality, responsive grid, color contrast, footer alignment, smooth scroll from nav.
- Optional future enhancement: Add a lightweight contact form (with client-side validation only) if required.

**File Location**: This spec lives at `tasks/specs/contact-footer.md`. It will guide the implementation of the contact section and footer in the final build step.
