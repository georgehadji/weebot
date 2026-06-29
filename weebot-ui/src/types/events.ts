/**
 * TypeScript event types - mirrors Python AgentEvent hierarchy
 */

export type PlanStatus = 'created' | 'updated' | 'completed';
export type StepStatus = 'pending' | 'running' | 'completed' | 'error';
export type ToolStatus = 'calling' | 'called';

export interface BaseEvent {
  type: string;
  id: string;
  timestamp: string;
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
  artifact?: unknown;
}

export interface MessageEvent extends BaseEvent {
  type: 'message';
  role: 'user' | 'assistant';
  message: string;
}

export interface TitleEvent extends BaseEvent {
  type: 'title';
  title: string;
}

export interface DoneEvent extends BaseEvent {
  type: 'done';
}

export interface WaitForUserEvent extends BaseEvent {
  type: 'wait_for_user';
  question: string;
}

export interface NotificationEvent extends BaseEvent {
  type: 'notification';
  text: string;
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
  | PlanReviewEvent;

export interface Session {
  id: string;
  user_id: string;
  agent_id: string;
  status: 'active' | 'waiting' | 'completed' | 'cancelled' | 'error';
  title?: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  context: Record<string, any>;
  created_at: string;
  updated_at: string;
  event_count: number;
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
