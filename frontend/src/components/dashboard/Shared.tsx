import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import type { ReactNode } from "react";

export function Badge({
  tone,
  children,
}: {
  tone: "success" | "warning" | "danger" | "neutral" | "accent";
  children: ReactNode;
}) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

export function statusTone(status: string): "success" | "warning" | "danger" | "neutral" {
  switch (status) {
    case "ACTIVE":
      return "success";
    case "PENDING":
      return "warning";
    case "SUSPENDED":
    case "FAILURE":
      return "danger";
    default:
      return "neutral";
  }
}

export function StatCard({ value, label }: { value: ReactNode; label: string }) {
  return (
    <div className="stat-card">
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

export function Section({
  title,
  note,
  action,
  children,
}: {
  title: string;
  note?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="dashboard-section">
      <div className="dashboard-section-header">
        <h2>{title}</h2>
        {action}
      </div>
      {note && <div className="dashboard-section-note" style={{ marginBottom: "0.6rem" }}>{note}</div>}
      {children}
    </section>
  );
}

export function DashboardChrome({
  title,
  roleLabel,
  tabs,
  activeTab,
  onTabChange,
  children,
}: {
  title: string;
  roleLabel: string;
  tabs: { id: string; label: string }[];
  activeTab: string;
  onTabChange: (id: string) => void;
  children: ReactNode;
}) {
  return (
    <div className="dashboard-shell">
      <header className="dashboard-topbar">
        <div className="dashboard-title-group">
          <Link to="/" className="dashboard-back">
            <ArrowLeft size={15} /> Chat
          </Link>
          <h1>{title}</h1>
          <Badge tone="accent">{roleLabel}</Badge>
        </div>
      </header>
      {tabs.length > 1 && (
        <nav className="dashboard-tabs">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              className={`dashboard-tab${activeTab === tab.id ? " active" : ""}`}
              onClick={() => onTabChange(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      )}
      <div className="dashboard-body">{children}</div>
    </div>
  );
}

export function ErrorNote({ message }: { message: string | null }) {
  if (!message) return null;
  return <div className="dashboard-error">{message}</div>;
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleString();
}
