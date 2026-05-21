export interface Stats {
  total_sessions: number;
  total_messages: number;
  by_source: { source: string; count: number }[];
  by_type: { msg_type: string; count: number }[];
  by_org: { org: string; session_count: number; message_count: number }[];
  tokens: { input: number; output: number; cached: number; thinking: number };
}

export interface Session {
  id: string;
  source: string;
  model: string | null;
  first_seen: string;
  last_updated: string;
  message_count: number;
  latest_message: string | null;
  user_email: string | null;
  user_name: string | null;
  device_name: string | null;
  device_id: string | null;
  cwd: string | null;
  repo_url: string | null;
  repo_name: string | null;
  git_branch: string | null;
  git_commit: string | null;
  project_hash: string | null;
  org: string | null;
}

export interface Message {
  id: string;
  session_id: string;
  source: string;
  msg_type: string;
  timestamp: string;
  content: string | null;
  content_preview?: string | null;
  thinking: string | null;
  model: string | null;
  raw_line_number: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cached_tokens: number | null;
  thinking_tokens: number | null;
  tool_name: string | null;
  tool_input: unknown | null;
  tool_output: string | null;
  tool_status: string | null;
}

export type FeedMessage = Pick<
  Message,
  | "id"
  | "session_id"
  | "source"
  | "msg_type"
  | "timestamp"
  | "model"
  | "input_tokens"
  | "output_tokens"
> & { content_preview: string | null; device_name: string | null };

export interface Device {
  device_id: string;
  device_name: string;
  org: string;
  status: string;
  daemon_version: string;
  queue_size: number;
  current_backoff: number;
  messages_this_session: number;
  last_push_at: string | null;
  uptime_seconds: number;
  source_stats: Record<string, unknown> | null;
  recent_errors: string[];
  last_seen_at: string;
  actual_latest_message: string | null;
}

export interface KnowledgeItem {
  id: string;
  org: string;
  category: string;
  title: string;
  content: string;
  source_sessions: string[];
  created_at: string;
  updated_at: string;
}

export interface Recommendation {
  id: string;
  org: string;
  type: string;
  title: string;
  description: string;
  priority: "low" | "medium" | "high";
  status: "open" | "dismissed" | "applied";
  created_at: string;
}

export interface WeeklyAnalysis {
  id: string;
  org: string;
  week_start: string;
  week_end: string;
  summary: string;
  highlights: string[];
  metrics: Record<string, number>;
  created_at: string;
}

export interface Developer {
  user_email: string;
  user_name: string | null;
  session_count: number;
}

export interface MemberBreakdownRow {
  member: string;
  user_email: string | null;
  device_name: string | null;
  source: string;
  org: string | null;
  sessions: number;
  messages: number;
  latest_message: string | null;
}
