"use client";

/**
 * TopBar — the console's contextual second bar: session breadcrumb,
 * connection state, command palette trigger. Sits below the global
 * Header (logo/nav/theme/settings already live there — this bar does
 * not repeat them).
 */

import { Command } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface TopBarProps {
  title?: string;
  isConnected?: boolean;
  onOpenPalette?: () => void;
}

export function TopBar({ title, isConnected, onOpenPalette }: TopBarProps) {
  return (
    <div className="flex h-topbar shrink-0 items-center gap-3 border-b bg-surface-1 px-3">
      <span className="truncate text-sm font-medium">{title || "Mission Center"}</span>

      <div className="ml-auto flex items-center gap-2">
        {isConnected !== undefined && (
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <span
              className={cn(
                "h-1.5 w-1.5 rounded-full",
                isConnected ? "bg-status-live animate-pulse" : "bg-status-idle"
              )}
            />
            {isConnected ? "Live" : "Offline"}
          </span>
        )}

        {onOpenPalette && (
          <Button variant="outline" size="sm" onClick={onOpenPalette} className="h-7 gap-1 text-xs">
            <Command className="h-3 w-3" />
            <span>K</span>
          </Button>
        )}
      </div>
    </div>
  );
}
