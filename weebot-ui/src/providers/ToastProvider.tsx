"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, Info, X } from "lucide-react";
import { cn } from "@/lib/utils";

export type ToastVariant = "info" | "success" | "error";

export interface ToastAction {
  label: string;
  onClick: () => void;
}

export interface ToastInput {
  title: string;
  description?: string;
  variant?: ToastVariant;
  durationMs?: number;
  action?: ToastAction;
}

interface Toast extends Required<Pick<ToastInput, "title" | "variant" | "durationMs">> {
  id: string;
  description?: string;
  action?: ToastAction;
}

interface ToastContextValue {
  toast: (input: ToastInput) => string;
  dismiss: (id: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);
// Errors stay until dismissed (0 = no timer); the rest wait longer than before and hold still
// while hovered or focused, so they can be read.
const DEFAULT_DURATION_MS = 8000;
const DEFAULT_ERROR_DURATION_MS = 0;

const VARIANT_ICON: Record<ToastVariant, typeof Info> = {
  info: Info,
  success: CheckCircle2,
  error: AlertCircle,
};

const VARIANT_CLASS: Record<ToastVariant, string> = {
  info: "border-border bg-surface-2 text-foreground",
  success: "border-status-live/40 bg-status-live/10 text-foreground",
  error: "border-status-error/40 surface-error",
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  // A counter, not crypto.randomUUID: that is undefined on a plain-http (non-secure) origin.
  const nextId = useRef(0);

  const dismiss = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const toast = useCallback(
    (input: ToastInput) => {
      const id = `toast-${nextId.current++}`;
      const entry: Toast = {
        id,
        title: input.title,
        description: input.description,
        variant: input.variant ?? "info",
        durationMs:
          input.durationMs ??
          (input.variant === "error" ? DEFAULT_ERROR_DURATION_MS : DEFAULT_DURATION_MS),
        action: input.action,
      };
      setToasts((prev) => [...prev, entry]);
      return id;
    },
    []
  );

  const value = useMemo(() => ({ toast, dismiss }), [toast, dismiss]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-full max-w-sm flex-col gap-2"
        role="region"
        aria-label="Notifications"
      >
        {toasts.map((t) => (
          <ToastItem key={t.id} toast={t} onDismiss={dismiss} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return ctx;
}

function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss: (id: string) => void }) {
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const held = hovered || focused;
  const { id, durationMs } = toast;
  const Icon = VARIANT_ICON[toast.variant];

  // The clock runs only while the toast is not hovered or focused.
  useEffect(() => {
    if (durationMs <= 0 || held) return;
    const timer = setTimeout(() => onDismiss(id), durationMs);
    return () => clearTimeout(timer);
  }, [id, durationMs, held, onDismiss]);

  return (
    <div
      role={toast.variant === "error" ? "alert" : "status"}
      aria-live={toast.variant === "error" ? "assertive" : "polite"}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      className={cn(
        "pointer-events-auto flex items-start gap-2.5 rounded-lg border p-3 shadow-lg transition-all duration-base ease-console animate-in slide-in-from-bottom-2 fade-in",
        VARIANT_CLASS[toast.variant]
      )}
    >
      <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium leading-tight">{toast.title}</p>
        {toast.description && (
          <p className="mt-0.5 break-words text-xs text-muted-foreground">{toast.description}</p>
        )}
        {toast.action && (
          <button
            onClick={() => {
              toast.action?.onClick();
              onDismiss(id);
            }}
            className="mt-1.5 text-xs font-medium underline underline-offset-2 hover:no-underline"
          >
            {toast.action.label}
          </button>
        )}
      </div>
      <button
        onClick={() => onDismiss(id)}
        aria-label="Dismiss notification"
        className="shrink-0 rounded-sm opacity-60 transition-opacity hover:opacity-100"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
