import { useCallback, useEffect, useState } from "react";
import { systemApi } from "../api/system";
import { ApiError } from "../api/client";
import type {
  DiagnosticsResponse,
  HealthResponse,
  ModelStatusOut,
  PerformanceResponse,
  RecentLogsResponse,
} from "../api/types";
import {
  Badge,
  DashboardChrome,
  ErrorNote,
  Section,
  StatCard,
  formatDate,
} from "../components/dashboard/Shared";

const TABS = [
  { id: "health", label: "Health" },
  { id: "performance", label: "Performance" },
  { id: "models", label: "Model availability" },
  { id: "logs", label: "Logs" },
];

export function DeveloperDashboardPage() {
  const [activeTab, setActiveTab] = useState("health");

  const [appHealth, setAppHealth] = useState<HealthResponse | null>(null);
  const [diagnostics, setDiagnostics] = useState<DiagnosticsResponse | null>(null);
  const [performance, setPerformance] = useState<PerformanceResponse | null>(null);
  const [models, setModels] = useState<ModelStatusOut[] | null>(null);
  const [logs, setLogs] = useState<RecentLogsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [healthRes, diagRes, perfRes, modelsRes, logsRes] = await Promise.all([
        systemApi.getHealth(),
        systemApi.getDiagnostics(),
        systemApi.getPerformance(),
        systemApi.getModelStatus(),
        systemApi.getLogs(150),
      ]);
      setAppHealth(healthRes);
      setDiagnostics(diagRes);
      setPerformance(perfRes);
      setModels(modelsRes.models);
      setLogs(logsRes);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't load the dashboard.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const errorClassCount = performance
    ? Object.entries(performance.requests_by_status_class)
        .filter(([cls]) => cls.startsWith("4") || cls.startsWith("5"))
        .reduce((sum, [, count]) => sum + count, 0)
    : 0;
  const errorRate =
    performance && performance.total_requests > 0
      ? ((errorClassCount / performance.total_requests) * 100).toFixed(1)
      : "0.0";

  return (
    <DashboardChrome
      title="Developer dashboard"
      roleLabel="Developer"
      tabs={TABS}
      activeTab={activeTab}
      onTabChange={setActiveTab}
    >
      <ErrorNote message={error} />

      {activeTab === "health" && (
        <>
          <Section title="Application health">
            {appHealth === null ? (
              <div className="dashboard-empty">Loading…</div>
            ) : (
              <div className="stat-grid">
                <StatCard
                  value={<Badge tone={appHealth.status === "ok" ? "success" : "danger"}>{appHealth.status}</Badge>}
                  label="Status"
                />
                <StatCard value={appHealth.environment} label="Environment" />
                <StatCard value={appHealth.version} label="Version" />
              </div>
            )}
          </Section>

          <Section title="Backend health" note="Reachability of the application's dependencies.">
            {diagnostics === null ? (
              <div className="dashboard-empty">Loading…</div>
            ) : (
              <div className="stat-grid">
                <StatCard
                  value={
                    <Badge tone={diagnostics.database_reachable ? "success" : "danger"}>
                      {diagnostics.database_reachable ? "Reachable" : "Unreachable"}
                    </Badge>
                  }
                  label="Database"
                />
                <StatCard
                  value={`${Math.floor(diagnostics.uptime_seconds / 3600)}h ${Math.floor(
                    (diagnostics.uptime_seconds % 3600) / 60,
                  )}m`}
                  label="Uptime"
                />
                <StatCard value={formatDate(diagnostics.server_time)} label="Server time" />
              </div>
            )}
          </Section>

          <Section title="Model health" note="Live status of every configured model.">
            {models === null ? (
              <div className="dashboard-empty">Loading…</div>
            ) : (
              <div className="data-table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Model</th>
                      <th>Provider</th>
                      <th>Category</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {models.map((m) => (
                      <tr key={m.id}>
                        <td>{m.display_name}</td>
                        <td>{m.provider}</td>
                        <td>{m.category}</td>
                        <td>
                          <Badge tone={m.is_enabled ? "success" : "neutral"}>
                            {m.is_enabled ? "Enabled" : "Disabled"}
                          </Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Section>
        </>
      )}

      {activeTab === "performance" && (
        <>
          <Section
            title="Request latency & error rates"
            note="Aggregated since the application process started."
          >
            {performance === null ? (
              <div className="dashboard-empty">Loading…</div>
            ) : (
              <div className="stat-grid">
                <StatCard value={performance.total_requests.toLocaleString()} label="Total requests" />
                <StatCard
                  value={`${performance.average_response_time_ms.toFixed(0)} ms`}
                  label="Avg response time"
                />
                <StatCard value={`${errorRate}%`} label="Error rate (4xx/5xx)" />
              </div>
            )}
          </Section>

          <Section title="Performance diagnostics" note="Requests grouped by status class.">
            {performance === null ? (
              <div className="dashboard-empty">Loading…</div>
            ) : Object.keys(performance.requests_by_status_class).length === 0 ? (
              <div className="dashboard-empty">No requests recorded yet.</div>
            ) : (
              <div className="data-table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Status class</th>
                      <th>Count</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(performance.requests_by_status_class).map(([cls, count]) => (
                      <tr key={cls}>
                        <td>{cls}</td>
                        <td>{count.toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Section>
        </>
      )}

      {activeTab === "models" && (
        <Section title="Model availability" note="Which models can currently serve requests.">
          {models === null ? (
            <div className="dashboard-empty">Loading…</div>
          ) : (
            <div className="stat-grid">
              <StatCard value={models.length} label="Configured models" />
              <StatCard value={models.filter((m) => m.is_enabled).length} label="Available" />
              <StatCard value={models.filter((m) => !m.is_enabled).length} label="Unavailable" />
            </div>
          )}
        </Section>
      )}

      {activeTab === "logs" && (
        <Section
          title="Logs"
          note="Most recent entries first. No chat content or user PII appears here."
        >
          {logs === null ? (
            <div className="dashboard-empty">Loading…</div>
          ) : logs.entries.length === 0 ? (
            <div className="dashboard-empty">No recent log entries.</div>
          ) : (
            <div>
              {[...logs.entries].reverse().map((entry, i) => (
                <div className="log-line" key={i}>
                  <span className={`log-level ${entry.level}`}>{entry.level}</span>
                  <span>{entry.timestamp}</span>
                  <span className="log-message">
                    {entry.logger}: {entry.message}
                  </span>
                </div>
              ))}
            </div>
          )}
        </Section>
      )}
    </DashboardChrome>
  );
}
