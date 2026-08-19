import { Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { LoginPage } from "./pages/LoginPage";
import { RegisterPage } from "./pages/RegisterPage";
import { ChatPage } from "./pages/ChatPage";
import { ManagerDashboardPage } from "./pages/ManagerDashboardPage";
import { DeveloperDashboardPage } from "./pages/DeveloperDashboardPage";
import { OwnerDashboardPage } from "./pages/OwnerDashboardPage";

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { status } = useAuth();
  if (status === "loading") {
    return (
      <div className="loading-center" style={{ height: "100vh" }}>
        <span className="spinner" /> Loading…
      </div>
    );
  }
  if (status === "anonymous") return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function RedirectIfAuthed({ children }: { children: React.ReactNode }) {
  const { status } = useAuth();
  if (status === "authenticated") return <Navigate to="/" replace />;
  return <>{children}</>;
}

/** Renders the dashboard for the caller's own role. A User (no elevated
 * role) has no dashboard and is bounced back to chat — this is a UX
 * convenience only, not the security boundary. The backend independently
 * rejects any unauthorized API call regardless of what this component
 * renders (see backend/src/auth/dependencies.py, admin.py, system.py). */
function RoleDashboard() {
  const { user } = useAuth();
  switch (user?.role) {
    case "MANAGER":
      return <ManagerDashboardPage />;
    case "DEVELOPER":
      return <DeveloperDashboardPage />;
    case "OWNER":
      return <OwnerDashboardPage />;
    default:
      return <Navigate to="/" replace />;
  }
}

function AppRoutes() {
  return (
    <Routes>
      <Route
        path="/login"
        element={
          <RedirectIfAuthed>
            <LoginPage />
          </RedirectIfAuthed>
        }
      />
      <Route
        path="/register"
        element={
          <RedirectIfAuthed>
            <RegisterPage />
          </RedirectIfAuthed>
        }
      />
      <Route
        path="/dashboard"
        element={
          <RequireAuth>
            <RoleDashboard />
          </RequireAuth>
        }
      />
      <Route
        path="/"
        element={
          <RequireAuth>
            <ChatPage />
          </RequireAuth>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export function App() {
  return (
    <AuthProvider>
      <AppRoutes />
    </AuthProvider>
  );
}
