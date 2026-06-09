# Services Section Specification

## Overview
The Services section showcases Athens Pro Plumbing’s core offerings in a visually clean, responsive grid of service cards. Each card highlights a key service with an icon placeholder, title, and short description.

## Background
- **Section background**: `#E6F0FA` (light blue)
- **Section padding**: `80px 0` (vertical), responsive horizontal padding

## Layout
- **Grid system**: CSS Grid
- **Desktop (≥1024px)**: 4 columns, `24px` gap
- **Tablet (768px – 1023px)**: 2 columns, `20px` gap
- **Mobile (<768px)**: 1 column, `16px` gap
- **Container max-width**: `1200px`, centered with auto margins

## Service Cards (×4)

### Card Design
- **Background**: `#FFFFFF` (white)
- **Border-radius**: `12px`
- **Padding**: `32px`
- **Shadow**: `0 4px 16px rgba(0, 53, 102, 0.08)`
- **Hover shadow**: `0 8px 24px rgba(0, 53, 102, 0.14)`
- **Transition**: `box-shadow 0.3s ease, transform 0.3s ease`
- **Hover transform**: `translateY(-4px)`

### Card Content Structure
```
[Icon Placeholder]
[Service Title]
[Short Description]
```

### 1. Emergency Repairs
- **Icon placeholder**: SVG placeholder, `48px × 48px`, color `#003566` (Greek blue)
- **Title**: "Emergency Repairs"
- **Description**: "24/7 rapid response for burst pipes, leaks, and urgent plumbing failures. We’re on call day and night."

### 2. Drain Cleaning
- **Icon placeholder**: SVG placeholder, `48px × 48px`, color `#003566`
- **Title**: "Drain Cleaning"
- **Description**: "Clear stubborn clogs and prevent backups with professional hydro-jetting and snaking services."

### 3. Pipe Installation
- **Icon placeholder**: SVG placeholder, `48px × 48px`, color `#003566`
- **Title**: "Pipe Installation"
- **Description**: "Expert copper, PEX, and PVC pipe fitting for renovations, new builds, and full repiping projects."

### 4. Water Heater Service
- **Icon placeholder**: SVG placeholder, `48px × 48px`, color `#003566`
- **Title**: "Water Heater Service"
- **Description**: "Installation, repair, and maintenance of tankless and traditional water heaters for reliable hot water."

## Typography
- **Section title** (above grid): `"Our Services"`, `32px`, font-weight `700`, color `#003566`, centered
- **Card title**: `20px`, font-weight `600`, color `#001D3D`, margin-top `16px`
- **Card description**: `15px`, font-weight `400`, color `#4A5568`, line-height `1.6`, margin-top `8px`

## Icon Placeholders
- Use inline SVG placeholders for each service
- Example placeholder pattern (wrench icon):
  ```html
  <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#003566" stroke-width="2">
    <!-- icon paths -->
  </svg>
  ```
- Actual SVG paths can be swapped in during implementation

## Responsive Behavior
- Cards stack vertically on mobile with full-width layout
- Maintain `16px` side padding on mobile container
- Reduce card padding to `24px` on mobile if needed

## Accessibility
- Cards should be keyboard-focusable (`tabindex="0"` or wrapped in semantic elements)
- Icon + title group should have appropriate `aria-label` if interactive
- Ensure color contrast meets WCAG AA (dark text on white cards, blue text on light blue background)
