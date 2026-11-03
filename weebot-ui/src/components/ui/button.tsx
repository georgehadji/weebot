"use client"

import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { Loader2 } from "lucide-react"

import { cn } from "@/lib/utils"

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-ring disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground hover:bg-primary/90",
        destructive: "bg-destructive text-destructive-foreground hover:bg-destructive/90",
        outline: "border border-border-strong bg-background hover:bg-accent hover:text-accent-foreground",
        secondary: "bg-secondary text-secondary-foreground hover:bg-secondary/80",
        ghost: "hover:bg-accent hover:text-accent-foreground",
        link: "text-primary-text underline-offset-4 hover:underline",
      },
      size: {
        default: "h-10 px-4 py-2 pointer-coarse:min-h-11 pointer-coarse:min-w-11",
        sm: "h-9 rounded-md px-3 pointer-coarse:min-h-11 pointer-coarse:min-w-11",
        lg: "h-11 rounded-md px-8 pointer-coarse:min-h-11 pointer-coarse:min-w-11",
        icon: "h-10 w-10 pointer-coarse:min-h-11 pointer-coarse:min-w-11",
        "icon-sm": "h-8 w-8 rounded-md pointer-coarse:min-h-11 pointer-coarse:min-w-11",
        "icon-xs": "h-6 w-6 rounded-md pointer-coarse:min-h-11 pointer-coarse:min-w-11",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  /**
   * In-flight state. Sets aria-busy/aria-disabled and swallows clicks, but never `disabled`:
   * a disabled button drops keyboard focus, which strands the user mid-action.
   */
  loading?: boolean
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, type = "button", loading = false, onClick, children, ...props }, ref) => {
    // A bare <button> inside a form submits it; only an explicit type="submit" should.
    const iconOnly = size?.startsWith("icon")
    return (
      <button
        type={type}
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        aria-busy={loading || undefined}
        aria-disabled={loading || undefined}
        onClick={loading ? (e) => e.preventDefault() : onClick}
        {...props}
      >
        {loading && <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden="true" />}
        {loading && iconOnly ? null : children}
      </button>
    )
  }
)
Button.displayName = "Button"

export { Button, buttonVariants }
