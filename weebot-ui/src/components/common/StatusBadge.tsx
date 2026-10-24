import { cn } from "@/lib/utils";
import { statusInfo, TONE_TEXT } from "./status";

interface StatusBadgeProps {
  status: string;
  /** "icon": the status glyph only (label for screen readers); "pill": glyph and visible label. */
  variant?: "icon" | "pill";
  className?: string;
}

/**
 * StatusBadge — the one way a status is shown. Colour is never the only signal: each status has
 * its own glyph and a label (visible in `pill`, announced in `icon`).
 */
export function StatusBadge({ status, variant = "pill", className }: StatusBadgeProps) {
  const { label, icon: Icon, tone, spin } = statusInfo(status);
  const glyph = (
    <Icon
      aria-hidden="true"
      className={cn("h-3.5 w-3.5 shrink-0", spin && "motion-safe:animate-spin", TONE_TEXT[tone])}
    />
  );
  if (variant === "icon") {
    return (
      <span className={cn("inline-flex", className)} title={label} role="img" aria-label={label}>
        {glyph}
      </span>
    );
  }
  return (
    <span className={cn("inline-flex items-center gap-1 text-xs font-medium", TONE_TEXT[tone], className)}>
      {glyph}
      {label}
    </span>
  );
}
