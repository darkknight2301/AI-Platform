import { useState, type FormEvent } from "react";
import { useNavigate, Link, useLocation } from "react-router-dom";
import { ApiError } from "../api/client";
import { useAuth } from "../context/AuthContext";

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation() as { state?: { registered?: boolean } };
  const [usernameOrEmail, setUsernameOrEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setPending(false);
    setSubmitting(true);
    try {
      await login(usernameOrEmail, password);
      navigate("/", { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setPending(true);
      } else if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("Couldn't sign in. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-shell">
      <div className="auth-card">
        <div className="auth-brand">AI Platform</div>
        <h1>Sign in</h1>

        {location.state?.registered && !pending && !error && (
          <div className="auth-notice success">
            Account created. It needs manager approval before you can sign in.
          </div>
        )}
        {pending && (
          <div className="auth-notice pending">
            Your account is pending manager approval. You'll be able to sign in once it's approved.
          </div>
        )}
        {error && <div className="auth-notice error">{error}</div>}

        <form onSubmit={onSubmit}>
          <div className="field">
            <label htmlFor="usernameOrEmail">Username or email</label>
            <input
              id="usernameOrEmail"
              value={usernameOrEmail}
              onChange={(e) => setUsernameOrEmail(e.target.value)}
              autoComplete="username"
              required
            />
          </div>
          <div className="field">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </div>
          <button className="btn btn-primary auth-submit" type="submit" disabled={submitting}>
            {submitting && <span className="spinner on-dark" />}
            Sign in
          </button>
        </form>

        <div className="auth-switch">
          Need an account? <Link to="/register">Register</Link>
        </div>
      </div>
    </div>
  );
}
