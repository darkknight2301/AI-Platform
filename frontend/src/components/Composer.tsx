import { useRef, useState, type KeyboardEvent } from "react";
import { ArrowUp } from "lucide-react";

export function Composer({
  onSend,
  disabled,
  placeholder = "Message the assistant...",
}: {
  onSend: (content: string) => void;
  disabled?: boolean;
  placeholder?: string;
}) {
  const [value, setValue] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  function submit() {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
    requestAnimationFrame(() => {
      if (ref.current) ref.current.style.height = "auto";
    });
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  function autoGrow() {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }

  return (
    <div className="composer">
      <div className="composer-box">
        <textarea
          ref={ref}
          value={value}
          placeholder={placeholder}
          rows={1}
          disabled={disabled}
          onChange={(e) => {
            setValue(e.target.value);
            autoGrow();
          }}
          onKeyDown={onKeyDown}
        />
        <button className="send-btn" onClick={submit} disabled={disabled || !value.trim()} aria-label="Send message">
          <ArrowUp size={16} />
        </button>
      </div>
      <div className="composer-hint">Enter to send · Shift+Enter for a new line</div>
    </div>
  );
}
