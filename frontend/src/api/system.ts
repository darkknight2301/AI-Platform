// Developer dashboard endpoints. `/system/*` is operational data only —
// logs, model config, request metrics — never chat content or user PII
// (see backend/src/api/v1/routers/system.py).
import { api } from "./client";
import type {
  DiagnosticsResponse,
  HealthResponse,
  ModelStatusResponse,
  PerformanceResponse,
  RecentLogsResponse,
} from "./types";

export const systemApi = {
  getHealth: () => api.get<HealthResponse>("/health"),
  getLogs: (limit = 100) => api.get<RecentLogsResponse>(`/system/logs?limit=${limit}`),
  getModelStatus: () => api.get<ModelStatusResponse>("/system/models"),
  getDiagnostics: () => api.get<DiagnosticsResponse>("/system/diagnostics"),
  getPerformance: () => api.get<PerformanceResponse>("/system/performance"),
};
