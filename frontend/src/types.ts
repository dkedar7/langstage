/**
 * TypeScript types mirroring langgraph-stream-parser event dataclasses.
 * Field names match event.to_dict() output from the library.
 */

// Server → Client events (match langgraph-stream-parser to_dict() output)
export type AgentEvent =
  | ContentEvent
  | ToolStartEvent
  | ToolEndEvent
  | ExtractionEvent
  | InterruptEventMsg
  | UsageEventMsg
  | CompleteEvent
  | ErrorEvent
  | StateUpdateEvent
  | FileChangedEvent
  | CancelledEvent
  | SessionInitEvent;

export interface ContentEvent {
  type: "content";
  content: string;
  role: string;
  node: string | null;
}

export interface ToolStartEvent {
  type: "tool_start";
  id: string;
  name: string;
  args: Record<string, unknown>;
  node: string | null;
}

export interface ToolEndEvent {
  type: "tool_end";
  id: string;
  name: string;
  result: string;
  status: "success" | "error";
  error_message: string | null;
  duration_ms: number | null;
}

export interface ExtractionEvent {
  type: "extraction";
  tool_name: string;
  extracted_type: string;
  data: unknown;
}

export interface InterruptEventMsg {
  type: "interrupt";
  action_requests: ActionRequest[];
  review_configs: ReviewConfig[];
  allowed_decisions: string[];
}

export interface ActionRequest {
  tool: string;
  tool_call_id?: string;
  args: Record<string, unknown>;
  description?: string;
}

export interface ReviewConfig {
  allowed_decisions?: string[];
}

export interface CompleteEvent {
  type: "complete";
}

export interface ErrorEvent {
  type: "error";
  error: string;
}

export interface StateUpdateEvent {
  type: "state_update";
  node: string;
  key: string;
  value: unknown;
}

export interface UsageEventMsg {
  type: "usage";
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  node: string | null;
}

export interface FileChangedEvent {
  type: "file_changed";
  event: "created" | "modified" | "deleted";
  path: string;
}

export interface CancelledEvent {
  type: "cancelled";
}

export interface SessionInitEvent {
  type: "session_init";
  session_id: string;
}

// Client → Server messages
export interface SendMessage {
  type: "message";
  content: string;
}

export interface SendInterruptResponse {
  type: "interrupt_response";
  decisions: Decision[];
}

export interface SendCancel {
  type: "cancel";
}

export interface Decision {
  type: "approve" | "reject" | "edit";
  edited_action?: { name: string; args: Record<string, unknown> };
  message?: string;
}

// UI state types
export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  toolCalls: ToolCall[];
  isStreaming?: boolean;
  timestamp?: number;
  startedAt?: number;
  durationMs?: number;
}

export interface ToolCall {
  id: string;
  name: string;
  args: Record<string, unknown>;
  status: "running" | "success" | "error";
  result?: string;
  errorMessage?: string | null;
  durationMs?: number | null;
  extraction?: {
    extracted_type: string;
    data: unknown;
  };
}

export interface TodoItem {
  content: string;
  status: "pending" | "in_progress" | "completed";
}

export interface CanvasItem {
  id: string;
  type: "dataframe" | "plotly" | "matplotlib" | "mermaid" | "image" | "html" | "markdown";
  title: string;
  data: unknown;
  file?: string;
  created_at: string;
}

export interface FileEntry {
  name: string;
  path: string;
  is_dir: boolean;
  size?: number | null;
  children?: FileEntry[] | null;
}

export interface FilePreview {
  path: string;
  name: string;
  size: number;
  preview_type: "text" | "image" | "html" | "csv" | "pdf" | "binary";
  language?: string;
  mime?: string;
  data?: string;
  headers?: string[];
  rows?: Record<string, string>[];
  download_url?: string;
}

export interface AppConfig {
  title: string;
  subtitle: string;
  welcome_message: string;
  theme: "light" | "dark" | "auto";
  workspace_name: string;
  agent_name: string;
  icon_url: string;
  save_workflow_prompt: string;
  run_workflow_prompt: string;
}

export interface TokenUsage {
  input: number;
  output: number;
  total: number;
}

export interface TurnUsage {
  turn: number;
  input: number;
  output: number;
  total: number;
}

export type ConnectionStatus = "connecting" | "connected" | "disconnected" | "error";
