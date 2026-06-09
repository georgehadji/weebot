# Global Design System & Navigation Specification

## Project: Web Designer Portfolio Website

---

## 1. Color Palette

### Primary Colors
| Token | Hex | Usage |
|-------|-----|-------|
| `--color-primary` | `#0A0A0A` | Primary text, dark backgrounds, headings |
| `--color-primary-light` | `#1A1A1A` | Secondary dark surfaces, hover states |
| `--color-accent` | `#FF6B35` | CTAs, highlights, active states, accent elements |
| `--color-accent-hover` | `#E85A28` | Accent hover state |

### Neutral Colors
| Token | Hex | Usage |
|-------|-----|-------|
| `--color-white` | `#FFFFFF` | Light backgrounds, text on dark |
| `--color-gray-100` | `#F5F5F5` | Page background, subtle fills |
| `--color-gray-200` | `#E5E5E5` | Borders, dividers, disabled states |
| `--color-gray-300` | `#D4D4D4` | Secondary borders |
| `--color-gray-400` | `#A3A3A3` | Placeholder text, muted labels |
| `--color-gray-500` | `#737373` | Secondary text, captions |
| `--color-gray-600` | `#525252` | Body text secondary |
| `--color-gray-700` | `#404040` | Strong secondary text |
| `--color-gray-800` | `#262626` | Subheadings on light bg |
| `--color-gray-900` | `#171717` | Near-black elements |

### Semantic Colors
| Token | Hex | Usage |
|-------|-----|-------|
| `--color-success` | `#22C55E` | Success states, confirmations |
| `--color-error` | `#EF4444` | Error states, validation |
| `--color-warning` | `#F59E0B` | Warnings, notices |
| `--color-info` | `#3B82F6` | Informational elements |

### Gradients
| Token | Value | Usage |
|-------|-------|-------|
| `--gradient-hero` | `linear-gradient(135deg, #0A0A0A 0%, #1A1A1A 50%, #262626 100%)` | Hero section background |
| `--gradient-accent` | `linear-gradient(90deg, #FF6B35 0%, #FF8F5C 100%)` | Accent CTAs, highlights |
| `--gradient-overlay` | `linear-gradient(180deg, rgba(10,10,10,0) 0%, rgba(10,10,10,0.8) 100%)` | Image overlays |

---

## 2. Typography Scale

### Font Families
| Token | Value | Usage |
|-------|-------|-------|
| `--font-primary` | `"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif` | Headings, UI, body |
| `--font-mono` | `"JetBrains Mono", "Fira Code", "SF Mono", Consolas, monospace` | Code snippets, labels |

### Type Scale (Major Third — 1.25 ratio)
| Token | Size | Weight | Line Height | Letter Spacing | Usage |
|-------|------|--------|-------------|----------------|-------|
| `--text-xs` | 0.75rem (12px) | 400 | 1.5 | 0.01em | Captions, badges |
| `--text-sm` | 0.875rem (14px) | 400 | 1.5 | 0em | Secondary text, nav links |
| `--text-base` | 1rem (16px) | 400 | 1.6 | 0em | Body text |
| `--text-lg` | 1.125rem (18px) | 400 | 1.5 | -0.01em | Lead paragraphs |
| `--text-xl` | 1.25rem (20px) | 500 | 1.4 | -0.01em | Subheadings |
| `--text-2xl` | 1.5rem (24px) | 600 | 1.3 | -0.02em | Section subheadings |
| `--text-3xl` | 1.875rem (30px) | 600 | 1.2 | -0.02em | Small section titles |
| `--text-4xl` | 2.25rem (36px) | 700 | 1.1 | -0.02em | Section headings |
| `--text-5xl` | 3rem (48px) | 700 | 1.1 | -0.03em | Large headings |
| `--text-6xl` | 3.75rem (60px) | 800 | 1.0 | -0.03em | Hero display |
| `--text-7xl` | 4.5rem (72px) | 800 | 1.0 | -0.04em | Hero display large |

### Font Weights
| Token | Value | Usage |
|-------|-------|-------|
| `--font-normal` | 400 | Body text |
| `--font-medium` | 500 | Emphasis, labels |
| `--font-semibold` | 600 | Subheadings |
| `--font-bold` | 700 | Headings, strong |
| `--font-extrabold` | 800 | Display text |

---

## 3. Spacing Tokens

### Base Unit: 4px (0.25rem)

| Token | Value | Usage |
|-------|-------|-------|
| `--space-0` | 0 | Zero spacing |
| `--space-1` | 0.25rem (4px) | Tight gaps, icon padding |
| `--space-2` | 0.5rem (8px) | Small gaps, inline spacing |
| `--space-3` | 0.75rem (12px) | Compact padding |
| `--space-4` | 1rem (16px) | Default spacing unit |
| `--space-5` | 1.25rem (20px) | Small component padding |
| `--space-6` | 1.5rem (24px) | Card padding, form gaps |
| `--space-8` | 2rem (32px) | Medium component padding |
| `--space-10` | 2.5rem (40px) | Section internal spacing |
| `--space-12` | 3rem (48px) | Large gaps |
| `--space-16` | 4rem (64px) | Section padding small |
| `--space-20` | 5rem (80px) | Section padding medium |
| `--space-24` | 6rem (96px) | Section padding large |
| `--space-32` | 8rem (128px) | Section padding xlarge |

### Layout Tokens
| Token | Value | Usage |
|-------|-------|-------|
| `--container-max` | 1280px | Max content width |
| `--container-narrow` | 768px | Narrow content width (text) |
| `--page-padding` | 1.5rem (24px) | Horizontal page padding |
| `--page-padding-lg` | 3rem (48px) | Horizontal padding desktop |
| `--grid-gap` | 1.5rem (24px) | Grid column gap |
| `--grid-gap-lg` | 2rem (32px) | Grid gap desktop |

---

## 4. Responsive Breakpoints

| Token | Value | Target |
|-------|-------|--------|
| `--bp-sm` | 640px | Large phones |
| `--bp-md` | 768px | Tablets |
| `--bp-lg` | 1024px | Small laptops |
| `--bp-xl` | 1280px | Desktops |
| `--bp-2xl` | 1536px | Large screens |

### Breakpoint Behavior Summary
| Range | Behavior |
|-------|----------|
| < 640px | Single column, stacked nav (hamburger), reduced spacing, fluid typography |
| 640–768px | Two column grids possible, hamburger nav, medium spacing |
| 768–1024px | Multi-column layouts, desktop nav visible, full spacing |
| 1024–1280px | Full desktop layout, max grid columns, large spacing |
| > 1280px | Centered container, max-width constrained, generous whitespace |

### Responsive Type Scaling
- Hero display (`--text-7xl`): Scales to `--text-5xl` on md, `--text-4xl` on sm
- Section headings (`--text-4xl`): Scales to `--text-3xl` on sm
- Body text: Remains `--text-base` across all breakpoints

---

## 5. Navigation Specification

### Navigation Structure
```
[Logo] ─────────────────────── [About] [Work] [Services] [Testimonials] [Contact] [CTA]
```

### Nav Items
| Label | Target | Behavior |
|-------|--------|----------|
| Logo | `#hero` | Smooth scroll to top |
| About | `#about` | Smooth scroll |
| Work | `#portfolio` | Smooth scroll |
| Services | `#services` | Smooth scroll |
| Testimonials | `#testimonials` | Smooth scroll |
| Contact | `#contact` | Smooth scroll |
| CTA ("Let's Talk") | `#contact` | Primary button style, smooth scroll |

### Navigation States

#### Default
- Background: `transparent` (over hero) → `rgba(255,255,255,0.95)` with `backdrop-filter: blur(12px)` after scroll
- Height: 72px
- Logo: `--text-xl`, `--font-bold`, `--color-primary`
- Links: `--text-sm`, `--font-medium`, `--color-gray-600`
- Padding: `0 var(--page-padding)`

#### Scrolled State (triggered at 50px scroll)
- Background: `rgba(255,255,255,0.95)`
- `backdrop-filter: blur(12px)`
- `box-shadow: 0 1px 3px rgba(0,0,0,0.08)`
- Height remains 72px

#### Link Hover
- Color transition: `color 200ms ease`
- Hover color: `--color-primary`
- Optional: underline animation (scaleX from 0 to 1, origin left)

#### Active Section
- Color: `--color-accent`
- Font weight: `--font-semibold`
- Smooth indicator transition

### Mobile Navigation (< 768px)
- Hamburger icon: 24px, `--color-primary`
- Menu slides in from right or drops down
- Background: `--color-white` with shadow
- Full-width links, stacked vertically
- Link padding: `--space-4` vertical
- Close on selection or outside click
- Transition: `transform 300ms ease-out`, `opacity 200ms ease`

### CTA Button in Nav
- Background: `--color-accent`
- Color: `--color-white`
- Padding: `--space-2` `--space-5`
- Border radius: 6px
- Hover: `--color-accent-hover`, slight translateY(-1px)
- Transition: `all 200ms ease`

---

## 6. Shadow & Elevation Tokens

| Token | Value | Usage |
|-------|-------|-------|
| `--shadow-sm` | `0 1px 2px rgba(0,0,0,0.04)` | Subtle elevation |
| `--shadow-md` | `0 4px 6px -1px rgba(0,0,0,0.06), 0 2px 4px -2px rgba(0,0,0,0.04)` | Cards |
| `--shadow-lg` | `0 10px 15px -3px rgba(0,0,0,0.08), 0 4px 6px -4px rgba(0,0,0,0.04)` | Modals, dropdowns |
| `--shadow-xl` | `0 20px 25px -5px rgba(0,0,0,0.08), 0 8px 10px -6px rgba(0,0,0,0.04)` | Floating elements |
| `--shadow-glow` | `0 0 20px rgba(255,107,53,0.3)` | Accent glow |

---

## 7. Border Radius Tokens

| Token | Value | Usage |
|-------|-------|-------|
| `--radius-sm` | 4px | Small elements, tags |
| `--radius-md` | 8px | Buttons, inputs |
| `--radius-lg` | 12px | Cards, panels |
| `--radius-xl` | 16px | Large cards, modals |
| `--radius-2xl` | 24px | Feature sections |
| `--radius-full` | 9999px | Pills, avatars |

---

## 8. Animation Tokens

### Durations
| Token | Value | Usage |
|-------|-------|-------|
| `--duration-fast` | 150ms | Micro-interactions |
| `--duration-normal` | 300ms | Standard transitions |
| `--duration-slow` | 500ms | Entrance animations |
| `--duration-slower` | 700ms | Complex animations |

### Easings
| Token | Value | Usage |
|-------|-------|-------|
| `--ease-default` | `cubic-bezier(0.4, 0, 0.2, 1)` | Standard |
| `--ease-in` | `cubic-bezier(0.4, 0, 1, 1)` | Entering |
| `--ease-out` | `cubic-bezier(0, 0, 0.2, 1)` | Exiting |
| `--ease-bounce` | `cubic-bezier(0.34, 1.56, 0.64, 1)` | Playful |
| `--ease-smooth` | `cubic-bezier(0.65, 0, 0.35, 1)` | Dramatic |

### Common Patterns
- Fade in: `opacity 0 → 1`, `--duration-normal`, `--ease-out`
- Slide up: `translateY(20px) → translateY(0)`, `--duration-slow`, `--ease-out`
- Scale hover: `scale(1) → scale(1.02)`, `--duration-fast`, `--ease-default`

---

## 9. Z-Index Scale

| Token | Value | Usage |
|-------|-------|-------|
| `--z-base` | 0 | Default |
| `--z-dropdown` | 100 | Dropdowns |
| `--z-sticky` | 200 | Sticky nav |
| `--z-drawer` | 300 | Mobile menu |
| `--z-modal` | 400 | Modals |
| `--z-toast` | 500 | Notifications |
| `--z-tooltip` | 600 | Tooltips |

---

## 10. Global Patterns

### Button Variants
| Variant | Background | Text | Border | Hover |
|---------|------------|------|--------|-------|
| Primary | `--color-accent` | `--color-white` | none | `--color-accent-hover`, lift |
| Secondary | `--color-primary` | `--color-white` | none | `--color-primary-light` |
| Outline | transparent | `--color-primary` | 1px `--color-gray-200` | bg `--color-gray-100` |
| Ghost | transparent | `--color-gray-600` | none | bg `--color-gray-100` |

### Focus States
- Outline: 2px solid `--color-accent`
- Outline offset: 2px
- Applied to all interactive elements
- Remove default browser outline

### Selection
- Background: `--color-accent` at 30% opacity
- Text: inherit

### Scrollbar
- Width: 8px
- Track: `--color-gray-100`
- Thumb: `--color-gray-300`
- Thumb hover: `--color-gray-400`

### Smooth Scroll
- `scroll-behavior: smooth` globally
- Scroll padding top: 80px (nav height + buffer)
