import { useCallback, useEffect, useState } from "react";
import { chatsApi, modelsApi } from "../api/chats";
import { quotaApi } from "../api/quota";
import { ApiError } from "../api/client";
import { useAuth } from "../context/AuthContext";
import type { ChatSummary, ModelInfo, QuotaStatusResponse } from "../api/types";
import { Sidebar } from "../components/Sidebar";
import { ChatView } from "../components/ChatView";

export function ChatPage() {
  const { user, logout } = useAuth();
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [quota, setQuota] = useState<QuotaStatusResponse | null>(null);
  const [activeChatId, setActiveChatId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [initializing, setInitializing] = useState(true);

  const refreshChats = useCallback(async () => {
    const result = await chatsApi.list();
    setChats(result.chats);
    return result.chats;
  }, []);

  const refreshQuota = useCallback(async () => {
    try {
      setQuota(await quotaApi.mine());
    } catch {
      // usage panel is a nice-to-have; a transient failure shouldn't block the chat UI
    }
  }, []);

  useEffect(() => {
    void (async () => {
      setInitializing(true);
      try {
        const [chatList] = await Promise.all([
          refreshChats(),
          modelsApi.list().then((r) => setModels(r.models)),
          refreshQuota(),
        ]);
        if (chatList.length > 0) setActiveChatId(chatList[0].id);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Couldn't load your workspace. Please refresh.");
      } finally {
        setInitializing(false);
      }
    })();
  }, [refreshChats, refreshQuota]);

  async function handleNewChat() {
    if (models.length === 0) {
      setError("No models are available yet. Ask an administrator to enable one.");
      return;
    }
    try {
      const selectableModels = models.filter((m) => m.category !== "AGENT");
      if (selectableModels.length === 0) {
        setError("No models are available yet. Ask an administrator to enable one.");
        return;
      }
      const chat = await chatsApi.create({ model_key: selectableModels[0].model_key });
      setChats((prev) => [chat, ...prev]);
      setActiveChatId(chat.id);
      setSidebarOpen(false);
      void refreshQuota();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Couldn't create a new chat. Please try again.",
      );
    }
  }

  async function handleNewAgentChat() {
    const agentModel = models.find((m) => m.category === "AGENT");
    if (!agentModel) {
      setError("The ILA agent is not currently available.");
      return;
    }
    try {
      const chat = await chatsApi.create({ agent_key: agentModel.model_key });
      setChats((prev) => [chat, ...prev]);
      setActiveChatId(chat.id);
      setSidebarOpen(false);
      void refreshQuota();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Couldn't create a new ILA chat. Please try again.",
      );
    }
  }

  async function handleRename(id: string, title: string) {
    const updated = await chatsApi.update(id, { title });
    setChats((prev) => prev.map((c) => (c.id === id ? updated : c)));
  }

  async function handleArchive(id: string) {
    const chat = chats.find((c) => c.id === id);
    if (!chat) return;
    const updated = await chatsApi.update(id, {
      status: chat.status === "ARCHIVED" ? "ACTIVE" : "ARCHIVED",
    });
    setChats((prev) => prev.map((c) => (c.id === id ? updated : c)));
  }

  async function handleDelete(id: string) {
    await chatsApi.remove(id);
    setChats((prev) => {
      const next = prev.filter((c) => c.id !== id);
      if (activeChatId === id) {
        setActiveChatId(next[0]?.id ?? null);
      }
      return next;
    });
    void refreshQuota();
  }

  const activeChat = chats.find((c) => c.id === activeChatId) ?? null;
  const chatLimitReached = quota != null && quota.chat_limit.active_chats >= quota.chat_limit.max_active_chats;

  if (initializing) {
    return (
      <div className="loading-center" style={{ height: "100vh" }}>
        <span className="spinner" /> Loading your workspace…
      </div>
    );
  }

  return (
    <div className="app-shell">
      <div className={`sidebar${sidebarOpen ? " open" : ""}`}>
        <Sidebar
          chats={chats}
          activeChatId={activeChatId}
          onSelectChat={(id) => {
            setActiveChatId(id);
            setSidebarOpen(false);
          }}
          onNewChat={handleNewChat}
          onNewAgentChat={() => void handleNewAgentChat()}
          agentAvailable={models.some((m) => m.category === "AGENT")}
          onRename={(id, title) => void handleRename(id, title)}
          onArchive={(id) => void handleArchive(id)}
          onDelete={(id) => void handleDelete(id)}
          newChatDisabled={chatLimitReached}
          quota={quota}
          user={user}
          onLogout={() => void logout()}
        />
      </div>

      {activeChat ? (
        <ChatView
          key={activeChat.id}
          chat={activeChat}
          models={models}
          onChatUpdated={(updated) => setChats((prev) => prev.map((c) => (c.id === updated.id ? updated : c)))}
          onAfterExchange={() => {
            void refreshChats();
            void refreshQuota();
          }}
          onOpenSidebar={() => setSidebarOpen(true)}
        />
      ) : (
        <div className="chat-pane">
          <div className="empty-state" style={{ margin: "auto" }}>
            <h2>No chat selected</h2>
            <p>
              {chatLimitReached
                ? "You've reached your active chat limit. Archive or delete a chat to start a new one."
                : "Create a new chat to get started."}
            </p>
          </div>
        </div>
      )}

      {error && (
        <div className="error-banner" style={{ position: "fixed", bottom: 16, right: 16, maxWidth: 360 }}>
          {error}
          <button onClick={() => setError(null)}>Dismiss</button>
        </div>
      )}
    </div>
  );
}
