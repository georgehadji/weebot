/**
 * TypeScript event types - mirrors Python AgentEvent hierarchy
 */

// Mirrors weebot/domain/models/plan.py. 'error' is the legacy name for 'failed'.
export type PlanStatus = 'created' | 'updated' | 'running' | 'completed' | 'failed';
export type StepStatus =
  | 'pending'
  | 'running'
  | 'started'
  | 'completed'
  | 'failed'
  | 'unverified'
  | 'error';
export type ToolStatus = 'calling' | 'called';
/** Client-side only: where a message the user typed is on its way to the server. */
export type DeliveryState = 'sending' | 'sent' | 'failed';

export interface BaseEvent {
  type: string;
  id: string;
  timestamp: string;
  /** Transport correlation id — empty means "global" (see SessionScopedEventBus). */
  session_id: string;
}

export interface ErrorEvent extends BaseEvent {
  type: 'error';
  error: string;
}

export interface PlanEvent extends BaseEvent {
  type: 'plan';
  status: PlanStatus;
  plan?: unknown;
  step?: unknown;
}

export interface StepEvent extends BaseEvent {
  type: 'step';
  step_id: string;
  description: string;
  status: StepStatus;
}

export interface ToolEvent extends BaseEvent {
  type: 'tool';
  tool_call_id: string;
  tool_name: string;
  function_name: string;
  function_args: Record<string, unknown>;
  status: ToolStatus;
  result?: string;
  /** The tool finished with an error (set by the backend; absent on older events). */
  is_error?: boolean;
  artifact?: unknown;
}

export interface MessageEvent extends BaseEvent {
  type: 'message';
  role: 'user' | 'assistant';
  message: string;
  /** Set on messages the UI created optimistically; the server's echo (same id) makes it 'sent'. */
  delivery?: DeliveryState;
}

export interface TitleEvent extends BaseEvent {
  type: 'title';
  title: string;
}

export interface DoneEvent extends BaseEvent {
  type: 'done';
  /** How the run ended. Absent on events stored before the field existed. */
  status?: 'completed' | 'failed';
}

export interface WaitForUserEvent extends BaseEvent {
  type: 'wait_for_user';
  question: string;
}

export interface NotificationEvent extends BaseEvent {
  type: 'notification';
  text: string;
}

/** Session status transition — feeds the WS-driven session rail (never session-scoped). */
export interface SessionPresenceEvent extends BaseEvent {
  type: 'session_presence';
  about_session_id: string;
  status: 'pending' | 'running' | 'waiting' | 'completed' | 'failed' | string;
  title: string;
  step_count: number;
  steps_completed: number;
}

export interface PlanStep {
  id: string;
  description: string;
  status: StepStatus;
}

export interface PlanReviewEvent extends BaseEvent {
  type: 'plan_review';
  plan_data: {
    title?: string;
    steps: PlanStep[];
  };
  step_count: number;
}

export type AgentEvent =
  | ErrorEvent
  | PlanEvent
  | StepEvent
  | ToolEvent
  | MessageEvent
  | TitleEvent
  | DoneEvent
  | WaitForUserEvent
  | NotificationEvent
  | PlanReviewEvent
  | SessionPresenceEvent;

export type SessionStatus = 'pending' | 'running' | 'waiting' | 'completed' | 'failed';

export interface Session {
  id: string;
  user_id: string;
  agent_id: string;
  /** Matches weebot.domain.models.session.SessionStatus.value exactly — see _session_to_response. */
  status: SessionStatus;
  title?: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  context: Record<string, any>;
  created_at: string;
  updated_at: string;
  event_count: number;
}

/** One agent role: its built-in model cascade, the user's pick, and the model tried first. */
export interface RoleModel {
  role: string;
  default: string[];
  override: string | null;
  effective: string;
}

export interface ModelInfo {
  id: string;
  name: string;
  provider: string;
  cost_per_1k_tokens: number;
  context_window: number;
  tier: 'free' | 'fast' | 'standard' | 'premium';
  strengths: string[];
}
