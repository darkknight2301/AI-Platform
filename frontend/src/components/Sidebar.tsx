import { useEffect, useRef, useState } from "react";
import { Archive, LogOut, MessageSquarePlus, MoreHorizontal, Pencil, Search, Trash2 } from "lucide-react";
import type { ChatSummary, QuotaStatusResponse, UserPublic } from "../api/types";
import { UsagePanel } from "./UsagePanel";

export function Sidebar({
  chats,
  activeChatId,
  onSelectChat,
  onNewChat,
  onRename,
  onArchive,
  onDelete,
  newChatDisabled,
  quota,
  user,
  onLogout,
}: {
  chats: ChatSummary[];
  activeChatId: string | null;
  onSelectChat: (id: string) => void;
  onNewChat: () => void;
  onRename: (id: string, title: string) => void;
  onArchive: (id: string) => void;
  onDelete: (id: string) => void;
  newChatDisabled: boolean;
  quota: QuotaStatusResponse | null;
  user: UserPublic | null;
  onLogout: () => void;
}) {
  const [search, setSearch] = useState("");
  const [menuOpenFor, setMenuOpenFor] = useState<string | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onClickAway(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpenFor(null);
    }
    document.addEventListener("mousedown", onClickAway);
    return () => document.removeEventListener("mousedown", onClickAway);
  }, []);

  const visibleChats = chats.filter((c) => c.title.toLowerCase().includes(search.toLowerCase()));

  return (
    <aside className="sidebar" id="sidebar">
      <div className="sidebar-brand">
        <strong>AI Platform</strong>
      </div>

      <button className="new-chat-btn" onClick={onNewChat} disabled={newChatDisabled}>
        <MessageSquarePlus size={16} />
        New chat
      </button>

      <div className="sidebar-search">
        <Search size={14} />
        <input
          placeholder="Search chats"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label="Search chats"
        />
      </div>

      <nav className="chat-list">
        {visibleChats.length === 0 && (
          <div className="empty-chat-list">{search ? "No chats match your search." : "No chats yet."}</div>
        )}
        {visibleChats.map((chat) => (
          <div
            key={chat.id}
            className={`chat-list-item${chat.id === activeChatId ? " active" : ""}`}
            onClick={() => renamingId !== chat.id && onSelectChat(chat.id)}
          >
            {renamingId === chat.id ? (
              <input
                className="title-input"
                value={renameValue}
                autoFocus
                onClick={(e) => e.stopPropagation()}
                onChange={(e) => setRenameValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    onRename(chat.id, renameValue.trim() || chat.title);
                    setRenamingId(null);
                  } else if (e.key === "Escape") {
                    setRenamingId(null);
                  }
                }}
                onBlur={() => setRenamingId(null)}
              />
            ) : (
              <span className="title">{chat.title}</span>
            )}

            <button
              className={`menu-btn${menuOpenFor === chat.id ? " open" : ""}`}
              onClick={(e) => {
                e.stopPropagation();
                setMenuOpenFor(menuOpenFor === chat.id ? null : chat.id);
              }}
              aria-label="Chat options"
            >
              <MoreHorizontal size={15} />
            </button>

            {menuOpenFor === chat.id && (
              <div className="chat-menu" ref={menuRef} onClick={(e) => e.stopPropagation()}>
                <button
                  onClick={() => {
                    setRenamingId(chat.id);
                    setRenameValue(chat.title);
                    setMenuOpenFor(null);
                  }}
                >
                  <Pencil size={13} /> Rename
                </button>
                <button
                  onClick={() => {
                    onArchive(chat.id);
                    setMenuOpenFor(null);
                  }}
                >
                  <Archive size={13} /> {chat.status === "ARCHIVED" ? "Unarchive" : "Archive"}
                </button>
                <button
                  className="danger"
                  onClick={() => {
                    onDelete(chat.id);
                    setMenuOpenFor(null);
                  }}
                >
                  <Trash2 size={13} /> Delete
                </button>
              </div>
            )}
          </div>
        ))}
      </nav>

      <UsagePanel quota={quota} />

      {user && (
        <div className="user-footer-row" style={{ padding: "0 0.85rem 0.85rem" }}>
          <span className="user-footer-name">{user.username}</span>
          <button className="logout-btn" onClick={onLogout} title="Log out" aria-label="Log out">
            <LogOut size={15} />
          </button>
        </div>
      )}
    </aside>
  );
}
