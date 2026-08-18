// Types mirroring backend Pydantic schemas (Phase 1-7). Kept in one
// file since the frontend has no independent domain logic of its own —
// it's a direct client of this API.

export type Role = "USER" | "MANAGER" | "DEVELOPER" | "OWNER";
export type UserStatus = "ACTIVE" | "INACTIVE" | "SUSPENDED" | "PENDING";
export type ChatStatus = "ACTIVE" | "ARCHIVED" | "DELETED";
export type MessageRole = "SYSTEM" | "USER" | "ASSISTANT" | "TOOL";
export type ModelCategory = "CODER" | "NLP";
export type RenewalPolicy = "ROLLING_24H" | "DAILY_RESET_UTC";

export interface UserPublic {
  id: string;
  username: string;
  email: string;
  status: UserStatus;
  role: Role;
  group_id: string | null;
  created_at: string;
  last_login_at: string | null;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_at: string;
}

export interface ModelInfo {
  id: string;
  model_key: string;
  display_name: string;
  category: ModelCategory;
  provider: string;
  version: string;
  is_enabled: boolean;
}

export interface ChatSummary {
  id: string;
  title: string;
  status: ChatStatus;
  model_id: string;
  model_key: string;
  revision: number;
  created_at: string;
  updated_at: string;
}

export interface MessageOut {
  id: string;
  chat_id: string;
  role: MessageRole;
  content: string;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  revision: number;
  revision_count: number;
  root_message_id: string | null;
  is_active: boolean;
  sequence_number: number;
  response_time_ms: number | null;
  model_key: string | null;
  created_at: string;
}

export interface ChatHistoryResponse {
  chat_id: string;
  messages: MessageOut[];
}

export interface MessageExchangeResponse {
  user_message: MessageOut | null;
  assistant_message: MessageOut | null;
}

export interface MessageRevisionsResponse {
  revisions: MessageOut[];
  active_message_id: string;
}

export interface StreamEvent {
  delta: string;
  is_final: boolean;
  finish_reason: "stop" | "length" | "error" | null;
  message_id: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
}

export interface TokenQuotaOut {
  used_tokens: number;
  quota_tokens: number;
  percent_used: number;
  renewal_policy: RenewalPolicy;
  renews_at: string;
}

export interface ChatLimitOut {
  active_chats: number;
  max_active_chats: number;
  percent_used: number;
}

export interface QuotaStatusResponse {
  token_quota: TokenQuotaOut;
  chat_limit: ChatLimitOut;
}
