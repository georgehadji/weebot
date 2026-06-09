# About Section Specification

## Overview
The About section introduces Athens Pro Plumbing as a trusted, local plumbing service. It builds credibility through a clean, professional two-column layout that pairs compelling copy with a visual element.

## Layout
- **Structure**: Two-column grid (text left, image right) on desktop; single-column stacked layout on mobile.
- **Background**: White (`#ffffff`).
- **Container**: Centered, max-width `1200px`, with horizontal padding (`1.5rem` default, `2rem` on larger screens).
- **Vertical Padding**: `5rem` top and bottom (`3rem` on mobile).

## Content

### Left Column — Text Content (approx. 55% width on desktop)
1. **Heading**
   - Text: "Trusted Plumbing Experts in Athens"
   - Font: Bold, `2rem` (mobile) / `2.5rem` (desktop).
   - Color: Dark navy (`#0a2540`).
   - Margin-bottom: `1rem`.

2. **Body Paragraph**
   - Text:  
     "Athens Pro Plumbing has been serving homes and businesses across Athens for over a decade. From emergency leak repairs to full bathroom installations, our licensed team delivers reliable workmanship with a commitment to punctuality and transparency. We understand the unique needs of Athenian properties—from classic neoclassical builds to modern apartments—and tailor every solution to ensure lasting results."
   - Font: Regular, `1rem`.
   - Color: Slate gray (`#425466`).
   - Line-height: `1.7`.
   - Margin-bottom: `1.25rem`.

3. **Secondary Paragraph (optional)**
   - Text:  
     "Fully insured and available 24/7, we take pride in being the local plumbers Athenians call first."
   - Same font styling as body paragraph.

### Right Column — Image Placeholder (approx. 45% width on desktop)
- **Element**: Responsive image container / `<img>` placeholder.
- **Placeholder behavior**: Gray background (`#e2e8f0`) with a centered icon or text label "Team Photo".
- **Border**: `4px` solid Greek blue accent (`#0057b8`) on the left edge of the image container.
- **Border-radius**: `0.5rem` on top-right, bottom-right, and bottom-left corners; `0` on top-left to merge visually with the accent border.
- **Aspect ratio**: `4:3` (or `object-fit: cover`).
- **Alt text**: "Athens Pro Plumbing team at work".

## Responsive Behavior
- **Desktop (≥768px)**: Two-column flex/grid layout with `2rem` gap between columns.
- **Mobile (<768px)**: Stack vertically. Image appears **below** text. Full-width columns. Accent border remains on the left. Padding and font sizes scale down per mobile specs above.

## Design Tokens
| Token | Value |
|-------|-------|
| Background | `#ffffff` |
| Heading Color | `#0a2540` |
| Body Text Color | `#425466` |
| Accent Border | `#0057b8` (Greek Blue) |
| Placeholder BG | `#e2e8f0` |
| Container Max-Width | `1200px` |
| Desktop Font (H2) | `2.5rem` |
| Mobile Font (H2) | `2rem` |
| Body Font Size | `1rem` |
| Line Height | `1.7` |

## Accessibility
- Heading should use `<h2>` tag for proper document outline.
- Image must include descriptive `alt` text.
- Ensure sufficient color contrast (WCAG AA) for all text.
- Touch targets should be adequate if any linked elements are added inside this section later.
