import "./style.css";
import { config } from "./config";

interface HealthResponse {
  status: string;
  environment: string;
  version: string;
}

async function fetchHealth(): Promise<HealthResponse | null> {
  try {
    const response = await fetch(`${config.apiBaseUrl}/health`);
    if (!response.ok) return null;
    return (await response.json()) as HealthResponse;
  } catch {
    return null;
  }
}

function render(status: string) {
  const app = document.querySelector<HTMLDivElement>("#app");
  if (!app) return;
  app.innerHTML = `
    <main class="foundation">
      <h1>AI Platform — Foundation</h1>
      <p>Backend status: <strong>${status}</strong></p>
    </main>
  `;
}

render("checking...");
fetchHealth().then((health) => {
  render(health ? `${health.status} (${health.environment})` : "unreachable");
});
