import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { Header } from "@/components/layout/Header";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ThemeProvider } from "@/providers/ThemeProvider";
import { ToastProvider } from "@/providers/ToastProvider";
import { EventStreamProvider } from "@/providers/EventStreamProvider";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const jetbrainsMono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-jetbrains-mono" });

export const metadata: Metadata = {
  title: "Weebot - Mission Center",
  description: "Real-time operations console for the Weebot agent framework",
};

// Applied before hydration so the stored theme paints on first frame —
// avoids a flash of the wrong theme (ThemeProvider syncs the class again on mount).
const THEME_INIT_SCRIPT = `(function(){try{var t=localStorage.getItem("weebot_theme");if(t!=="light"){document.documentElement.classList.add("dark");document.documentElement.setAttribute("data-theme","dark");}else{document.documentElement.setAttribute("data-theme","light");}}catch(e){document.documentElement.classList.add("dark");}})();`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className={`${inter.variable} ${jetbrainsMono.variable} font-sans`}>
        <ThemeProvider>
          <ToastProvider>
            <EventStreamProvider>
              <TooltipProvider>
                <div className="min-h-screen flex flex-col">
                  <Header />
                  <main className="flex-1">{children}</main>
                </div>
              </TooltipProvider>
            </EventStreamProvider>
          </ToastProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
