import { useCallback, useEffect, useState } from "react";
import { managerApi } from "../api/manager";
import { ApiError } from "../api/client";
import type {
  AuditLogOut,
  GroupSummary,
  UsageReportResponse,
  UserSummary,
} from "../api/types";
import { useAuth } from "../context/AuthContext";
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
  { id: "approvals", label: "Pending users" },
  { id: "group", label: "Group" },
  { id: "activity", label: "Authorized activity" },
];

export function ManagerDashboardPage() {
  const { user } = useAuth();
  const [activeTab, setActiveTab] = useState("approvals");

  const [pending, setPending] = useState<UserSummary[] | null>(null);
  const [groupUsers, setGroupUsers] = useState<UserSummary[] | null>(null);
  const [group, setGroup] = useState<GroupSummary | null>(null);
  const [usage, setUsage] = useState<UsageReportResponse | null>(null);
  const [activity, setActivity] = useState<AuditLogOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actingOn, setActingOn] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [pendingRes, allRes] = await Promise.all([
        managerApi.listUsers("PENDING"),
        managerApi.listUsers(),
      ]);
      setPending(pendingRes.users);
      setGroupUsers(allRes.users);

      if (user?.group_id) {
        const [groupRes, usageRes] = await Promise.all([
          managerApi.getGroup(user.group_id),
          managerApi.getGroupUsage(user.group_id),
        ]);
        setGroup(groupRes);
        setUsage(usageRes);
      }

      const activityRes = await managerApi.getMyActivity();
      setActivity(activityRes.entries);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't load the dashboard.");
    }
  }, [user?.group_id]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleApprove(id: string) {
    setActingOn(id);
    try {
      await managerApi.approveUser(id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't approve this user.");
    } finally {
      setActingOn(null);
    }
  }

  async function handleReject(id: string) {
    setActingOn(id);
    try {
      await managerApi.rejectUser(id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't reject this user.");
    } finally {
      setActingOn(null);
    }
  }

  return (
    <DashboardChrome
      title="Manager dashboard"
      roleLabel="Manager"
      tabs={TABS}
      activeTab={activeTab}
      onTabChange={setActiveTab}
    >
      <ErrorNote message={error} />

      {activeTab === "approvals" && (
        <Section
          title="Pending users"
          note="New registrations in your group waiting for a decision."
        >
          {pending === null ? (
            <div className="dashboard-empty">Loading…</div>
          ) : pending.length === 0 ? (
            <div className="dashboard-empty">No users are waiting on approval.</div>
          ) : (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Username</th>
                    <th>Email</th>
                    <th>Requested</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {pending.map((u) => (
                    <tr key={u.id}>
                      <td>{u.username}</td>
                      <td>{u.email}</td>
                      <td>{formatDate(u.created_at)}</td>
                      <td>
                        <div className="row-actions">
                          <button
                            className="btn btn-primary"
                            disabled={actingOn === u.id}
                            onClick={() => handleApprove(u.id)}
                          >
                            Approve
                          </button>
                          <button
                            className="btn btn-secondary"
                            disabled={actingOn === u.id}
                            onClick={() => handleReject(u.id)}
                          >
                            Reject
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Section>
      )}

      {activeTab === "group" && (
        <>
          <Section
            title={group ? `Group: ${group.name}` : "Group"}
            note="You can only see and manage the group you belong to."
          >
            {!user?.group_id ? (
              <div className="dashboard-empty">You're not assigned to a group yet.</div>
            ) : (
              <div className="stat-grid">
                <StatCard value={groupUsers?.length ?? "—"} label="Members" />
                <StatCard
                  value={usage ? usage.total_tokens.toLocaleString() : "—"}
                  label="Total tokens used"
                />
                <StatCard value={usage ? usage.records.length : "—"} label="Usage records" />
              </div>
            )}
          </Section>

          <Section title="Group users">
            {groupUsers === null ? (
              <div className="dashboard-empty">Loading…</div>
            ) : (
              <div className="data-table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Username</th>
                      <th>Email</th>
                      <th>Status</th>
                      <th>Joined</th>
                    </tr>
                  </thead>
                  <tbody>
                    {groupUsers.map((u) => (
                      <tr key={u.id}>
                        <td>{u.username}</td>
                        <td>{u.email}</td>
                        <td>
                          <Badge tone={statusTone(u.status)}>{u.status}</Badge>
                        </td>
                        <td>{formatDate(u.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Section>
        </>
      )}

      {activeTab === "activity" && (
        <Section
          title="Authorized activity"
          note="Actions you've personally approved or rejected."
        >
          {activity === null ? (
            <div className="dashboard-empty">Loading…</div>
          ) : activity.length === 0 ? (
            <div className="dashboard-empty">No activity recorded yet.</div>
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
                  {activity.map((entry) => (
                    <tr key={entry.id}>
                      <td>{entry.action}</td>
                      <td>{entry.target_id ?? "—"}</td>
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
    </DashboardChrome>
  );
}
