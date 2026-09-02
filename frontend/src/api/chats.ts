import { api } from "./client";
import { streamPost } from "./stream";
import type {
  ChatHistoryResponse,
  ChatStatus,
  ChatSummary,
  MessageExchangeResponse,
  MessageRevisionsResponse,
  ModelInfo,
  StreamEvent,
} from "./types";

export const modelsApi = {
  list: () => api.get<{ models: ModelInfo[] }>("/models"),
};

export const chatsApi = {
  list: (status?: ChatStatus) =>
    api.get<{ chats: ChatSummary[]; total: number }>(
      `/chats${status ? `?status=${status}` : ""}`,
    ),

  create: (input: { model_key?: string; agent_key?: string; title?: string | null }) =>
    api.post<ChatSummary>("/chats", input),

  get: (chatId: string) => api.get<ChatSummary>(`/chats/${chatId}`),

  update: (chatId: string, input: { title?: string; status?: ChatStatus; model_key?: string }) =>
    api.patch<ChatSummary>(`/chats/${chatId}`, input),

  remove: (chatId: string) => api.delete<void>(`/chats/${chatId}`),

  history: (chatId: string) => api.get<ChatHistoryResponse>(`/chats/${chatId}/history`),

  sendMessage: (chatId: string, content: string) =>
    api.post<MessageExchangeResponse>(`/chats/${chatId}/messages`, { content, stream: false }),

  streamMessage: (chatId: string, content: string, onEvent: (e: StreamEvent) => void, signal?: AbortSignal) =>
    streamPost(`/chats/${chatId}/messages`, { content, stream: true }, onEvent, signal),
};

export const messagesApi = {
  edit: (messageId: string, content: string) =>
    api.post<MessageExchangeResponse>(`/messages/${messageId}/edit`, { content, stream: false }),

  editStream: (messageId: string, content: string, onEvent: (e: StreamEvent) => void, signal?: AbortSignal) =>
    streamPost(`/messages/${messageId}/edit`, { content, stream: true }, onEvent, signal),

  regenerate: (messageId: string) =>
    api.post<MessageExchangeResponse>(`/messages/${messageId}/regenerate`, {}),

  regenerateStream: (messageId: string, onEvent: (e: StreamEvent) => void, signal?: AbortSignal) =>
    streamPost(`/messages/${messageId}/regenerate`, { stream: true }, onEvent, signal),

  revisions: (messageId: string) =>
    api.get<MessageRevisionsResponse>(`/messages/${messageId}/revisions`),

  activate: (messageId: string) => api.post(`/messages/${messageId}/activate`),
};
