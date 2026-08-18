// Generic parser for the backend's common SSE stream format
// (StreamEventOut — see ARCHITECTURE.md "Chat Backend" / ADR 0009).
// This is the ONLY place in the frontend that knows how to read a
// stream; it has no idea which model produced it. Callers just get a
// sequence of StreamEvent objects via onEvent.

import { API_BASE, authHeaders, ApiError } from "./client";
import type { StreamEvent } from "./types";

export async function streamPost(
  path: string,
  body: unknown,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
    signal,
  });

  if (!response.ok || !response.body) {
    let message = `Request failed (${response.status}).`;
    try {
      const data = await response.json();
      if (data?.detail) message = data.detail;
    } catch {
      // response body wasn't JSON (or was empty) — keep the default message
    }
    throw new ApiError(response.status, message);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const block = buffer.slice(0, boundary).trim();
      buffer = buffer.slice(boundary + 2);
      if (block.startsWith("data:")) {
        const raw = block.slice("data:".length).trim();
        if (raw) {
          try {
            onEvent(JSON.parse(raw) as StreamEvent);
          } catch {
            // malformed line — skip rather than kill the whole stream
          }
        }
      }
      boundary = buffer.indexOf("\n\n");
    }
  }
}
