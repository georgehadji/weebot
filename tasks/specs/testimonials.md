# Testimonials Section — Section Specification

**Project:** Kallos Plastic Surgery Website — Dr. Jorgis Chatzivantsidis
**Section Position:** #6 on homepage (after Results/B&A section, before Contact)
**Target File:** `src/components/sections/TestimonialsSection.tsx`
**Data Source:** `src/data/index.ts` — `testimonials[]` array
**i18n Keys:** `testimonials.title`, `testimonials.subtitle`, `testimonials.verified`
**Copy Source:** `website_copy/03_gallery_testimonials.md`, `messages/en.json`

---

## 1. Component Architecture

### File Structure
```
src/
├── components/
│   └── sections/
│       └── TestimonialsSection.tsx    ← THIS SPEC
└── data/
    └── index.ts                       ← testimonials[] already defined
```

### Component Tree
```
TestimonialsSection (default export)
├── Section wrapper (<section id="testimonials">)
│   ├── Section Header
│   │   ├── Badge ("Patient Testimonials")
│   │   ├── H2 Title (font-serif)
│   │   ├── Subtitle (text-neutral-600)
│   │   └── Gradient Divider (h-1 rounded-full w-20)
│   ├── Testimonial Carousel
│   │   ├── TestimonialCard (×5, mapped from data)
│   │   │   ├── Star Rating (5 filled stars)
│   │   │   ├── Quote text
│   │   │   ├── Patient metadata
│   │   │   │   ├── Name + "Verified Patient" badge
│   │   │   │   └── Procedure label
│   │   │   └── Decorative quote icon (SVG, top-left corner)
│   │   └── Navigation Controls
│   │       ├── Left arrow button
│   │       ├── Dot indicators (active dot highlighted)
│   │       └── Right arrow button
│   └── Optional: "Share Your Story" CTA below carousel
```

---

## 2. Visual Design Specifications

### Section Container
| Property | Value |
|---|---|
| Element | `<section id="testimonials">` |
| Background | `bg-white` |
| Padding Y | `py-20` (80px) |
| Inner max width | `max-w-7xl mx-auto px-6` |

### Section Header
| Element | Property | Value |
|---|---|---|
| Badge | Background | `bg-primary-50 text-primary-600` rounded-full px-4 py-1.5 |
| Badge | Font | `text-sm font-medium` |
| H2 Title | Font Family | `font-serif` (Playfair Display) |
| H2 Title | Font Size | `text-4xl md:text-5xl` |
| H2 Title | Font Weight | `font-semibold` |
| H2 Title | Color | `text-neutral-900` |
| H2 Title | Margin | `mt-3 mb-4` |
| Subtitle | Color | `text-neutral-600` |
| Subtitle | Max Width | `max-w-2xl mx-auto` |
| Divider | Width | `w-20` (80px) |
| Divider | Height | `h-1` (4px) |
| Divider | Border Radius | `rounded-full` |
| Divider | Background | `bg-gradient-to-r from-primary-500 to-accent-500` |
| Divider | Margin | `mx-auto mt-6` |

### Testimonial Card
| Property | Value |
|---|---|
| Background | `bg-neutral-50` |
| Border Radius | `rounded-2xl` (16px) |
| Padding | `p-8` (32px) all sides |
| Width | `md:w-[420px]` (fixed width for carousel) |
| Min Height | `min-h-[280px]` |
| Border | `border border-neutral-100` |
| Box Shadow | `shadow-soft` → on hover: `shadow-elevated` |
| Hover Transform | `hover:-translate-y-1` |
| Transition | `transition-all duration-300` |
| Position | `relative` (for decorative quote icon) |

### Quote Decorative Icon (SVG corner)
| Property | Value |
|---|---|
| Position | `absolute top-6 left-6` |
| Color | `text-primary-200` (faded gold) |
| Size | `w-12 h-12` (48px) |
| Opacity | `opacity-40` |
| SVG | Double quotation mark path |

### Star Rating
| Property | Value |
|---|---|
| Color (filled) | `text-amber-400` |
| Color (empty) | `text-neutral-200` |
| Size | `w-5 h-5` (20px) |
| Spacing | `gap-1` between stars |
| Count | 5 stars (all filled — all data entries are 5) |
| SVG | Star path (`fill="currentColor" viewBox="0 0 20 20"`) |

### Quote Text
| Property | Value |
|---|---|
| Font Size | `text-base md:text-lg` |
| Line Height | `leading-relaxed` |
| Color | `text-neutral-700` |
| Margin Top | `mt-6` (room after stars) |
| Max Lines | Truncate at 6 lines with `line-clamp-6` |

### Patient Name + Verified Badge
| Property | Value |
|---|---|
| Name | `font-semibold text-neutral-900` |
| Verified Badge | `inline-flex items-center gap-1 text-xs text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded-full` |
| Badge Icon | Checkmark SVG, `w-3 h-3` |

### Procedure Label
| Property | Value |
|---|---|
| Color | `text-neutral-500 text-sm` |
| Margin Top | `mt-1` |

### Carousel Navigation
| Element | Property | Value |
|---|---|---|
| Container | Layout | `flex items-center justify-center gap-4 mt-10` |
| Arrow Btn | Size | `w-12 h-12 rounded-full bg-white border border-neutral-200` |
| Arrow Btn | Icon | SVG chevron left/right, `w-5 h-5 text-neutral-600` |
| Arrow Btn | Hover | `hover:bg-primary-50 hover:border-primary-200 hover:text-primary-600` |
| Arrow Btn | Disabled | `opacity-30 cursor-not-allowed` |
| Dot | Size | `w-2.5 h-2.5 rounded-full bg-neutral-300` |
| Dot Active | Color | `bg-primary-500` (scale to `w-3 h-3`) |
| Dot Transition | | `transition-all duration-300` |

### "Share Your Story" CTA (below carousel)
| Property | Value |
|---|---|
| Container | `text-center mt-12 pt-8 border-t border-neutral-100` |
| Text | `text-neutral-600 text-sm mb-4` |
| Button | `btn btn-outline` — `border-primary-300 text-primary-600 hover:bg-primary-50` |
| Button Padding | `px-6 py-3 rounded-xl` |

---

## 3. Interaction Behaviors

### Carousel (Client-side, `"use client"`)
1. **Initial State**: Show first 2-3 testimonial cards visible in a flex row with `overflow-hidden`
2. **Autoplay**: Auto-advance every 5 seconds (`setInterval`), pause on hover
3. **Manual Navigation**: Left/right arrow buttons shift by 1 card per click
4. **Dot Navigation**: Clicking a dot snaps to the corresponding card index
5. **Edge Behavior**: 
   - At start: Left arrow disabled (`opacity-30 cursor-not-allowed`)
   - At end: Right arrow disabled
   - Wrap-around: Optional — or stop at last card
6. **Swipe (future)**: Touch swipe support can be added later with `framer-motion`

### Card Hover
1. Card lifts (`hover:-translate-y-1`)
2. Shadow increases (`shadow-soft` → `shadow-elevated`)
3. Border subtly changes to `hover:border-primary-200`
4. Transition: `duration-300 ease-out`

### Star Rating Display
- Static display only (no interactive rating on this page)
- All 5 stars filled for all current testimonials
- Update if `rating` field changes in data source

### Verified Badge
- Static display with checkmark icon
- Tooltip on click/hover (optional, future): "This patient's identity has been verified"

---

## 4. Data Schema

```typescript
// Already in src/data/index.ts
export const testimonials = [
  {
    id: 1,
    name: "Maria K.",
    procedure: "Rhinoplasty",
    text: "Dr. Chatzivantsidis completely transformed my confidence...",
    rating: 5
  },
  // ... 4 more entries
]
```

### Fields
| Field | Type | Description |
|---|---|---|
| `id` | number | Unique identifier |
| `name` | string | Patient first name + initial (privacy) |
| `procedure` | string | Procedure name for context |
| `text` | string | Full testimonial quote |
| `rating` | number | 1-5 star rating |

---

## 5. Asset Dependencies

### Icons (Inline SVG — no external icon library needed)
| Icon | Usage | Quantity |
|---|---|---|
| Star (filled) | Rating display | 5 per card × 5 cards = 25 |
| Quote mark (decorative) | Card decoration | 1 per card × 5 cards = 5 |
| Chevron left | Carousel navigation | 1 |
| Chevron right | Carousel navigation | 1 |
| Checkmark | Verified badge | 1 per card × 5 cards = 5 |

**Source**: All inline SVGs in component file. No external icon library import needed.

### Gradients (Tailwind)
- `from-primary-500 to-accent-500` — Section divider
- `bg-gradient-to-br from-primary-50 to-accent-50` — Optional card background variant

### Images
- **None** — Section uses decorative SVGs + text only
- Patient photos can be added later as optional `avatar` field in data

---

## 6. Responsive Behavior

### Desktop (≥1024px)
- Carousel: 3 cards visible side-by-side
- Card width: `w-[380px]` with `gap-8`
- Section padding: `py-20`

### Tablet (768px–1023px)
- Carousel: 2 cards visible side-by-side
- Card width: `w-[340px]` with `gap-6`
- Section padding: `py-16`

### Mobile (<768px)
- Carousel: 1 card visible, centered
- Card width: `w-full max-w-[380px]`
- Card padding: `p-6`
- Section padding: `py-12 px-4`
- Navigation arrows: Smaller (`w-10 h-10`)
- Title: `text-3xl`

---

## 7. Accessibility

- All interactive elements (arrows, dots, CTA button) must be focusable
- Arrow buttons: `aria-label="Previous testimonial"` / `aria-label="Next testimonial"`
- Dot indicators: `aria-label="Go to testimonial N of M"`
- Carousel container: `role="region" aria-roledescription="carousel" aria-label="Patient testimonials"`
- Each card: `role="group" aria-roledescription="slide"`
- Star SVGs: `aria-hidden="true"` (purely decorative with rating as text)
- Verified badge: `aria-label="Verified patient"`
- Colors: All text meets WCAG 2.1 AA 4.5:1 on `bg-white`/`bg-neutral-50`

---

## 8. Implementation Steps

1. Create `TestimonialsSection.tsx` in `src/components/sections/`
2. Import `testimonials` from `@/data`
3. Import `useState`, `useEffect`, `useCallback` from React (for carousel state)
4. Add `"use client"` directive at top
5. Pattern after existing sections (HeroSection, AboutSection) for:
   - Section wrapper with `id="testimonials"`
   - Badge → H2 → divider header pattern
6. Implement carousel with:
   - `currentIndex` state
   - `next()` / `prev()` handlers
   - Auto-advance via `useEffect` + `setInterval`
   - Pause on hover via `onMouseEnter`/`onMouseLeave`
7. Wire up to `page.tsx`: import and place after `<ResultsSection />`
8. Test: Verify all 5 cards render, navigation works, responsive breakpoints

---

## 9. Dependencies

| Dependency | Purpose | Status |
|---|---|---|
| React `useState` | Carousel index tracking | Built-in |
| React `useEffect` | Auto-advance timer | Built-in |
| React `useCallback` | Memoized handlers | Built-in |
| `@/data` (testimonials) | Data source | ✅ Already exists |
| `tailwindcss` | Styling | ✅ Already configured |
| `messages/*.json` | i18n strings | ✅ Already configured (future use) |

No external packages required.
