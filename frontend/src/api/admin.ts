// Owner-only administrative endpoints (`/admin/*`). The backend rejects
// anyone below Role.OWNER at the dependency level regardless of what
// this page renders — see backend/src/api/v1/routers/admin.py.
import { api } from "./client";
import type {
  AdminModelOut,
  AuditLogListResponse,
  GlobalConfigOut,
  GroupOut,
  Role,
  UsageReportResponse,
  UserStatus,
  UserSummary,
} from "./types";

export interface GroupCreateInput {
  name: string;
  status?: "ACTIVE" | "INACTIVE";
  max_active_chats_override?: number | null;
  token_quota_override?: number | null;
}

export interface GroupUpdateInput {
  name?: string;
  status?: "ACTIVE" | "INACTIVE";
  max_active_chats_override?: number | null;
  token_quota_override?: number | null;
}

export interface UserAdminUpdateInput {
  role?: Role;
  status?: UserStatus;
  group_id?: string | null;
  max_active_chats_override?: number | null;
  token_quota_override?: number | null;
}

export interface ModelCreateInput {
  model_key: string;
  display_name: string;
  category: "CODER" | "NLP";
  provider: string;
  version: string;
  is_enabled?: boolean;
  capabilities?: string[];
  config_metadata?: Record<string, unknown>;
}

export interface ModelUpdateInput {
  display_name?: string;
  is_enabled?: boolean;
  capabilities?: string[];
  config_metadata?: Record<string, unknown>;
}

export const adminApi = {
  // Users (global, every group) — role/status/group reassignment.
  listUsers: (status?: UserStatus) =>
    api.get<{ users: UserSummary[]; total: number }>(
      `/users${status ? `?status=${status}` : ""}`,
    ),
  updateUser: (userId: string, payload: UserAdminUpdateInput) =>
    api.patch<UserSummary>(`/admin/users/${userId}`, payload),

  // Groups
  listGroups: () => api.get<GroupOut[]>("/admin/groups"),
  createGroup: (payload: GroupCreateInput) => api.post<GroupOut>("/admin/groups", payload),
  updateGroup: (groupId: string, payload: GroupUpdateInput) =>
    api.patch<GroupOut>(`/admin/groups/${groupId}`, payload),

  // Models
  listModels: () => api.get<AdminModelOut[]>("/admin/models"),
  createModel: (payload: ModelCreateInput) => api.post<AdminModelOut>("/admin/models", payload),
  updateModel: (modelId: string, payload: ModelUpdateInput) =>
    api.patch<AdminModelOut>(`/admin/models/${modelId}`, payload),

  // Usage / audit / config
  getGlobalUsage: (limit = 200) =>
    api.get<UsageReportResponse>(`/admin/usage?limit=${limit}`),
  listAuditLogs: (limit = 100) =>
    api.get<AuditLogListResponse>(`/admin/audit-logs?limit=${limit}`),
  getConfig: () => api.get<GlobalConfigOut>("/admin/config"),
};
