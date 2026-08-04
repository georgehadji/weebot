"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Bot, Plus, Settings, Bug, Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useTheme } from "@/providers/ThemeProvider";

const navLinks = [
  { href: "/sessions", label: "Sessions" },
  { href: "/ops", label: "Ops" },
  { href: "/models", label: "Models" },
  { href: "/behavior", label: "Behavior" },
];

export function Header() {
  const pathname = usePathname();
  const { theme, toggleTheme } = useTheme();

  return (
    <header className="border-b bg-background sticky top-0 z-40">
      <div className="flex h-16 items-center px-4 gap-4">
        <Link href="/" className="flex items-center gap-2 font-bold text-xl shrink-0">
          <Bot className="h-6 w-6" />
          <span>Weebot</span>
        </Link>

        <nav className="flex items-center gap-1 ml-6">
          {navLinks.map(({ href, label }) => (
            <Link
              key={href}
              href={href}
              className={cn(
                "px-3 py-1.5 rounded-md text-sm font-medium transition-colors",
                pathname?.startsWith(href)
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground hover:text-foreground hover:bg-accent/50"
              )}
            >
              {label}
            </Link>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-2">
          <Link href="/">
            <Button variant="outline" size="sm">
              <Plus className="h-4 w-4 mr-1" />
              New Session
            </Button>
          </Link>
          <Button
            variant="ghost"
            size="icon"
            aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
            title={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
            onClick={toggleTheme}
          >
            {theme === "dark" ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
          </Button>
          {process.env.NODE_ENV !== "production" && (
            <Link href="/debug">
              <Button variant="ghost" size="icon" aria-label="WebSocket debug" title="WebSocket Debug">
                <Bug className="h-5 w-5" />
              </Button>
            </Link>
          )}
          <Link href="/settings">
            <Button variant="ghost" size="icon" aria-label="Settings" title="Settings">
              <Settings className="h-5 w-5" />
            </Button>
          </Link>
        </div>
      </div>
    </header>
  );
}
