"use client";

import { useEffect } from "react";
import { AlertCircle, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";

/**
 * Route-level error boundary (Next convention): a render crash inside a page shows this inside
 * the app frame, with a way to retry, instead of Next's bare error page.
 */
export default function RouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Route error:", error);
  }, [error]);

  return (
    <div className="mx-auto flex max-w-md flex-1 flex-col items-center justify-center gap-3 p-8 text-center">
      <AlertCircle className="h-8 w-8 text-status-error-fg" aria-hidden="true" />
      <h1 className="text-lg font-semibold">Something went wrong on this page</h1>
      <p className="text-sm text-muted-foreground">
        The rest of the app is fine. Try again, or go back to another page.
      </p>
      <Button onClick={reset} className="gap-1">
        <RefreshCw className="h-4 w-4" aria-hidden="true" />
        Try again
      </Button>
    </div>
  );
}
