# Modern Pricing Cards CSS Framework

A comprehensive CSS framework for creating beautiful, responsive pricing cards with feature lists and call-to-action buttons. Built with modern design trends including glassmorphism, gradients, and smooth animations.

## Features

- 🎨 **Modern Design**: Clean, professional styling with gradients and shadows
- 📱 **Fully Responsive**: Works on all screen sizes
- 🌙 **Dark Mode Support**: Automatic dark/light theme detection
- ⚡ **Performance Optimized**: Minimal CSS with maximum impact
- 🎯 **Accessibility**: Proper contrast ratios and focus states
- 🎪 **Animations**: Smooth hover effects and entrance animations

## Installation

1. Include the CSS file in your HTML:
```html
<link rel="stylesheet" href="pricing-styles.css">
```

2. Add the HTML structure (see examples below)

## Basic Usage

### HTML Structure

```html
<section class="pricing-section">
    <div class="pricing-header">
        <h1>Choose Your Plan</h1>
        <p>Find the perfect plan for your needs</p>
    </div>
    
    <div class="pricing-cards">
        <div class="pricing-card">
            <div class="card-header">
                <h3>Basic</h3>
                <div class="price">$19<span>/month</span></div>
                <p class="description">Perfect for small projects</p>
            </div>
            
            <div class="feature-list">
                <div class="feature-item">
                    <div class="feature-icon">✓</div>
                    <span class="feature-text">5 projects</span>
                </div>
                <div class="feature-item">
                    <div class="feature-icon">✓</div>
                    <span class="feature-text">Basic support</span>
                </div>
                <div class="feature-item disabled">
                    <div class="feature-icon">✗</div>
                    <span class="feature-text">Advanced analytics</span>
                </div>
            </div>
            
            <a href="#" class="cta-button cta-primary">Get Started</a>
        </div>
        
        <div class="pricing-card popular">
            <div class="popular-badge">Most Popular</div>
            <div class="card-header">
                <h3>Pro</h3>
                <div class="price">$49<span>/month</span></div>
                <p class="description">For growing businesses</p>
            </div>
            
            <div class="feature-list">
                <div class="feature-item">
                    <div class="feature-icon">✓</div>
                    <span class="feature-text">Unlimited projects</span>
                </div>
                <div class="feature-item">
                    <div class="feature-icon">✓</div>
                    <span class="feature-text">Priority support</span>
                </div>
                <div class="feature-item">
                    <div class="feature-icon">✓</div>
                    <span class="feature-text">Advanced analytics</span>
                </div>
            </div>
            
            <a href="#" class="cta-button cta-primary">Get Started</a>
        </div>
        
        <div class="pricing-card glass">
            <div class="card-header">
                <h3>Enterprise</h3>
                <div class="price">$99<span>/month</span></div>
                <p class="description">For large organizations</p>
            </div>
            
            <div class="feature-list">
                <div class="feature-item">
                    <div class="feature-icon">✓</div>
                    <span class="feature-text">Everything in Pro</span>
                </div>
                <div class="feature-item">
                    <div class="feature-icon">✓</div>
                    <span class="feature-text">Custom integrations</span>
                </div>
                <div class="feature-item">
                    <div class="feature-icon">✓</div>
                    <span class="feature-text">Dedicated account manager</span>
                </div>
            </div>
            
            <a href="#" class="cta-button cta-primary">Contact Sales</a>
        </div>
    </div>
</section>
```

## Components

### Pricing Card Types

1. **Standard Card**: `.pricing-card` - Basic card with clean styling
2. **Popular Card**: Add `.popular` class for highlighted plan (adds badge and accent colors)
3. **Glassmorphism**: Add `.glass` class for frosted glass effect

### Feature List

- Use `.feature-item` for each feature
- Add `.disabled` class for unavailable features (grayed out)
- Custom icons via CSS or SVG in `.feature-icon`

### Call-to-Action Buttons

- `.cta-primary` - Primary gradient button
- `.cta-secondary` - Outline button
- `.cta-ghost` - Minimal ghost button

## Customization

The CSS uses CSS custom properties for easy theming:

```css
:root {
    --primary-color: #6366f1;
    --secondary-color: #8b5cf6;
    --accent-color: #ec4899;
    --text-primary: #1f2937;
    --text-secondary: #6b7280;
    --bg-primary: #ffffff;
    --bg-secondary: #f8fafc;
    --border-color: #e5e7eb;
    --shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.1);
}

/* Dark mode */
@media (prefers-color-scheme: dark) {
    :root {
        --text-primary: #f9fafb;
        --text-secondary: #d1d5db;
        --bg-primary: #111827;
        --bg-secondary: #1f2937;
        --border-color: #374151;
        --shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3);
    }
}
```

## Browser Support

- Chrome 88+
- Firefox 85+
- Safari 14+
- Edge 88+

## License

MIT License - feel free to use in personal and commercial projects.