import { useCallback, useEffect, useState } from "react";
import { adminApi } from "../api/admin";
import { systemApi } from "../api/system";
import { ApiError } from "../api/client";
import type {
  AdminModelOut,
  AuditLogOut,
  DiagnosticsResponse,
  GlobalConfigOut,
  GroupOut,
  HealthResponse,
  ModelStatusOut,
  Role,
  UsageReportResponse,
  UserStatus,
  UserSummary,
} from "../api/types";
import {
  Badge,
  DashboardChrome,
  ErrorNote,
  Section,
  StatCard,
  formatDate,
  statusTone,
} from "../components/dashboard/Shared";

const TABS = [
  { id: "users", label: "Users & roles" },
  { id: "groups", label: "Groups" },
  { id: "models", label: "Models" },
  { id: "usage", label: "Usage" },
  { id: "config", label: "System configuration" },
  { id: "audit", label: "Audit logs" },
  { id: "health", label: "Health" },
];

const ROLES: Role[] = ["USER", "MANAGER", "DEVELOPER", "OWNER"];
const STATUSES: UserStatus[] = ["ACTIVE", "INACTIVE", "SUSPENDED", "PENDING"];

export function OwnerDashboardPage() {
  const [activeTab, setActiveTab] = useState("users");
  const [error, setError] = useState<string | null>(null);

  const [users, setUsers] = useState<UserSummary[] | null>(null);
  const [groups, setGroups] = useState<GroupOut[] | null>(null);
  const [models, setModels] = useState<AdminModelOut[] | null>(null);
  const [usage, setUsage] = useState<UsageReportResponse | null>(null);
  const [config, setConfig] = useState<GlobalConfigOut | null>(null);
  const [auditLogs, setAuditLogs] = useState<AuditLogOut[] | null>(null);
  const [appHealth, setAppHealth] = useState<HealthResponse | null>(null);
  const [diagnostics, setDiagnostics] = useState<DiagnosticsResponse | null>(null);
  const [devModels, setDevModels] = useState<ModelStatusOut[] | null>(null);

  const [savingUserId, setSavingUserId] = useState<string | null>(null);
  const [newGroupName, setNewGroupName] = useState("");
  const [creatingGroup, setCreatingGroup] = useState(false);
  const [newModel, setNewModel] = useState({
    model_key: "",
    display_name: "",
    category: "NLP" as "NLP" | "CODER",
    provider: "",
    version: "",
  });
  const [creatingModel, setCreatingModel] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [usersRes, groupsRes, modelsRes, usageRes, configRes, auditRes] = await Promise.all([
        adminApi.listUsers(),
        adminApi.listGroups(),
        adminApi.listModels(),
        adminApi.getGlobalUsage(),
        adminApi.getConfig(),
        adminApi.listAuditLogs(),
      ]);
      setUsers(usersRes.users);
      setGroups(groupsRes);
      setModels(modelsRes);
      setUsage(usageRes);
      setConfig(configRes);
      setAuditLogs(auditRes.entries);

      const [healthRes, diagRes, devModelsRes] = await Promise.all([
        systemApi.getHealth(),
        systemApi.getDiagnostics(),
        systemApi.getModelStatus(),
      ]);
      setAppHealth(healthRes);
      setDiagnostics(diagRes);
      setDevModels(devModelsRes.models);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't load the dashboard.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleRoleChange(userId: string, role: Role) {
    setSavingUserId(userId);
    try {
      await adminApi.updateUser(userId, { role });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't update this user's role.");
    } finally {
      setSavingUserId(null);
    }
  }

  async function handleStatusChange(userId: string, status: UserStatus) {
    setSavingUserId(userId);
    try {
      await adminApi.updateUser(userId, { status });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't update this user's status.");
    } finally {
      setSavingUserId(null);
    }
  }

  async function handleGroupReassign(userId: string, groupId: string) {
    setSavingUserId(userId);
    try {
      await adminApi.updateUser(userId, { group_id: groupId || null });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't reassign this user's group.");
    } finally {
      setSavingUserId(null);
    }
  }

  async function handleCreateGroup() {
    if (!newGroupName.trim()) return;
    setCreatingGroup(true);
    try {
      await adminApi.createGroup({ name: newGroupName.trim() });
      setNewGroupName("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't create the group.");
    } finally {
      setCreatingGroup(false);
    }
  }

  async function handleToggleGroupStatus(group: GroupOut) {
    try {
      await adminApi.updateGroup(group.id, {
        status: group.status === "ACTIVE" ? "INACTIVE" : "ACTIVE",
      });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't update the group.");
    }
  }

  async function handleCreateModel() {
    if (!newModel.model_key.trim() || !newModel.display_name.trim()) return;
    setCreatingModel(true);
    try {
      await adminApi.createModel({
        model_key: newModel.model_key.trim(),
        display_name: newModel.display_name.trim(),
        category: newModel.category,
        provider: newModel.provider.trim() || "unknown",
        version: newModel.version.trim() || "1.0",
      });
      setNewModel({ model_key: "", display_name: "", category: "NLP", provider: "", version: "" });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't create the model.");
    } finally {
      setCreatingModel(false);
    }
  }

  async function handleToggleModel(model: AdminModelOut) {
    try {
      await adminApi.updateModel(model.id, { is_enabled: !model.is_enabled });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't update the model.");
    }
  }

  return (
    <DashboardChrome
      title="Owner dashboard"
      roleLabel="Owner"
      tabs={TABS}
      activeTab={activeTab}
      onTabChange={setActiveTab}
    >
      <ErrorNote message={error} />

      {activeTab === "users" && (
        <Section title="Users & roles" note="Every user, across every group. Role changes take effect immediately.">
          {users === null ? (
            <div className="dashboard-empty">Loading…</div>
          ) : (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Username</th>
                    <th>Email</th>
                    <th>Role</th>
                    <th>Status</th>
                    <th>Group</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((u) => (
                    <tr key={u.id}>
                      <td>{u.username}</td>
                      <td>{u.email}</td>
                      <td>
                        <select
                          className="select-input"
                          value={u.role}
                          disabled={savingUserId === u.id}
                          onChange={(e) => handleRoleChange(u.id, e.target.value as Role)}
                        >
                          {ROLES.map((r) => (
                            <option key={r} value={r}>
                              {r}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>
                        <select
                          className="select-input"
                          value={u.status}
                          disabled={savingUserId === u.id}
                          onChange={(e) => handleStatusChange(u.id, e.target.value as UserStatus)}
                        >
                          {STATUSES.map((s) => (
                            <option key={s} value={s}>
                              {s}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>
                        <select
                          className="select-input"
                          value={u.group_id ?? ""}
                          disabled={savingUserId === u.id}
                          onChange={(e) => handleGroupReassign(u.id, e.target.value)}
                        >
                          <option value="">No group</option>
                          {(groups ?? []).map((g) => (
                            <option key={g.id} value={g.id}>
                              {g.name}
                            </option>
                          ))}
                        </select>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Section>
      )}

      {activeTab === "groups" && (
        <Section
          title="Groups"
          action={
            <div className="inline-form">
              <input
                className="select-input"
                placeholder="New group name"
                value={newGroupName}
                onChange={(e) => setNewGroupName(e.target.value)}
              />
              <button className="btn btn-primary" disabled={creatingGroup} onClick={handleCreateGroup}>
                Create group
              </button>
            </div>
          }
        >
          {groups === null ? (
            <div className="dashboard-empty">Loading…</div>
          ) : groups.length === 0 ? (
            <div className="dashboard-empty">No groups yet.</div>
          ) : (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Status</th>
                    <th>Created</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {groups.map((g) => (
                    <tr key={g.id}>
                      <td>{g.name}</td>
                      <td>
                        <Badge tone={g.status === "ACTIVE" ? "success" : "neutral"}>{g.status}</Badge>
                      </td>
                      <td>{formatDate(g.created_at)}</td>
                      <td>
                        <button className="btn btn-secondary" onClick={() => handleToggleGroupStatus(g)}>
                          {g.status === "ACTIVE" ? "Deactivate" : "Activate"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Section>
      )}

      {activeTab === "models" && (
        <Section
          title="Model management"
          note="Add a model or toggle whether it's currently enabled."
          action={
            <div className="inline-form">
              <input
                className="select-input"
                placeholder="model_key"
                value={newModel.model_key}
                onChange={(e) => setNewModel({ ...newModel, model_key: e.target.value })}
              />
              <input
                className="select-input"
                placeholder="Display name"
                value={newModel.display_name}
                onChange={(e) => setNewModel({ ...newModel, display_name: e.target.value })}
              />
              <select
                className="select-input"
                value={newModel.category}
                onChange={(e) =>
                  setNewModel({ ...newModel, category: e.target.value as "NLP" | "CODER" })
                }
              >
                <option value="NLP">NLP</option>
                <option value="CODER">CODER</option>
              </select>
              <input
                className="select-input"
                placeholder="Provider"
                value={newModel.provider}
                onChange={(e) => setNewModel({ ...newModel, provider: e.target.value })}
              />
              <input
                className="select-input"
                placeholder="Version"
                value={newModel.version}
                onChange={(e) => setNewModel({ ...newModel, version: e.target.value })}
              />
              <button className="btn btn-primary" disabled={creatingModel} onClick={handleCreateModel}>
                Add model
              </button>
            </div>
          }
        >
          {models === null ? (
            <div className="dashboard-empty">Loading…</div>
          ) : (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Model</th>
                    <th>Provider</th>
                    <th>Version</th>
                    <th>Category</th>
                    <th>Status</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {models.map((m) => (
                    <tr key={m.id}>
                      <td>{m.display_name}</td>
                      <td>{m.provider}</td>
                      <td>{m.version}</td>
                      <td>{m.category}</td>
                      <td>
                        <Badge tone={m.is_enabled ? "success" : "neutral"}>
                          {m.is_enabled ? "Enabled" : "Disabled"}
                        </Badge>
                      </td>
                      <td>
                        <button className="btn btn-secondary" onClick={() => handleToggleModel(m)}>
                          {m.is_enabled ? "Disable" : "Enable"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Section>
      )}

      {activeTab === "usage" && (
        <Section title="Usage" note="Aggregated token usage across every group.">
          {usage === null ? (
            <div className="dashboard-empty">Loading…</div>
          ) : (
            <div className="stat-grid">
              <StatCard value={usage.total_tokens.toLocaleString()} label="Total tokens" />
              <StatCard value={usage.total_input_tokens.toLocaleString()} label="Input tokens" />
              <StatCard value={usage.total_output_tokens.toLocaleString()} label="Output tokens" />
              <StatCard value={usage.records.length} label="Usage records (page)" />
            </div>
          )}
        </Section>
      )}

      {activeTab === "config" && (
        <Section title="System configuration" note="Non-secret settings. No credentials are ever shown here.">
          {config === null ? (
            <div className="dashboard-empty">Loading…</div>
          ) : (
            <div className="stat-grid">
              <StatCard value={config.app_name} label="App name" />
              <StatCard value={config.environment} label="Environment" />
              <StatCard value={config.rate_limit_requests_per_minute} label="Rate limit / min" />
              <StatCard value={`${config.access_token_expire_minutes} min`} label="Token expiry" />
              <StatCard value={config.default_max_active_chats} label="Default max active chats" />
              <StatCard value={config.default_token_quota.toLocaleString()} label="Default token quota" />
              <StatCard value={config.token_quota_renewal_policy} label="Renewal policy" />
            </div>
          )}
        </Section>
      )}

      {activeTab === "audit" && (
        <Section title="Audit logs" note="Every recorded administrative action, most recent first.">
          {auditLogs === null ? (
            <div className="dashboard-empty">Loading…</div>
          ) : auditLogs.length === 0 ? (
            <div className="dashboard-empty">No audit entries yet.</div>
          ) : (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Action</th>
                    <th>Target</th>
                    <th>Result</th>
                    <th>When</th>
                  </tr>
                </thead>
                <tbody>
                  {auditLogs.map((entry) => (
                    <tr key={entry.id}>
                      <td>{entry.action}</td>
                      <td>
                        {entry.target_type ?? "—"} {entry.target_id ? `· ${entry.target_id}` : ""}
                      </td>
                      <td>
                        <Badge tone={statusTone(entry.result)}>{entry.result}</Badge>
                      </td>
                      <td>{formatDate(entry.timestamp)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Section>
      )}

      {activeTab === "health" && (
        <>
          <Section title="Application & backend health">
            {appHealth === null || diagnostics === null ? (
              <div className="dashboard-empty">Loading…</div>
            ) : (
              <div className="stat-grid">
                <StatCard
                  value={<Badge tone={appHealth.status === "ok" ? "success" : "danger"}>{appHealth.status}</Badge>}
                  label="Application"
                />
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
              </div>
            )}
          </Section>

          <Section title="Model health">
            {devModels === null ? (
              <div className="dashboard-empty">Loading…</div>
            ) : (
              <div className="stat-grid">
                <StatCard value={devModels.length} label="Configured" />
                <StatCard value={devModels.filter((m) => m.is_enabled).length} label="Available" />
                <StatCard value={devModels.filter((m) => !m.is_enabled).length} label="Unavailable" />
              </div>
            )}
          </Section>
        </>
      )}
    </DashboardChrome>
  );
}
