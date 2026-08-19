// Manager dashboard endpoints. Every call here hits an API route that
// enforces "own group only" server-side (`can_manage_group` /
// `user_service.list_users_for_requester`) — this module does no
// scoping of its own, it just calls the already-scoped routes.
import { api } from "./client";
import type {
  ApprovalActionResponse,
  AuditLogListResponse,
  GroupSummary,
  UsageReportResponse,
  UserListResponse,
  UserStatus,
} from "./types";

export const managerApi = {
  listUsers: (status?: UserStatus) =>
    api.get<UserListResponse>(`/users${status ? `?status=${status}` : ""}`),

  approveUser: (userId: string) =>
    api.post<ApprovalActionResponse>(`/users/${userId}/approve`),

  rejectUser: (userId: string) =>
    api.post<ApprovalActionResponse>(`/users/${userId}/reject`),

  getGroup: (groupId: string) => api.get<GroupSummary>(`/users/groups/${groupId}`),

  getGroupUsage: (groupId: string) =>
    api.get<UsageReportResponse>(`/users/groups/${groupId}/usage`),

  getMyActivity: () => api.get<AuditLogListResponse>("/users/me/activity"),
};
