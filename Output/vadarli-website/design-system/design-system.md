# Vadarli Healthcare - Design System

## Brand Identity

### Brand Name
**Vadarli Healthcare** — A modern, trustworthy healthcare provider brand.

### Brand Values
- Trust & Reliability
- Compassionate Care
- Medical Excellence
- Innovation & Technology
- Patient-Centered Approach

---

## Color Palette

### Primary Colors
| Color Name | Hex Code | Usage |
|---|---|---|
| Medical Blue | #0077B6 | Primary brand color, CTAs, links |
| Deep Navy | #023E8A | Headings, footer, navigation |
| White | #FFFFFF | Backgrounds, text on dark |

### Secondary Colors
| Color Name | Hex Code | Usage |
|---|---|---|
| Teal Accent | #00B4D8 | Highlights, icons, accents |
| Light Blue | #90E0EF | Subtle backgrounds, hover states |
| Soft Cyan | #CAF0F8 | Cards, sections, badges |

### Neutral Colors
| Color Name | Hex Code | Usage |
|---|---|---|
| Dark Gray | #333333 | Body text |
| Medium Gray | #666666 | Secondary text, placeholders |
| Light Gray | #E0E0E0 | Borders, dividers |
| Off-White | #F8F9FA | Section backgrounds |

### Semantic Colors
| Color Name | Hex Code | Usage |
|---|---|---|
| Success Green | #28A745 | Success states, confirmations |
| Warning Orange | #FFC107 | Warnings, attention |
| Error Red | #DC3545 | Errors, urgent alerts |
| Info Blue | #17A2B8 | Informational elements |

---

## Typography

### Font Families
- **Primary (Headings):** 'Poppins', sans-serif — Modern, clean, professional
- **Secondary (Body):** 'Open Sans', sans-serif — Highly readable, accessible
- **Accent (Optional):** 'Lato', sans-serif — For special callouts

### Type Scale
| Element | Size | Weight | Line Height |
|---|---|---|---|
| H1 | 48px / 3rem | 700 (Bold) | 1.2 |
| H2 | 36px / 2.25rem | 600 (Semi-Bold) | 1.3 |
| H3 | 28px / 1.75rem | 600 (Semi-Bold) | 1.3 |
| H4 | 22px / 1.375rem | 500 (Medium) | 1.4 |
| H5 | 18px / 1.125rem | 500 (Medium) | 1.4 |
| Body Large | 18px / 1.125rem | 400 (Regular) | 1.6 |
| Body | 16px / 1rem | 400 (Regular) | 1.6 |
| Body Small | 14px / 0.875rem | 400 (Regular) | 1.5 |
| Caption | 12px / 0.75rem | 400 (Regular) | 1.4 |
| Button | 16px / 1rem | 600 (Semi-Bold) | 1.0 |

---

## Spacing System

### Base Unit: 8px

| Token | Value | Usage |
|---|---|---|
| xs | 4px | Tight spacing, icon gaps |
| sm | 8px | Small gaps, inline elements |
| md | 16px | Standard padding, card gaps |
| lg | 24px | Section padding, large gaps |
| xl | 32px | Between components |
| 2xl | 48px | Section spacing |
| 3xl | 64px | Major section breaks |
| 4xl | 96px | Page-level spacing |

---

## Components

### Buttons

#### Primary Button
- Background: #0077B6 (Medical Blue)
- Text: White, 16px, Semi-Bold
- Padding: 12px 32px
- Border Radius: 8px
- Hover: Background darkens to #005F99
- Transition: all 0.3s ease

#### Secondary Button
- Background: Transparent
- Border: 2px solid #0077B6
- Text: #0077B6, 16px, Semi-Bold
- Padding: 10px 30px
- Border Radius: 8px
- Hover: Background #0077B6, Text white

#### CTA Button (Large)
- Background: #0077B6
- Text: White, 18px, Bold
- Padding: 16px 48px
- Border Radius: 10px
- Box Shadow: 0 4px 15px rgba(0, 119, 182, 0.3)

### Cards

#### Service Card
- Background: White
- Border: 1px solid #E0E0E0
- Border Radius: 12px
- Padding: 24px
- Box Shadow: 0 2px 10px rgba(0, 0, 0, 0.05)
- Hover: Box Shadow 0 8px 25px rgba(0, 119, 182, 0.15), translateY(-4px)

#### Doctor Card
- Background: White
- Border Radius: 12px
- Overflow: Hidden
- Box Shadow: 0 2px 10px rgba(0, 0, 0, 0.05)
- Hover: Box Shadow 0 8px 25px rgba( 0, 0, 0, 0.1)

### Form Inputs
- Height: 48px
- Border: 1px solid #E0E0E0
- Border Radius: 8px
- Padding: 12px 16px
- Font Size: 16px
- Focus: Border color #0077B6, box-shadow 0 0 0 3px rgba(0, 119, 182, 0.1)

### Navigation
- Height: 80px
- Background: White
- Box Shadow: 0 2px 10px rgba(0, 0, 0, 0.05)
- Position: Fixed/Sticky
- Z-index: 1000

---

## Icons

### Icon Style
- Style: Line icons (outlined) with 2px stroke
- Size: 24px (standard), 32px (feature), 48px (hero)
- Color: Inherits from context or uses Medical Blue
- Library: Phosphor Icons or Feather Icons

### Common Icons
- Heart / Pulse — Healthcare
- Stethoscope — General Practice
- Brain — Neurology
- Bone — Orthopedics
- Eye — Ophthalmology
- Tooth — Dentistry
- Baby — Pediatrics
- Phone — Contact
- Calendar — Appointment
- Map Pin — Location

---

## Imagery

### Photography Style
- Warm, natural lighting
- Diverse patients and staff
- Clean, modern medical environments
- Authentic moments (not overly staged)
- Soft focus backgrounds for portraits

### Image Treatments
- Hero images: Full-width, with subtle blue overlay (rgba(2, 62, 138, 0.4))
- Doctor portraits: Circular or rounded-square crop
- Service images: 16:9 ratio, rounded corners
- Icons: Consistent line style, Medical Blue color

---

## Grid System

### Desktop (≥1200px)
- Columns: 12
- Gutter: 24px
- Max Width: 1440px
- Margin: Auto (centered)

### Tablet (768px - 1199px)
- Columns: 8
- Gutter: 20px
- Margin: 24px

### Mobile (< 768px)
- Columns: 4
- Gutter: 16px
- Margin: 16px

---

## Breakpoints

| Breakpoint | Width | Target |
|---|---|---|
| xs | 0px | Small phones |
| sm | 576px | Phones |
| md | 768px | Tablets |
| lg | 992px | Small desktops |
| xl | 1200px | Desktops |
| xxl | 1440px | Large screens |

---

## Animations & Transitions

### Micro-interactions
- Button hover: background-color 0.3s ease
- Card hover: transform 0.3s ease, box-shadow 0.3s ease
- Link hover: color 0.2s ease, underline slide-in
- Form focus: border-color 0.2s ease, box-shadow 0.2s ease

### Page Transitions
- Fade in: opacity 0.3s ease
- Slide up: transform translateY(20px) → translateY(0), 0.4s ease
- Scroll animations: Intersection Observer, fade-in-up

### Loading States
- Skeleton screens with shimmer animation
- Spinner: Medical Blue, 40px, 1s linear infinite

---

## Accessibility

### WCAG 2.1 AA Compliance
- Minimum contrast ratio: 4.5:1 for body text
- Minimum contrast ratio: 3:1 for large text
- Focus indicators: Visible 2px outline on all interactive elements
- Alt text: All images have descriptive alt attributes
- ARIA labels: Proper labeling for interactive elements
- Keyboard navigation: Full site navigable via keyboard
- Skip navigation: "Skip to main content" link

### Font Sizes
- Minimum body font: 16px
- Scalable up to 200% without loss of content
- Relative units (rem) for all font sizes

---

## Page Structure (Homepage)

1. **Header** — Sticky nav with logo, menu, CTA
2. **Hero** — Full-width banner with headline, subtext, CTA
3. **Stats Bar** — Key numbers (years, patients, doctors, specialties)
4. **Services** — 6-card grid showcasing medical services
5. **Doctors** — 4-card team showcase
6. **Testimonials** — Horizontal scroll carousel
7. **Booking** — Appointment form + image
8. **CTA** — Final call-to-action section
9. **Footer** — 4-column layout with links, contact, logo
