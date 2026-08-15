/**
 * Frontend configuration.
 *
 * Reads from Vite env variables (VITE_*), which are inlined at build
 * time. No secrets belong here — this is client-side code and is
 * always readable by end users. Server-side secrets stay in the
 * Python backend's environment.
 */
export const config = {
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL ?? "/api/v1",
};
