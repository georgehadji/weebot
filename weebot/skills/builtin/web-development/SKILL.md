---
name: web-development
description: Build and deploy websites, SPAs, and full-stack apps. Covers HTML/CSS/JS, React/Next.js, Tailwind, shadcn/ui, responsive design, accessibility, SEO, and deployment. Triggered for any website creation, frontend development, landing page, or web app task.
metadata:
  emoji: 🌐
  trust: trusted
  provenance:
    origin: human
  requires_toolsets: []
  fallback_for_toolsets: []
---

# Web Development

## Project Types

| Type | Approach | Tools |
|---|---|---|
| Static landing page | Single `index.html` with embedded CSS/JS | HTML5, CSS3, vanilla JS |
| Framework app | Scaffold with CLI → build components | Next.js, Vite, React |
| 3D/motion site | Use approved stack: R3F, GSAP, Spline | See `<web_3d_motion>` in core rules |

## CSS Framework Priority

1. **Tailwind CSS** — utility-first, CDN: `<script src="https://cdn.tailwindcss.com">`
2. **shadcn/ui** — when building React/Next.js apps: `npx shadcn-ui@latest init`
3. **Plain CSS** — for single-file pages under 300 lines

## Responsive Design Rules

- Mobile-first: design at 375px, scale up
- Breakpoints: `sm:640px md:768px lg:1024px xl:1280px`
- Use `max-width: 100%` on images, `flex-wrap` on card grids
- Test layout at 3 widths: mobile (375), tablet (768), desktop (1280)

## Accessibility Checklist

- All images have `alt` text
- Form inputs have `<label>` elements
- Color contrast ≥ 4.5:1 for normal text
- Page has exactly one `<h1>`
- Interactive elements are keyboard-accessible
- `aria-label` on icon-only buttons

## SEO Meta Tags

```html
<meta name="description" content="...">
<meta property="og:title" content="...">
<meta property="og:description" content="...">
<meta property="og:image" content="...">
<meta name="twitter:card" content="summary_large_image">
<script type="application/ld+json">
{ "@context": "https://schema.org", "@type": "WebSite", ... }
</script>
```

## Performance Rules

- Images: WebP format, lazy loading (`loading="lazy"`), explicit width/height
- CSS: avoid `@import`, use `<link>`, minimize render-blocking
- JS: defer non-critical scripts (`defer` attribute)
- Fonts: `font-display: swap`, subset to needed characters
- No jQuery — use vanilla JS or framework utilities

## Website Standards (MANDATORY)
Every website you build or generate MUST comply with the following — no exceptions:

1. **Mobile-First**: Design and code for the smallest screen first, then progressively enhance for larger viewports. Use `min-width` media queries, not `max-width`.
2. **Fully Responsive**: Layouts must adapt fluidly across all screen sizes (320px → 1920px+). No horizontal overflow, no fixed-width containers that break on small screens.
3. **Web Standards & Best Practices**, including but not limited to:
   - **Semantic HTML**: Use correct elements (`<header>`, `<nav>`, `<main>`, `<section>`, `<article>`, `<footer>`, etc.) rather than generic `<div>` stacks.
   - **Accessibility (WCAG 2.1 AA)**: Proper alt text, ARIA labels where needed, keyboard navigability, sufficient color contrast (4.5:1 for text).
   - **Performance**: Images with explicit dimensions and `loading="lazy"`, minimal render-blocking resources, optimized assets.
   - **Valid HTML/CSS**: Markup must pass W3C validation. No deprecated elements or attributes.
   - **Meta & SEO**: `<meta charset>`, `<meta name="viewport" content="width=device-width, initial-scale=1">`, descriptive `<title>`, `<meta name="description">`.
   - **Security headers**: CSP, `X-Content-Type-Options`, `X-Frame-Options` where applicable.
   - **No inline styles or scripts** unless absolutely unavoidable; prefer external stylesheets and scripts.

## Output Convention

All websites go under `Output/<project-name>/`. Single-file projects: `Output/<name>/index.html`.
