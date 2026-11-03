"use client";

/**
 * ResponsivePanel — one panel, two presentations. From `md` up it is an inline column (the
 * wrapper reserves the grid cell in CSS, so nothing shifts when it hydrates); below `md` it
 * is a side sheet built on the Dialog primitive, which brings Escape, a focus trap,
 * `aria-modal` and focus return.
 */

import { Dialog, DialogSheet } from "@/components/ui/dialog";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { cn } from "@/lib/utils";

interface ResponsivePanelProps {
  label: string;
  side: "left" | "right";
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Classes for the inline column (md and up). */
  inlineClassName?: string;
  children: React.ReactNode;
}

export function ResponsivePanel({
  label,
  side,
  open,
  onOpenChange,
  inlineClassName,
  children,
}: ResponsivePanelProps) {
  // Desktop is assumed on the server, so a desktop reader hydrates straight into the inline
  // column instead of mounting the Dialog tree first; a phone corrects after hydration.
  const isDesktop = useMediaQuery("(min-width: 768px)", true);
  return (
    <>
      <div className={cn("hidden md:block md:h-full md:overflow-hidden", inlineClassName)}>
        {isDesktop && children}
      </div>
      {!isDesktop && (
        <Dialog open={open} onOpenChange={onOpenChange}>
          <DialogSheet
            side={side}
            aria-label={label}
            // A link to the current path does not navigate away, so dismiss on activation.
            onClick={(e) => (e.target as Element).closest("a") && onOpenChange(false)}
          >
            {children}
          </DialogSheet>
        </Dialog>
      )}
    </>
  );
}
