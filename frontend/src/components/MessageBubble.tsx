import { useState } from "react";
import { Check, Copy, Pencil, RotateCcw } from "lucide-react";
import { Markdown } from "./Markdown";
import { RevisionNav } from "./RevisionNav";
import type { MessageOut } from "../api/types";

function CopyMessageButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      className={`icon-btn${copied ? " copied" : ""}`}
      title="Copy message"
      aria-label="Copy message"
      onClick={() => {
        void navigator.clipboard.writeText(text).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        });
      }}
    >
      {copied ? <Check size={14} /> : <Copy size={14} />}
    </button>
  );
}

export function MessageBubble({
  message,
  onEdit,
  onRegenerate,
  onRevisionChanged,
  busy,
}: {
  message: MessageOut;
  onEdit?: () => void;
  onRegenerate?: () => void;
  onRevisionChanged: () => void;
  busy?: boolean;
}) {
  const isUser = message.role === "USER";

  return (
    <div className={`message-block role-${isUser ? "user" : "assistant"}`}>
      <span className="message-role-label">{isUser ? "You" : message.model_key ?? "Assistant"}</span>
      <div className="message-bubble">
        <Markdown content={message.content} />
      </div>
      <div className="message-meta-row">
        {!isUser && message.model_key && <span>Model: {message.model_key}</span>}
        {!isUser && message.response_time_ms != null && (
          <span>Response time: {(message.response_time_ms / 1000).toFixed(2)}s</span>
        )}
        {!isUser && <span>Input tokens: {message.input_tokens.toLocaleString()}</span>}
        {!isUser && <span>Output tokens: {message.output_tokens.toLocaleString()}</span>}
        <div className="message-actions">
          <CopyMessageButton text={message.content} />
          {isUser && onEdit && (
            <button className="icon-btn" title="Edit prompt" aria-label="Edit prompt" onClick={onEdit} disabled={busy}>
              <Pencil size={13} />
            </button>
          )}
          {!isUser && onRegenerate && (
            <button
              className="icon-btn"
              title="Regenerate response"
              aria-label="Regenerate response"
              onClick={onRegenerate}
              disabled={busy}
            >
              <RotateCcw size={13} />
            </button>
          )}
          <RevisionNav message={message} onActivated={onRevisionChanged} />
        </div>
      </div>
    </div>
  );
}
