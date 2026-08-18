import { useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import type { ModelInfo } from "../api/types";

export function ModelSelector({
  models,
  selectedKey,
  onSelect,
  disabled,
}: {
  models: ModelInfo[];
  selectedKey: string | null;
  onSelect: (modelKey: string) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const selected = models.find((m) => m.model_key === selectedKey);

  useEffect(() => {
    function onClickAway(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickAway);
    return () => document.removeEventListener("mousedown", onClickAway);
  }, []);

  return (
    <div className="model-selector" ref={ref}>
      <button
        className="model-selector-btn"
        onClick={() => setOpen((v) => !v)}
        disabled={disabled || models.length === 0}
      >
        {selected ? selected.display_name : models.length === 0 ? "No models available" : "Select a model"}
        <ChevronDown size={14} />
      </button>
      {open && (
        <div className="model-menu">
          {models.map((m) => (
            <button
              key={m.model_key}
              onClick={() => {
                onSelect(m.model_key);
                setOpen(false);
              }}
            >
              <span className="name">{m.display_name}</span>
              <span className="meta">
                <span className="model-badge">{m.category}</span> · {m.model_key}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
