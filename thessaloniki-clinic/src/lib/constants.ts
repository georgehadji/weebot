export const SITE_CONFIG = {
  name: 'AESTHETIKON',
  tagline: 'Where Surgical Mastery Meets Quiet Elegance',
  description:
    'AESTHETIKON is Thessaloniki\'s premier destination for refined plastic surgery. We believe in results that honour your individuality — never overdone, always unmistakably you.',
  url: 'https://aesthetikon.gr',
  phone: '+30 231 099 2000',
  email: 'info@aesthetikon.gr',
  address: {
    street: 'Vasileos Georgiou 15',
    city: 'Thessaloniki',
    postal: '546 22',
    country: 'Greece',
  },
  social: {
    instagram: 'https://instagram.com/aesthetikon.gr',
    facebook: 'https://facebook.com/aesthetikon.gr',
    linkedin: 'https://linkedin.com/company/aesthetikon',
    youtube: 'https://youtube.com/@aesthetikon',
  },
  hours: {
    weekdays: '9:00 AM – 7:00 PM',
    saturday: '10:00 AM – 2:00 PM',
    sunday: 'Closed',
  },
} as const;

export const NAV_LINKS = [
  { label: 'Home', href: '#home' },
  { label: 'Procedures', href: '#procedures' },
  { label: 'About', href: '#about' },
  { label: 'Surgeon', href: '#surgeon' },
  { label: 'Results', href: '#results' },
  { label: 'Testimonials', href: '#testimonials' },
  { label: 'Contact', href: '#contact' },
] as const;

export const PROCEDURES = [
  {
    id: 'facelift',
    title: 'Deep Plane Facelift',
    subtitle: 'The Gold Standard in Facial Rejuvenation',
    description:
      'Our signature deep plane facelift repositions the deeper layers of the face for results that look natural, not pulled. This advanced technique delivers dramatic yet undetectable rejuvenation that lasts 10–15 years.',
    icon: 'facelift',
    features: ['Deep plane technique', 'Natural-looking results', '10–15 year longevity', 'Minimal scarring', 'Combined with neck lift'],
    duration: '4–6 hours',
    recovery: '2–3 weeks',
  },
  {
    id: 'rhinoplasty',
    title: 'Rhinoplasty',
    subtitle: 'Sculpting Harmony, Breathing Freely',
    description:
      'Precision rhinoplasty that balances facial aesthetics with functional breathing. Using both open and closed techniques, we craft noses that complement your unique facial architecture.',
    icon: 'rhinoplasty',
    features: ['Open & closed techniques', 'Functional & aesthetic', 'Ethnic rhinoplasty', 'Revision rhinoplasty', '3D simulation'],
    duration: '2–3 hours',
    recovery: '1–2 weeks',
  },
  {
    id: 'breast',
    title: 'Breast Surgery',
    subtitle: 'Augmentation, Reduction & Lift',
    description:
      'Comprehensive breast surgery tailored to your body proportions and aesthetic goals. From subtle augmentation to complex reconstruction, every procedure is a bespoke composition.',
    icon: 'breast',
    features: ['Augmentation', 'Mastopexy (lift)', 'Reduction', 'Fat transfer', 'Revision surgery'],
    duration: '2–4 hours',
    recovery: '1–3 weeks',
  },
  {
    id: 'body',
    title: 'Body Contouring',
    subtitle: 'Liposculpture, Tummy Tuck & Mommy Makeover',
    description:
      'Advanced body contouring that goes beyond fat removal. Our liposculpture technique sculpts with artistic precision, while abdominoplasty and mommy makeover restore your pre-pregnancy silhouette.',
    icon: 'body',
    features: ['VASER liposculpture', 'Abdominoplasty', 'Mommy makeover', 'Arm lift', 'Thigh lift'],
    duration: '2–5 hours',
    recovery: '2–4 weeks',
  },
  {
    id: 'blepharoplasty',
    title: 'Blepharoplasty',
    subtitle: 'Eyelid Rejuvenation',
    description:
      'Delicate eyelid surgery that refreshes your expression while preserving your natural character. Upper and lower blepharoplasty to restore brightness and youth to your gaze.',
    icon: 'blepharoplasty',
    features: ['Upper & lower lids', 'Transconjunctival approach', 'Fat repositioning', 'Minimal downtime', 'Local anaesthesia option'],
    duration: '1–2 hours',
    recovery: '1 week',
  },
  {
    id: 'non-surgical',
    title: 'Non-Surgical Aesthetics',
    subtitle: 'Injectables, Threads & Skin Rejuvenation',
    description:
      'A curated suite of non-surgical treatments for subtle refinement. Anti-wrinkle injections, dermal fillers, PDO threads, and advanced skin therapies — all administered with an artist\'s eye.',
    icon: 'non-surgical',
    features: ['Anti-wrinkle injections', 'Dermal fillers', 'PDO thread lift', 'PRP therapy', 'Laser rejuvenation'],
    duration: '30–60 min',
    recovery: 'Minimal',
  },
] as const;

export const SURGEON = {
  id: 'dr-chatzivantsidis',
  name: 'Dr. Georgios Chatzivantsidis',
  title: 'Plastic, Aesthetic & Reconstructive Surgeon',
  credentials: [
    'ISAPS Certified',
    'EBOPRAS Certified',
    'Member of the Hellenic Society of Plastic Surgery',
    'Member of the International Society of Aesthetic Plastic Surgery',
  ],
  bio: [
    'Dr. Georgios Chatzivantsidis is a board-certified plastic surgeon with over 15 years of experience in aesthetic and reconstructive surgery. Trained in leading centres across Europe and the United States, he founded AESTHETIKON with a singular vision: to create a clinic where surgical excellence is matched by genuine care.',
    'Known for his meticulous technique and natural aesthetic philosophy, Dr. Chatzivantsidis specialises in deep plane facelift, precision rhinoplasty, and advanced body contouring. His approach is guided by one principle — results should enhance, never erase, who you are.',
    'A committed educator and researcher, he regularly presents at international conferences and publishes in peer-reviewed journals. His work on deep plane facelift techniques has been recognised by the European Board of Plastic, Reconstructive and Aesthetic Surgery.',
  ],
  education: [
    'MD, Aristotle University of Thessaloniki',
    'MSc in Aesthetic Surgery, University of Barcelona',
    'Fellowship in Aesthetic Surgery, Harvard Medical School',
    'EBOPRAS Certification, European Board of Plastic Surgery',
  ],
  image: '/team/dr-chatzivantsidis.jpg',
} as const;

export const TESTIMONIALS = [
  {
    id: 1,
    name: 'Elena M.',
    location: 'Athens, Greece',
    rating: 5,
    text: 'Dr. Chatzivantsidis is a true artist. My deep plane facelift results are so natural that people simply say I look "rested." The entire AESTHETIKON team made me feel safe and cared for from consultation to recovery.',
    treatment: 'Deep Plane Facelift',
    date: '2025-01-15',
  },
  {
    id: 2,
    name: 'Sarah K.',
    location: 'London, UK',
    rating: 5,
    text: 'I travelled from London specifically for Dr. Chatzivantsidis after months of research. The rhinoplasty results exceeded my expectations — my nose looks like it was always meant to be this way. Worth every mile.',
    treatment: 'Rhinoplasty',
    date: '2024-11-22',
  },
  {
    id: 3,
    name: 'Maria P.',
    location: 'Thessaloniki, Greece',
    rating: 5,
    text: 'After having two children, I wanted to feel like myself again. The mommy makeover was life-changing. Dr. Chatzivantsidis listened to exactly what I wanted and delivered beautifully.',
    treatment: 'Mommy Makeover',
    date: '2025-02-08',
  },
  {
    id: 4,
    name: 'James W.',
    location: 'Munich, Germany',
    rating: 5,
    text: 'As a man considering plastic surgery, I was nervous about it looking obvious. Dr. Chatzivantsidis performed my blepharoplasty with such precision that colleagues just think I\'ve been sleeping better. Exceptional care.',
    treatment: 'Blepharoplasty',
    date: '2024-12-01',
  },
  {
    id: 5,
    name: 'Anna D.',
    location: 'Vienna, Austria',
    rating: 5,
    text: 'The non-surgical treatments at AESTHETIKON are on another level. The injectable work is so subtle and refined — I look like myself, just fresher. The clinic itself is beautiful and calming.',
    treatment: 'Non-Surgical Aesthetics',
    date: '2025-03-10',
  },
  {
    id: 6,
    name: 'Nikos T.',
    location: 'Thessaloniki, Greece',
    rating: 5,
    text: 'I brought my wife for a consultation and was impressed by the thoroughness of the process. The 3D simulation, the detailed explanation, the genuine care — this is how medicine should be practised.',
    treatment: 'Breast Augmentation',
    date: '2025-01-28',
  },
] as const;

export const STATS = [
  { value: '15+', label: 'Years of Experience' },
  { value: '3,000+', label: 'Procedures Performed' },
  { value: '98%', label: 'Patient Satisfaction' },
  { value: '4.9', label: 'Google Rating' },
] as const;

export const CERTIFICATIONS = [
  { name: 'ISAPS', description: 'International Society of Aesthetic Plastic Surgery' },
  { name: 'EBOPRAS', description: 'European Board of Plastic, Reconstructive and Aesthetic Surgery' },
  { name: 'HSPRS', description: 'Hellenic Society of Plastic, Reconstructive and Aesthetic Surgery' },
  { name: 'ISO 9001', description: 'Quality Management Certification' },
] as const;
