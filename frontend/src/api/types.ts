// Types mirroring backend Pydantic schemas (Phase 1-7). Kept in one
// file since the frontend has no independent domain logic of its own —
// it's a direct client of this API.

export type Role = "USER" | "MANAGER" | "DEVELOPER" | "OWNER";
export type UserStatus = "ACTIVE" | "INACTIVE" | "SUSPENDED" | "PENDING";
export type ChatStatus = "ACTIVE" | "ARCHIVED" | "DELETED";
export type MessageRole = "SYSTEM" | "USER" | "ASSISTANT" | "TOOL";
export type ModelCategory = "CODER" | "NLP" | "AGENT";

export interface ILAGenerateParams {
  mode: string;
  function_name: string;
  step: string;
  test_case_desc?: string;
  overwrite_step?: boolean;
  output_file: string;
}
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
  agent_key: string | null;
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

// --- Phase 9: Administrative Interfaces --------------------------------

export type GroupStatus = "ACTIVE" | "INACTIVE";
export type AuditResult = "SUCCESS" | "FAILURE";

export interface UserSummary {
  id: string;
  username: string;
  email: string;
  status: UserStatus;
  role: Role;
  group_id: string | null;
  created_at: string;
  last_login_at: string | null;
}

export interface UserListResponse {
  users: UserSummary[];
  total: number;
}

export interface ApprovalActionResponse {
  id: string;
  status: UserStatus;
  detail: string;
}

/** Own-group summary — what a Manager may see about their group. */
export interface GroupSummary {
  id: string;
  name: string;
  status: GroupStatus;
}

/** Full group record with quota overrides — Owner (`/admin/groups`) only. */
export interface GroupOut extends GroupSummary {
  max_active_chats_override: number | null;
  token_quota_override: number | null;
  created_at: string;
}

export interface UsageRecordOut {
  id: string;
  chat_id: string | null;
  message_id: string | null;
  model_id: string;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  timestamp: string;
}

export interface UsageReportResponse {
  records: UsageRecordOut[];
  total_input_tokens: number;
  total_output_tokens: number;
  total_tokens: number;
}

export interface AuditLogOut {
  id: string;
  actor_user_id: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  timestamp: string;
  request_id: string | null;
  result: AuditResult;
  audit_metadata: Record<string, unknown>;
}

export interface AuditLogListResponse {
  entries: AuditLogOut[];
  total: number;
}

/** Owner's model record — includes fields needed to create/edit a model. */
export interface AdminModelOut {
  id: string;
  model_key: string;
  display_name: string;
  category: ModelCategory;
  provider: string;
  version: string;
  is_enabled: boolean;
  capabilities: string[];
  config_metadata: Record<string, unknown>;
}

export interface GlobalConfigOut {
  app_name: string;
  environment: string;
  rate_limit_requests_per_minute: number;
  access_token_expire_minutes: number;
  default_max_active_chats: number;
  default_token_quota: number;
  token_quota_renewal_policy: string;
}

export interface LogEntryOut {
  timestamp: string;
  level: string;
  logger: string;
  message: string;
}

export interface RecentLogsResponse {
  entries: LogEntryOut[];
}

export interface ModelStatusOut {
  id: string;
  model_key: string;
  display_name: string;
  category: ModelCategory;
  provider: string;
  version: string;
  is_enabled: boolean;
}

export interface ModelStatusResponse {
  models: ModelStatusOut[];
}

export interface DiagnosticsResponse {
  environment: string;
  database_reachable: boolean;
  server_time: string;
  uptime_seconds: number;
}

export interface PerformanceResponse {
  total_requests: number;
  requests_by_status_class: Record<string, number>;
  average_response_time_ms: number;
  uptime_seconds: number;
}

export interface HealthResponse {
  status: string;
  environment: string;
  version: string;
}
