import { AlertCircle, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Remote } from "@/types/remote";

interface StateViewProps<T> {
  state: Remote<T>;
  children: (data: T) => React.ReactNode;
  /** True when *data* is ready but has nothing to show; renders `empty` instead. */
  isEmpty?: (data: T) => boolean;
  empty?: React.ReactNode;
  /** What failed, for the error message ("Couldn't load sessions"). */
  errorTitle?: string;
  /** Name of what is loading, for assistive technology. */
  loadingLabel?: string;
  skeleton?: React.ReactNode;
  onRetry?: () => void;
}

/**
 * StateView — renders a `Remote<T>`: skeleton while loading, a message with Retry on failure
 * (over the last good data when there is some), the empty view, or the data itself.
 */
export function StateView<T>({
  state,
  children,
  isEmpty,
  empty,
  errorTitle = "Couldn't load this",
  loadingLabel = "Loading",
  skeleton,
  onRetry,
}: StateViewProps<T>) {
  if (state.status === "idle") return null;

  if (state.status === "loading") {
    return (
      <div role="status" aria-label={loadingLabel} className="space-y-2 p-2">
        {skeleton ?? (
          <>
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-5/6" />
            <Skeleton className="h-8 w-2/3" />
          </>
        )}
      </div>
    );
  }

  const banner =
    state.status === "error" ? (
      <div role="alert" className="surface-error m-2 flex items-start gap-2 rounded-lg border p-3 text-sm">
        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <p className="font-medium">{errorTitle}</p>
          <p className="break-words text-xs">{state.message}</p>
        </div>
        {onRetry && (
          <Button variant="outline" size="sm" onClick={onRetry} className="shrink-0 gap-1">
            <RefreshCw className="h-3 w-3" aria-hidden="true" />
            Retry
          </Button>
        )}
      </div>
    ) : null;

  const data = state.data;
  if (data === undefined) return banner;
  return (
    <>
      {banner}
      {isEmpty?.(data) ? empty : children(data)}
    </>
  );
}
