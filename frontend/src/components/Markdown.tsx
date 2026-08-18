import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Check, Copy } from "lucide-react";

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      className={`icon-btn${copied ? " copied" : ""}`}
      onClick={() => {
        void navigator.clipboard.writeText(text).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        });
      }}
      aria-label="Copy code"
      title="Copy code"
    >
      {copied ? <Check size={13} /> : <Copy size={13} />}
    </button>
  );
}

export function Markdown({ content }: { content: string }) {
  return (
    <div className="markdown-body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code(props) {
            const { children, className, ...rest } = props;
            const isBlock = /language-(\w+)/.test(className ?? "") || String(children).includes("\n");
            const language = /language-(\w+)/.exec(className ?? "")?.[1];
            const text = String(children).replace(/\n$/, "");

            if (!isBlock) {
              return (
                <code className="inline-code" {...rest}>
                  {children}
                </code>
              );
            }

            return (
              <span className="code-block">
                <span className="code-block-header">
                  <span>{language ?? "text"}</span>
                  <CopyButton text={text} />
                </span>
                <pre>
                  <code className={className} {...rest}>
                    {children}
                  </code>
                </pre>
              </span>
            );
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
