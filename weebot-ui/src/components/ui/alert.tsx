import * as React from "react"
import { mergeProps } from "@base-ui/react/merge-props"
import { useRender } from "@base-ui/react/use-render"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const alertVariants = cva(
  "group/alert relative grid w-full gap-0.5 rounded-lg border px-2.5 py-2 text-left text-sm has-data-[slot=alert-action]:relative has-data-[slot=alert-action]:pr-18 has-[>svg]:grid-cols-[auto_1fr] has-[>svg]:gap-x-2 [svg]:*:row-span-2 [svg]:*:translate-y-0.5 [svg]:*:text-current [svg:not([class*='size-'])]:*:size-4",
  {
    variants: {
      variant: {
        default: "bg-card text-card-foreground",
        destructive:
          "bg-card text-status-error-fg data-[slot=alert-description]:*:text-status-error-fg/90 [svg]:*:text-current",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

/**
 * `destructive` interrupts (role="alert"); everything else is polite (role="status"). A
 * mounted-on-load "Connecting…" banner must not shout over the page title.
 */
function Alert({
  className,
  variant,
  role,
  ...props
}: React.ComponentProps<"div"> & VariantProps<typeof alertVariants>) {
  return (
    <div
      data-slot="alert"
      role={role ?? (variant === "destructive" ? "alert" : "status")}
      className={cn(alertVariants({ variant }), className)}
      {...props}
    />
  )
}

function AlertTitle({ className, render, ...props }: useRender.ComponentProps<"h3">) {
  return useRender({
    defaultTagName: "h3",
    props: mergeProps<"h3">(
      {
        "data-slot": "alert-title",
        className: cn(
          "font-medium group-has-[>svg]/alert:col-start-2 [&_a]:underline [&_a]:underline-offset-3 hover:[&_a]:text-foreground",
          className
        ),
      } as React.ComponentProps<"h3">,
      props
    ),
    render,
  })
}

function AlertDescription({
  className,
  ...props
}: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="alert-description"
      className={cn(
        "text-sm text-balance text-muted-foreground md:text-pretty [&_a]:underline [&_a]:underline-offset-3 hover:[&_a]:text-foreground [&_p:not(:last-child)]:mb-4",
        className
      )}
      {...props}
    />
  )
}

function AlertAction({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="alert-action"
      className={cn("absolute top-2 right-2", className)}
      {...props}
    />
  )
}

export { Alert, AlertTitle, AlertDescription, AlertAction }
