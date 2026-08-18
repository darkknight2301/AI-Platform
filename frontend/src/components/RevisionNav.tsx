import { ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";
import { messagesApi } from "../api/chats";
import type { MessageOut } from "../api/types";

/** Undo/redo for a single message slot: steps through its revisions
 * (v1, v2, v3, ...) by calling `POST /messages/{id}/activate` on the
 * neighboring revision — the server-persisted undo/redo primitive
 * (see ADR 0009/0010). Only rendered when a message has more than one
 * revision. */
export function RevisionNav({
  message,
  onActivated,
}: {
  message: MessageOut;
  onActivated: () => void;
}) {
  const [busy, setBusy] = useState(false);

  if (message.revision_count <= 1) return null;

  async function step(direction: -1 | 1) {
    setBusy(true);
    try {
      const { revisions } = await messagesApi.revisions(message.id);
      const sorted = [...revisions].sort((a, b) => a.revision - b.revision);
      const currentIndex = sorted.findIndex((r) => r.id === message.id);
      const targetIndex = currentIndex + direction;
      if (targetIndex < 0 || targetIndex >= sorted.length) return;
      await messagesApi.activate(sorted[targetIndex].id);
      onActivated();
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="revision-nav">
      <button
        className="icon-btn"
        disabled={busy || message.revision <= 1}
        onClick={() => void step(-1)}
        aria-label="Undo (previous revision)"
        title="Undo"
      >
        <ChevronLeft size={13} />
      </button>
      {message.revision}/{message.revision_count}
      <button
        className="icon-btn"
        disabled={busy || message.revision >= message.revision_count}
        onClick={() => void step(1)}
        aria-label="Redo (next revision)"
        title="Redo"
      >
        <ChevronRight size={13} />
      </button>
    </span>
  );
}
