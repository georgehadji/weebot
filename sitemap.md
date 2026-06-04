# 🦷 Thessaloniki Dental Practice — Sitemap

## Site Architecture Overview

```
🏠 HOME
│
├── ℹ️ ABOUT
│   ├── Our Practice / Story
│   ├── Our Philosophy
│   ├── Technology & Equipment
│   └── Virtual Tour (360°)
│
├── 🦷 SERVICES
│   ├── General Dentistry
│   ├── Cosmetic Dentistry
│   ├── Orthodontics
│   ├── Dental Implants
│   ├── Oral Surgery
│   ├── Pediatric Dentistry
│   ├── Prosthodontics
│   └── Emergency Dentistry
│
├── 👥 TEAM
│   ├── Lead Dentist(s)
│   ├── Specialists
│   └── Support Staff
│
├── 🖼️ GALLERY / BEFORE & AFTER
│   ├── Smile Gallery
│   ├── Clinic Interior
│   └── Patient Stories (Video)
│
├── 📋 PATIENT INFO
│   ├── New Patients (Forms)
│   ├── Insurance & Payment
│   ├── FAQs
│   └── Patient Resources (Post-Op Care)
│
├── 📰 BLOG / NEWS
│   ├── Dental Health Tips
│   ├── Technology Updates
│   ├── Patient Stories
│   └── Category Filters
│
├── 📞 CONTACT
│   ├── Location & Map
│   ├── Contact Form
│   ├── Phone / Email / WhatsApp
│   └── Hours & Directions
│
└── 📅 BOOK APPOINTMENT (CTA — Global)
    ├── Online Booking Form
    ├── Phone Booking
    └── WhatsApp Booking
```

---

## Navigation Structure

### Primary Navigation (Header)
| # | Label (EN) | Label (EL) | URL |
|---|-----------|-----------|-----|
| 1 | Home | Αρχική | `/` |
| 2 | About | Σχετικά | `/about` |
| 3 | Services | Υπηρεσίες | `/services` |
| 4 | Team | Ομάδα | `/team` |
| 5 | Patient Info | Πληροφορίες | `/patient-info` |
| 6 | Blog | Άρθρα | `/blog` |
| 7 | Contact | Επικοινωνία | `/contact` |
| — | **Book Now** (CTA) | **Κλείστε Ραντεβού** | `/book` |

### Secondary Navigation (Header Top Bar)
- 📞 Phone number
- 📧 Email
- 📍 Address (short)
- 🌐 Language Toggle (EN | ΕΛ)
- 📅 Book Appointment button

### Footer Navigation
- Quick Links (all primary pages)
- Services (all 8 categories)
- Contact Info (full)
- Social Media Icons (Facebook, Instagram, Google, YouTube)
- Legal (Privacy Policy, Terms, Cookie Policy — GDPR)
- Powered by / Copyright

---

## Page-by-Page Content Hierarchy

### 1. HOME (`/`)
**Purpose:** First impression, trust-building, conversion to appointment

| Section | Content | Priority |
|---------|---------|----------|
| Hero | Full-width image/video, H1 headline, dual CTAs (Book Now + Call), language-aware | Critical |
| Trust Bar | Years of experience, patients served, Google rating, certifications | High |
| Services Overview | 8 service cards with icons, short descriptions, links to detail pages | Critical |
| About Preview | Brief intro + photo + link to About page | High |
| Team Preview | 2-3 team member cards with photos + specialties | Medium |
| Testimonials | Carousel of patient reviews (Google/Yelp) | High |
| Before & After | 3-4 gallery items with slider | Medium |
| Blog Preview | Latest 3 posts with thumbnails | Low |
| CTA Banner | "Book Your Visit Today" with form/button | Critical |
| Contact Strip | Map preview, address, phone, hours | High |

---

### 2. ABOUT (`/about`)
**Purpose:** Build trust and connection

| Section | Content |
|---------|---------|
| Hero Banner | Page title + breadcrumb |
| Our Story | Practice history, founder story, mission |
| Our Philosophy | Patient-first approach, pain-free commitment |
| Technology | Equipment list (CBCT, digital X-ray, CAD/CAM, laser) with images |
| Certifications | Memberships (Hellenic Dental Federation, European associations) |
| Virtual Tour | 360° embedded tour or video walkthrough |
| CTA | Book appointment |

---

### 3. SERVICES (`/services`)
**Purpose:** Detail all treatments, educate patients, SEO landing pages

**Listing Page:**
| Section | Content |
|---------|---------|
| Hero Banner | Page title + intro paragraph |
| Service Grid | 8 cards → each links to individual service page |
| CTA | "Not sure what you need? Book a consultation" |

**Individual Service Pages** (×8) — e.g., `/services/dental-implants`:
| Section | Content |
|---------|---------|
| Hero | Service name, short tagline, CTA |
| Overview | What is this treatment? |
| Procedure | Step-by-step process |
| Benefits | Why choose this treatment |
| Technology Used | Specific equipment/techniques |
| Before & After | Relevant gallery items |
| Pricing / From €XXX | Transparent pricing or "from" price |
| FAQs | 5-8 accordion FAQs |
| Related Services | Links to 2-3 related services |
| CTA | Book consultation |

---

### 4. TEAM (`/team`)
**Purpose:** Humanize the practice, showcase expertise

| Section | Content |
|---------|---------|
| Hero Banner | "Meet Our Team" |
| Lead Dentist(s) | Large photo, full bio, education, specialties, languages |
| Specialists | Cards per specialist (orthodontist, surgeon, pediatric, etc.) |
| Support Staff | Hygienists, assistants, reception (optional) |
| Certifications & Memberships | Logos/badges |
| CTA | Book with a specific doctor |

---

### 5. GALLERY (`/gallery`)
**Purpose:** Visual proof of quality

| Section | Content |
|---------|---------|
| Filter Tabs | Smile Gallery / Clinic / Patient Stories |
| Before & After Grid | Lightbox-enabled comparison sliders |
| Clinic Interior | Professional photos of facilities |
| Video Testimonials | Embedded YouTube/Vimeo |
| CTA | "Start Your Smile Journey" |

---

### 6. PATIENT INFO (`/patient-info`)
**Purpose:** Reduce friction for new patients

| Section | Content |
|---------|---------|
| New Patients Welcome | What to expect on first visit |
| Downloadable Forms | PDF forms (Greek + English) |
| Insurance | Accepted insurance plans, payment methods |
| Payment Options | Cash, card, installments |
| FAQs | Accordion-style, 15-20 questions |
| Post-Op Care | Downloadable guides per procedure |
| CTA | Book first appointment |

---

### 7. BLOG (`/blog`)
**Purpose:** SEO, education, authority building

| Section | Content |
|---------|---------|
| Featured Post | Large hero article |
| Category Filters | All / Tips / Technology / News / Patient Stories |
| Post Grid | Cards with thumbnail, title, excerpt, date, author |
| Sidebar | Search, categories, popular posts, newsletter signup |
| Individual Post | Title, author, date, content, share buttons, related posts, comments |

---

### 8. CONTACT (`/contact`)
**Purpose:** Easy communication

| Section | Content |
|---------|---------|
| Contact Form | Name, email, phone, service dropdown, message, GDPR consent |
| Map | Google Maps embed (Thessaloniki location) |
| Address | Full address with "Get Directions" link |
| Phone | Click-to-call, WhatsApp link |
| Email | Click-to-email |
| Hours | Mon-Sat schedule |
| Parking / Transit | Nearby parking, bus/metro info |
| CTA | Book online instead |

---

### 9. BOOK APPOINTMENT (`/book`)
**Purpose:** Conversion — the most important page

| Section | Content |
|---------|---------|
| Online Booking Form | Name, email, phone, service, preferred doctor, date, time, notes |
| Calendar Widget | Real-time availability |
| Confirmation | Auto-confirmation message + email |
| Alternative Booking | Phone number, WhatsApp button |
| What to Expect | Brief reassurance text |

---

## URL Structure (SEO-Friendly)

```
/                          → Home
/about                     → About
/services                  → Services listing
/services/general          → General Dentistry
/services/cosmetic         → Cosmetic Dentistry
/services/orthodontics     → Orthodontics
/services/implants         → Dental Implants
/services/surgery          → Oral Surgery
/services/pediatric        → Pediatric Dentistry
/services/prosthodontics   → Prosthodontics
/services/emergency        → Emergency Dentistry
/team                      → Team
/gallery                   → Gallery
/patient-info              → Patient Info
/patient-info/forms        → Forms
/patient-info/faq          → FAQ
/patient-info/insurance    → Insurance & Payment
/blog                      → Blog listing
/blog/:slug                → Individual post
/contact                   → Contact
/book                      → Book Appointment
/privacy                   → Privacy Policy
/terms                     → Terms of Service
/cookies                   → Cookie Policy
```

---

## Multilingual URL Strategy

| Language | URL Pattern | Example |
|----------|------------|---------|
| English (default) | `/` | `/services/implants` |
| Greek | `/el/` | `/el/services/implants` |

Language toggle persists via cookie/localStorage. All content managed bilingually in CMS.
