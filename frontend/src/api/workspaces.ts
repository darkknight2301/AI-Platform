import { api } from "./client";

export interface WorkspaceInfo {
  id: string;
  chat_id: string;
  status: "PENDING" | "ACTIVE" | "STOPPED" | "ERROR";
  target_path: string;
  connect_url: string;
  terminal_enabled: boolean;
}

// connect() is Bearer-authenticated like every other call in `api`
// (see client.ts) and, on success, the backend sets an HttpOnly
// cookie scoping a short-lived ticket to connect_url's path — that's
// what lets the plain browser navigation in ChatView.tsx's "Open VS
// Code" handler authenticate without a header. See
// backend/src/agent_layer/workspace/tickets.py.
export const workspacesApi = {
  connect: (chatId: string) => api.post<WorkspaceInfo>(`/workspaces/${chatId}/connect`, {}),
};
