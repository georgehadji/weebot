# Header / Navigation Section Spec

## Overview
Sticky navigation bar for Maya Rivera's portfolio website. Provides persistent access to key sections and reinforces brand identity.

## Layout
- **Position**: Fixed at top of viewport (`position: fixed; top: 0; left: 0; right: 0`)
- **Z-index**: Highest layer (e.g., `z-index: 1000`) to stay above all content
- **Height**: ~64px (standard touch-friendly nav height)
- **Background**: Dark theme background. Default: transparent (or semi-transparent `rgba(15, 15, 15, 0.8)` with `backdrop-filter: blur(10px)`). On scroll: solid dark (`#0F0F0F`)
- **Container**: Max-width centered (e.g., `max-width: 1200px; margin: 0 auto; padding: 0 24px`)

## Elements

### 1. Designer Name (Logo)
- **Text**: "Maya Rivera"
- **Position**: Left side of nav
- **Style**: Bold, distinctive typography (e.g., 1.25rem font-weight 700)
- **Link**: Anchors to top of page (`href="#"` or `#hero`)
- **Hover**: Subtle color shift or underline animation

### 2. Navigation Links
- **Items**: Work | About | Contact
- **Position**: Right side of nav (desktop); collapsible menu on mobile
- **Style**: Clean sans-serif, ~1rem, medium weight (500)
- **Anchor targets**:
  - Work → `#portfolio`
  - About → `#about`
  - Contact → `#contact`
- **Hover/Active**: Coral accent color (`#FF6B6B`) underline animation (200ms ease)

## Behavior
- **Sticky**: Remains fixed while scrolling
- **Scroll effect**: Background opacity/color may transition when user scrolls past hero
- **Mobile (< 768px)**: Hamburger menu (☰) replaces inline links; menu slides in from right or drops down
- **Accessibility**:
  - `aria-label` on nav element
  - Focus-visible styles for keyboard navigation
  - Skip-to-content link optional

## Responsive Breakpoints
| Breakpoint | Layout |
|------------|--------|
| Desktop (≥ 768px) | Inline links on right |
| Mobile (< 768px) | Hamburger menu icon |

## Assets
- None required (text-only nav)

## Dependencies
- Smooth-scroll behavior (CSS `scroll-behavior: smooth` or JS polyfill)
