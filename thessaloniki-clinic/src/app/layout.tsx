import type { Metadata } from 'next';
import { Inter, Playfair_Display, Cormorant_Garamond } from 'next/font/google';
import '@/styles/globals.css';

const inter = Inter({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-inter',
});

const playfair = Playfair_Display({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-playfair',
});

const cormorant = Cormorant_Garamond({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-cormorant',
  weight: ['300', '400', '500', '600', '700'],
});

export const metadata: Metadata = {
  title: {
    default: 'AESTHETIKON | Premium Plastic Surgery Clinic, Thessaloniki',
    template: '%s | AESTHETIKON',
  },
  description:
    'AESTHETIKON is Thessaloniki\'s premier destination for refined plastic surgery. Experience artistry, precision, and care that respects your individuality. ISAPS & EBOPRAS certified surgeons.',
  keywords: [
    'plastic surgery thessaloniki',
    'cosmetic surgery greece',
    'facelift thessaloniki',
    'rhinoplasty thessaloniki',
    'breast augmentation greece',
    'liposculpture thessaloniki',
    'aesthetic surgery thessaloniki',
    'plastic surgeon thessaloniki',
    'mommy makeover greece',
    'deep plane faceliki',
    'blepharoplasty thessaloniki',
    'abdominoplasty greece',
    'medical tourism greece',
    'ISAPS certified surgeon',
    'EBOPRAS certified',
  ],
  authors: [{ name: 'AESTHETIKON Plastic Surgery Clinic' }],
  creator: 'AESTHETIKON',
  openGraph: {
    type: 'website',
    locale: 'en_GR',
    alternateLocale: 'el_GR',
    url: 'https://aesthetikon.gr',
    siteName: 'AESTHETIKON',
    title: 'AESTHETIKON | Premium Plastic Surgery Clinic, Thessaloniki',
    description:
      'Where surgical mastery meets quiet elegance. Thessaloniki\'s premier destination for refined plastic surgery.',
    images: [
      {
        url: '/og-image.jpg',
        width: 1200,
        height: 630,
        alt: 'AESTHETIKON Plastic Surgery Clinic, Thessaloniki',
      },
    ],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'AESTHETIKON | Premium Plastic Surgery Clinic, Thessaloniki',
    description:
      'Where surgical mastery meets quiet elegance. Thessaloniki\'s premier destination for refined plastic surgery.',
    images: ['/og-image.jpg'],
  },
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      'max-video-preview': -1,
      'max-image-preview': 'large',
      'max-snippet': -1,
    },
  },
  icons: {
    icon: '/favicon.ico',
    apple: '/apple-touch-icon.png',
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${inter.variable} ${playfair.variable} ${cormorant.variable} scroll-smooth`}>
      <body className="font-sans antialiased bg-ivory-50 text-charcoal-600">
        {children}
      </body>
    </html>
  );
}
