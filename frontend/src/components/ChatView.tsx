import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Code2, Menu } from "lucide-react";
import { chatsApi, messagesApi } from "../api/chats";
import { ApiError } from "../api/client";
import { workspacesApi } from "../api/workspaces";
import type { ChatSummary, ILAGenerateParams, MessageOut, ModelInfo, StreamEvent } from "../api/types";
import { MessageBubble } from "./MessageBubble";
import { Composer } from "./Composer";
import { EditBox } from "./EditBox";
import { ModelSelector } from "./ModelSelector";

export function ChatView({
  chat,
  models,
  onChatUpdated,
  onAfterExchange,
  onOpenSidebar,
}: {
  chat: ChatSummary;
  models: ModelInfo[];
  onChatUpdated: (chat: ChatSummary) => void;
  onAfterExchange: () => void;
  onOpenSidebar: () => void;
}) {
  const [messages, setMessages] = useState<MessageOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [pendingUserContent, setPendingUserContent] = useState<string | null>(null);
  const [streamingContent, setStreamingContent] = useState<string | null>(null);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [workspaceConnecting, setWorkspaceConnecting] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  async function loadHistory() {
    setLoading(true);
    setError(null);
    try {
      const result = await chatsApi.history(chat.id);
      setMessages(result.messages);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't load this chat. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadHistory();
    setEditingId(null);
    return () => abortRef.current?.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chat.id]);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [messages, streamingContent, pendingUserContent]);

  async function runStream(fn: (onEvent: (e: StreamEvent) => void, signal: AbortSignal) => Promise<void>) {
    setBusy(true);
    setStreamError(null);
    setStreamingContent("");
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      await fn((event) => {
        if (!event.is_final) {
          setStreamingContent((prev) => (prev ?? "") + event.delta);
        } else if (event.finish_reason === "error") {
          setStreamError("The assistant couldn't generate a response. Please try again.");
        }
      }, controller.signal);
    } catch (err) {
      setStreamError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setStreamingContent(null);
      setPendingUserContent(null);
      setBusy(false);
      await loadHistory();
      onAfterExchange();
    }
  }

  // ILA doesn't support streaming yet (backend rejects stream: true
  // for agent-mode chats — see conversation_service.prepare_send_stream).
  // Same pending/busy/reload lifecycle as runStream, just without SSE
  // events to accumulate.
  async function runNonStreaming(fn: () => Promise<unknown>) {
    setBusy(true);
    setStreamError(null);
    try {
      await fn();
    } catch (err) {
      setStreamError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setPendingUserContent(null);
      setBusy(false);
      await loadHistory();
      onAfterExchange();
    }
  }

  function handleSend(content: string, ila?: ILAGenerateParams) {
    setPendingUserContent(content);
    if (chat.agent_key) {
      void runNonStreaming(() => chatsApi.sendMessage(chat.id, content, ila));
    } else {
      void runStream((onEvent, signal) => chatsApi.streamMessage(chat.id, content, onEvent, signal));
    }
  }

  function handleEdit(messageId: string, content: string) {
    setEditingId(null);
    void runStream((onEvent, signal) => messagesApi.editStream(messageId, content, onEvent, signal));
  }

  function handleRegenerate(messageId: string) {
    void runStream((onEvent, signal) => messagesApi.regenerateStream(messageId, onEvent, signal));
  }

  async function handleModelChange(modelKey: string) {
    try {
      const updated = await chatsApi.update(chat.id, { model_key: modelKey });
      onChatUpdated(updated);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't change the model.");
    }
  }

  async function handleOpenVsCode() {
    setWorkspaceConnecting(true);
    setError(null);
    try {
      // connect() sets the auth cookie connect_url's path relies on
      // (see api/workspaces.ts) before this resolves; cookies are
      // scoped to origin+path in the browser's cookie jar, not to a
      // tab, so the new tab opened below picks it up automatically.
      // connect_url is same-origin (served via the same Nginx origin
      // as this app in the documented deployment) — an absolute
      // cross-origin VITE_API_BASE_URL isn't supported by this
      // navigation yet.
      const workspace = await workspacesApi.connect(chat.id);
      window.open(workspace.connect_url, "_blank", "noopener,noreferrer");
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Couldn't connect to the workspace. Please try again.",
      );
    } finally {
      setWorkspaceConnecting(false);
    }
  }

  return (
    <div className="chat-pane">
      <header className="chat-header">
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", minWidth: 0 }}>
          <button className="mobile-menu-btn" onClick={onOpenSidebar} aria-label="Open sidebar">
            <Menu size={18} />
          </button>
          <span className="chat-title-display">{chat.title}</span>
        </div>
        {chat.agent_key ? (
          // Not another model — an ILA-session action (ADR 0012).
          <button
            className="open-vscode-btn"
            onClick={() => void handleOpenVsCode()}
            disabled={workspaceConnecting}
            title="Open this session's engineering workspace in VS Code"
          >
            <Code2 size={14} />
            {workspaceConnecting ? "Connecting…" : "Open VS Code"}
          </button>
        ) : (
          <ModelSelector
            models={models.filter((m) => m.category !== "AGENT")}
            selectedKey={chat.model_key}
            onSelect={handleModelChange}
            disabled={busy}
          />
        )}
      </header>

      <div className="message-list" ref={listRef}>
        <div className="message-list-inner">
          {loading && (
            <div className="loading-center">
              <span className="spinner" /> Loading conversation…
            </div>
          )}

          {!loading && messages.length === 0 && !pendingUserContent && (
            <div className="empty-state">
              <h2>Start the conversation</h2>
              <p>Send a prompt below to get a response from {chat.model_key}.</p>
            </div>
          )}

          {!loading &&
            messages.map((message) =>
              editingId === message.id ? (
                <div key={message.id} className="message-block role-user">
                  <span className="message-role-label">You</span>
                  <EditBox
                    initialContent={message.content}
                    busy={busy}
                    onCancel={() => setEditingId(null)}
                    onSubmit={(content) => handleEdit(message.id, content)}
                  />
                </div>
              ) : (
                <MessageBubble
                  key={message.id}
                  message={message}
                  busy={busy}
                  onEdit={message.role === "USER" && message.is_active ? () => setEditingId(message.id) : undefined}
                  onRegenerate={
                    message.role === "ASSISTANT" && message.is_active ? () => handleRegenerate(message.id) : undefined
                  }
                  onRevisionChanged={() => void loadHistory()}
                />
              ),
            )}

          {pendingUserContent != null && (
            <div className="message-block role-user">
              <span className="message-role-label">You</span>
              <div className="message-bubble">
                <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{pendingUserContent}</p>
              </div>
            </div>
          )}

          {streamingContent != null && (
            <div className="message-block role-assistant">
              <span className="message-role-label">{chat.model_key}</span>
              <div className={`message-bubble${streamingContent === "" ? " streaming" : ""}`}>
                {streamingContent === "" ? (
                  <span className="thinking-row">
                    <span className="spinner" /> Thinking…
                  </span>
                ) : (
                  <span className="streaming-content">{streamingContent}</span>
                )}
              </div>
            </div>
          )}

          {streamError && (
            <div className="error-banner">
              <AlertTriangle size={15} />
              {streamError}
              <button onClick={() => setStreamError(null)}>Dismiss</button>
            </div>
          )}

          {error && (
            <div className="error-banner">
              <AlertTriangle size={15} />
              {error}
              <button onClick={() => void loadHistory()}>Retry</button>
            </div>
          )}
        </div>
      </div>

      <div className="composer-wrap">
        <Composer onSend={handleSend} disabled={busy || loading} ilaMode={!!chat.agent_key} />
      </div>
    </div>
  );
}
