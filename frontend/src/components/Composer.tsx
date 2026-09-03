import { useRef, useState, type KeyboardEvent } from "react";
import { ArrowUp } from "lucide-react";
import type { ILAGenerateParams } from "../api/types";

export function Composer({
  onSend,
  disabled,
  placeholder = "Message the assistant...",
  ilaMode = false,
}: {
  onSend: (content: string, ila?: ILAGenerateParams) => void;
  disabled?: boolean;
  placeholder?: string;
  // ILA's fixed generate() signature needs structured params beyond
  // plain text (mode/function_name/step/output_file are required,
  // not guessed — see backend schemas/message.py's
  // SendMessageRequest.ila docstring). Only rendered for agent-mode
  // chats; an ordinary model chat's Composer is unchanged.
  ilaMode?: boolean;
}) {
  const [value, setValue] = useState("");
  const [functionName, setFunctionName] = useState("");
  const [step, setStep] = useState("");
  const [outputFile, setOutputFile] = useState("");
  const [testCaseDesc, setTestCaseDesc] = useState("");
  const [mode, setMode] = useState("generate");
  const [overwriteStep, setOverwriteStep] = useState(false);
  const ref = useRef<HTMLTextAreaElement>(null);

  const ilaFieldsValid = !ilaMode || (functionName.trim() && step.trim() && outputFile.trim());

  function submit() {
    const trimmed = value.trim();
    if (!trimmed || disabled || !ilaFieldsValid) return;

    if (ilaMode) {
      onSend(trimmed, {
        mode,
        function_name: functionName.trim(),
        step: step.trim(),
        test_case_desc: testCaseDesc.trim() || undefined,
        overwrite_step: overwriteStep,
        output_file: outputFile.trim(),
      });
    } else {
      onSend(trimmed);
    }

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
      {ilaMode && (
        <div className="composer-ila-fields">
          <div className="composer-ila-row">
            <input
              type="text"
              placeholder="Function name *"
              value={functionName}
              disabled={disabled}
              onChange={(e) => setFunctionName(e.target.value)}
            />
            <input
              type="text"
              placeholder="Step *"
              value={step}
              disabled={disabled}
              onChange={(e) => setStep(e.target.value)}
            />
            <input
              type="text"
              placeholder="Output file *"
              value={outputFile}
              disabled={disabled}
              onChange={(e) => setOutputFile(e.target.value)}
            />
          </div>
          <div className="composer-ila-row">
            <input
              type="text"
              placeholder="Mode"
              value={mode}
              disabled={disabled}
              onChange={(e) => setMode(e.target.value)}
            />
            <input
              type="text"
              placeholder="Test case description (optional)"
              value={testCaseDesc}
              disabled={disabled}
              onChange={(e) => setTestCaseDesc(e.target.value)}
            />
            <label className="composer-ila-checkbox">
              <input
                type="checkbox"
                checked={overwriteStep}
                disabled={disabled}
                onChange={(e) => setOverwriteStep(e.target.checked)}
              />
              Overwrite step
            </label>
          </div>
        </div>
      )}
      <div className="composer-box">
        <textarea
          ref={ref}
          value={value}
          placeholder={ilaMode ? "Describe what ILA should generate..." : placeholder}
          rows={1}
          disabled={disabled}
          onChange={(e) => {
            setValue(e.target.value);
            autoGrow();
          }}
          onKeyDown={onKeyDown}
        />
        <button
          className="send-btn"
          onClick={submit}
          disabled={disabled || !value.trim() || !ilaFieldsValid}
          aria-label="Send message"
        >
          <ArrowUp size={16} />
        </button>
      </div>
      <div className="composer-hint">
        {ilaMode ? "* required — Enter to send · Shift+Enter for a new line" : "Enter to send · Shift+Enter for a new line"}
      </div>
    </div>
  );
}
