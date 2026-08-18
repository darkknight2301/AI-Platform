import { useState } from "react";

export function EditBox({
  initialContent,
  onSubmit,
  onCancel,
  busy,
}: {
  initialContent: string;
  onSubmit: (content: string) => void;
  onCancel: () => void;
  busy?: boolean;
}) {
  const [value, setValue] = useState(initialContent);

  return (
    <div className="edit-box">
      <textarea value={value} onChange={(e) => setValue(e.target.value)} disabled={busy} autoFocus />
      <div className="edit-box-actions">
        <button className="btn btn-secondary" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
        <button
          className="btn btn-primary"
          disabled={busy || !value.trim()}
          onClick={() => onSubmit(value.trim())}
        >
          Save &amp; regenerate
        </button>
      </div>
    </div>
  );
}
