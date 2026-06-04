import type { Metadata } from "next";
import { Inter, Playfair_Display } from "next/font/google";
import "./globals.css";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin", "greek"],
});

const playfair = Playfair_Display({
  variable: "--font-playfair",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: {
    default: "Dr. Jorgis Chatzivantsidis | Plastic Surgeon Thessaloniki",
    template: "%s | Dr. Chatzivantsidis Plastic Surgery",
  },
  description:
    "Board-certified plastic surgeon in Thessaloniki, Greece. Dr. Jorgis Chatzivantsidis offers rhinoplasty, facelift, breast augmentation, liposuction, and more. Schedule your consultation today.",
  keywords: [
    "plastic surgeon",
    "Thessaloniki",
    "rhinoplasty",
    "facelift",
    "breast augmentation",
    "liposuction",
    "cosmetic surgery",
    "aesthetic medicine",
    "Greece",
  ],
  openGraph: {
    type: "website",
    locale: "en_GR",
    alternateLocale: "el_GR",
    siteName: "Dr. Chatzivantsidis Plastic Surgery",
    title: "Dr. Jorgis Chatzivantsidis | Plastic Surgeon Thessaloniki",
    description:
      "Board-certified plastic surgeon in Thessaloniki, Greece. Combining artistry with surgical precision.",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="scroll-smooth">
      <body
        className={`${inter.variable} ${playfair.variable} font-sans antialiased bg-white text-neutral-900`}
      >
        {children}
      </body>
    </html>
  );
}
