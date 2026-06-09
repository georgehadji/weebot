# Schema.org Structured Data Templates

## Organization
Required: name, url.  Recommended: logo, sameAs, description.
```json
{
  "@context": "https://schema.org",
  "@type": "Organization",
  "name": "Company Name",
  "url": "https://example.com",
  "logo": "https://example.com/logo.png",
  "description": "Brief description of the organization.",
  "sameAs": [
    "https://twitter.com/example",
    "https://linkedin.com/company/example",
    "https://github.com/example"
  ]
}
```

## Person
```json
{
  "@context": "https://schema.org",
  "@type": "Person",
  "name": "Full Name",
  "url": "https://example.com/about",
  "jobTitle": "Role",
  "sameAs": ["https://twitter.com/handle", "https://linkedin.com/in/handle"]
}
```

## WebSite (for Sitelinks Searchbox)
```json
{
  "@context": "https://schema.org",
  "@type": "WebSite",
  "name": "Site Name",
  "url": "https://example.com",
  "potentialAction": {
    "@type": "SearchAction",
    "target": "https://example.com/search?q={search_term_string}",
    "query-input": "required name=search_term_string"
  }
}
```

## Article / BlogPosting
```json
{
  "@context": "https://schema.org",
  "@type": "Article",
  "headline": "Article Title (matching <title>)",
  "author": {"@type": "Person", "name": "Author Name"},
  "datePublished": "2025-01-15T09:00:00+00:00",
  "dateModified": "2025-01-20T14:30:00+00:00",
  "image": "https://example.com/images/article-hero.jpg",
  "description": "150-character description matching meta description.",
  "publisher": {"@type": "Organization", "name": "Publisher", "logo": {"@type": "ImageObject", "url": "https://example.com/logo.png"}}
}
```

## FAQPage
```json
{
  "@context": "https://schema.org",
  "@type": "FAQPage",
  "mainEntity": [
    {
      "@type": "Question",
      "name": "What is the refund policy?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "Refunds are processed within 30 days of purchase."
      }
    }
  ]
}
```

## BreadcrumbList
```json
{
  "@context": "https://schema.org",
  "@type": "BreadcrumbList",
  "itemListElement": [
    {"@type": "ListItem", "position": 1, "name": "Home", "item": "https://example.com"},
    {"@type": "ListItem", "position": 2, "name": "Blog", "item": "https://example.com/blog"},
    {"@type": "ListItem", "position": 3, "name": "Post Title"}
  ]
}
```

## Product
```json
{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": "Product Name",
  "description": "Product description.",
  "image": "https://example.com/product.jpg",
  "sku": "SKU123",
  "brand": {"@type": "Brand", "name": "Brand Name"},
  "offers": {
    "@type": "Offer",
    "price": "29.99",
    "priceCurrency": "USD",
    "availability": "https://schema.org/InStock",
    "url": "https://example.com/product"
  }
}
```

## LocalBusiness
```json
{
  "@context": "https://schema.org",
  "@type": "LocalBusiness",
  "name": "Business Name",
  "address": {
    "@type": "PostalAddress",
    "streetAddress": "123 Main St",
    "addressLocality": "City",
    "addressRegion": "State",
    "postalCode": "12345",
    "addressCountry": "US"
  },
  "telephone": "+1-555-555-5555",
  "url": "https://example.com",
  "openingHours": ["Mo-Fr 09:00-17:00"],
  "geo": {"@type": "GeoCoordinates", "latitude": 40.7128, "longitude": -74.0060}
}
```

## Event
```json
{
  "@context": "https://schema.org",
  "@type": "Event",
  "name": "Event Name",
  "startDate": "2025-09-14T19:00:00",
  "location": {"@type": "Place", "name": "Venue Name", "address": "..."},
  "description": "Event description.",
  "offers": {"@type": "Offer", "url": "https://example.com/tickets", "price": "0", "priceCurrency": "USD", "availability": "https://schema.org/InStock"}
}
```
