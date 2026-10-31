"use client";

/**
 * AppBar — the one 48 px header: brand, primary navigation, the page's title and connection
 * state (slots filled by `useShellSlots`), and the global actions. Below `md` the navigation
 * and actions move into a dialog behind a menu button.
 */

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Bot, Bug, Command, Menu, Moon, Plus, Settings, Sun } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { useShell } from "@/providers/ShellProvider";
import { useTheme } from "@/providers/ThemeProvider";

const NAV_LINKS = [
  { href: "/sessions", label: "Sessions" },
  { href: "/ops", label: "Ops" },
  { href: "/models", label: "Models" },
  { href: "/behavior", label: "Behavior" },
];

const SHOW_DEBUG = process.env.NODE_ENV !== "production";

export function AppBar() {
  const pathname = usePathname();
  const { theme, toggleTheme } = useTheme();
  const { slots, setPaletteOpen } = useShell();
  // Open "at" a path, so navigating (a link in the menu) closes it without an effect.
  const [menuPath, setMenuPath] = useState<string | null>(null);
  const menuOpen = menuPath === pathname;
  const themeLabel = theme === "dark" ? "Switch to light theme" : "Switch to dark theme";

  return (
    <header className="flex h-topbar shrink-0 items-center gap-2 border-b bg-background px-3">
      <Link href="/" className="flex shrink-0 items-center gap-2 text-base font-bold">
        <Bot className="h-5 w-5" aria-hidden="true" />
        <span>Weebot</span>
      </Link>

      <nav aria-label="Primary" className="ml-4 hidden items-center gap-1 lg:flex">
        {NAV_LINKS.map(({ href, label }) => (
          <NavLink key={href} href={href} label={label} active={pathname?.startsWith(href)} />
        ))}
      </nav>

      {slots.title && (
        <h1 className="ml-2 min-w-0 flex-1 truncate border-l pl-3 text-sm font-medium">{slots.title}</h1>
      )}

      <div className="ml-auto flex shrink-0 items-center gap-1.5">
        {slots.isConnected !== undefined && (
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <span
              aria-hidden="true"
              className={cn(
                "h-1.5 w-1.5 rounded-full",
                slots.isConnected ? "bg-status-live animate-pulse" : "bg-status-idle"
              )}
            />
            {slots.isConnected ? "Live" : "Offline"}
          </span>
        )}

        <Button
          variant="outline"
          size="sm"
          onClick={() => setPaletteOpen(true)}
          aria-label="Open command palette"
          className="gap-1"
        >
          <Command className="h-3.5 w-3.5" aria-hidden="true" />
          <span className="hidden sm:inline">K</span>
        </Button>

        <div className="hidden items-center gap-1.5 lg:flex">
          <Link href="/" className={buttonVariants({ variant: "outline", size: "sm" })}>
            <Plus className="h-4 w-4" aria-hidden="true" />
            New session
          </Link>
          <Button variant="ghost" size="icon-sm" aria-label={themeLabel} title={themeLabel} onClick={toggleTheme}>
            {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </Button>
          {SHOW_DEBUG && (
            <Link href="/debug" aria-label="WebSocket debug" title="WebSocket debug" className={buttonVariants({ variant: "ghost", size: "icon-sm" })}>
              <Bug className="h-4 w-4" aria-hidden="true" />
            </Link>
          )}
          <Link href="/settings" aria-label="Settings" title="Settings" className={buttonVariants({ variant: "ghost", size: "icon-sm" })}>
            <Settings className="h-4 w-4" aria-hidden="true" />
          </Link>
        </div>

        <Button
          variant="ghost"
          size="icon-sm"
          className="lg:hidden"
          aria-label="Open menu"
          aria-haspopup="dialog"
          onClick={() => setMenuPath(pathname)}
        >
          <Menu className="h-4 w-4" />
        </Button>
      </div>

      <Dialog open={menuOpen} onOpenChange={(open) => setMenuPath(open ? pathname : null)}>
        {/* A link to the page the operator is already on does not change the path, so close on click. */}
        <DialogContent
          className="top-16 -translate-y-0 gap-3 sm:max-w-sm"
          onClick={(e) => (e.target as Element).closest("a") && setMenuPath(null)}
        >
          <DialogTitle>Menu</DialogTitle>
          <nav aria-label="Primary" className="flex flex-col gap-1">
            {NAV_LINKS.map(({ href, label }) => (
              <NavLink key={href} href={href} label={label} active={pathname?.startsWith(href)} block />
            ))}
          </nav>
          <div className="flex flex-col gap-1 border-t pt-3">
            <Link href="/" className={buttonVariants({ variant: "outline" })}>
              <Plus className="h-4 w-4" aria-hidden="true" />
              New session
            </Link>
            <Link href="/settings" className={buttonVariants({ variant: "ghost" })}>
              <Settings className="h-4 w-4" aria-hidden="true" />
              Settings
            </Link>
            <Button variant="ghost" onClick={toggleTheme}>
              {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
              {themeLabel}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </header>
  );
}

function NavLink({
  href,
  label,
  active,
  block,
}: {
  href: string;
  label: string;
  active?: boolean;
  block?: boolean;
}) {
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
        block && "py-2.5",
        active
          ? "bg-accent text-accent-foreground"
          : "text-muted-foreground hover:bg-accent/50 hover:text-foreground"
      )}
    >
      {label}
    </Link>
  );
}
