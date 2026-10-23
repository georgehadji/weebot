"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Bot, Plus, Settings, Bug, Menu, Moon, Sun, X } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
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
      <div className="flex h-16 items-center gap-2 px-3 sm:gap-4 sm:px-4">
        <Link href="/" className="flex shrink-0 items-center gap-2 text-lg font-bold sm:text-xl">
          <Bot className="h-6 w-6" />
          <span className="hidden sm:inline">Weebot</span>
        </Link>

        <nav className="ml-6 hidden items-center gap-1 md:flex" aria-label="Primary navigation">
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

        <div className="ml-auto flex items-center gap-1 sm:gap-2">
          <Link
            href="/"
            className={cn(buttonVariants({ variant: "outline", size: "sm" }), "gap-1")}
            aria-label="New conversation"
          >
            <Plus className="h-4 w-4" />
            <span className="hidden sm:inline">New Session</span>
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
            <Link
              href="/debug"
              className={buttonVariants({ variant: "ghost", size: "icon" })}
              aria-label="WebSocket debug"
              title="WebSocket Debug"
            >
              <Bug className="h-5 w-5" />
            </Link>
          )}
          <Link
            href="/settings"
            className={buttonVariants({ variant: "ghost", size: "icon" })}
            aria-label="Settings"
            title="Settings"
          >
            <Settings className="h-5 w-5" />
          </Link>
          <details className="relative md:hidden">
            <summary
              className={cn(buttonVariants({ variant: "ghost", size: "icon" }), "list-none [&::-webkit-details-marker]:hidden")}
              aria-label="Open navigation menu"
            >
              <Menu className="h-5 w-5 [[open]_&]:hidden" />
              <X className="hidden h-5 w-5 [[open]_&]:block" />
            </summary>
            <nav
              className="absolute right-0 top-12 z-50 flex w-48 flex-col rounded-md border bg-popover p-1 shadow-lg"
              aria-label="Mobile navigation"
            >
              {navLinks.map(({ href, label }) => (
                <Link
                  key={href}
                  href={href}
                  className={cn(
                    "rounded-md px-3 py-2 text-sm font-medium transition-colors",
                    pathname?.startsWith(href)
                      ? "bg-accent text-accent-foreground"
                      : "text-muted-foreground hover:bg-accent hover:text-foreground"
                  )}
                >
                  {label}
                </Link>
              ))}
            </nav>
          </details>
        </div>
      </div>
    </header>
  );
}
