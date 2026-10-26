/**
 * Status → how it is shown. The one home for the mapping that the rail, the sessions page and
 * the timeline rows each used to keep their own copy of.
 *
 * Status is never colour alone: every entry has its own icon and a label.
 */
import {
  AlertTriangle,
  CheckCircle2,
  Circle,
  CircleDashed,
  Clock,
  Loader2,
  XCircle,
  type LucideIcon,
} from "lucide-react";

export type StatusTone = "live" | "waiting" | "error" | "idle";

export interface StatusInfo {
  label: string;
  icon: LucideIcon;
  tone: StatusTone;
  /** The icon should spin (work in progress). */
  spin?: boolean;
}

const STATUS: Record<string, StatusInfo> = {
  // Session lifecycle (weebot.domain.models.session.SessionStatus)
  pending: { label: "Pending", icon: CircleDashed, tone: "idle" },
  running: { label: "Running", icon: Loader2, tone: "live", spin: true },
  waiting: { label: "Waiting for you", icon: Clock, tone: "waiting" },
  completed: { label: "Completed", icon: CheckCircle2, tone: "idle" },
  failed: { label: "Failed", icon: XCircle, tone: "error" },
  // Plan steps add these
  started: { label: "Running", icon: Loader2, tone: "live", spin: true },
  error: { label: "Failed", icon: XCircle, tone: "error" },
  unverified: { label: "Unverified", icon: AlertTriangle, tone: "waiting" },
};

const UNKNOWN: StatusInfo = { label: "Unknown", icon: Circle, tone: "idle" };

export function statusInfo(status: string): StatusInfo {
  return STATUS[status] ?? { ...UNKNOWN, label: status || UNKNOWN.label };
}

/** Text colour that meets 4.5:1 on the surfaces (see the `--status-*-fg` tokens). */
export const TONE_TEXT: Record<StatusTone, string> = {
  live: "text-status-live-fg",
  waiting: "text-status-waiting-fg",
  error: "text-status-error-fg",
  idle: "text-muted-foreground",
};
