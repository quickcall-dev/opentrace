"use client";

import { memo, useState } from "react";
import { CheckIcon, CopyIcon } from "lucide-react";
import { TooltipIconButton } from "@/components/tooltip-icon-button";
import { cn } from "@/lib/utils";

const useCopyToClipboard = ({ copiedDuration = 3000 } = {}) => {
  const [isCopied, setIsCopied] = useState(false);
  const copyToClipboard = (value: string) => {
    if (!value) return;
    navigator.clipboard.writeText(value).then(() => {
      setIsCopied(true);
      setTimeout(() => setIsCopied(false), copiedDuration);
    });
  };
  return { isCopied, copyToClipboard };
};

function CodeHeader({ language, code }: { language?: string; code?: string }) {
  const { isCopied, copyToClipboard } = useCopyToClipboard();
  return (
    <div className="mt-4 flex items-center justify-between gap-4 rounded-t-lg bg-muted-foreground/15 px-4 py-2 text-sm font-semibold text-foreground dark:bg-muted-foreground/20">
      <span className="lowercase text-xs">{language}</span>
      <TooltipIconButton
        tooltip="Copy"
        onClick={() => code && !isCopied && copyToClipboard(code)}
      >
        {isCopied ? <CheckIcon /> : <CopyIcon />}
      </TooltipIconButton>
    </div>
  );
}

interface MarkdownTextProps {
  content: string;
  className?: string;
}

function MarkdownTextImpl({ content, className }: MarkdownTextProps) {
  // Simple markdown-like rendering: code blocks, inline code, paragraphs
  const parts = content.split(/(```[\s\S]*?```)/g);

  return (
    <div className={cn("prose prose-sm dark:prose-invert max-w-none", className)}>
      {parts.map((part, i) => {
        if (part.startsWith("```")) {
          const match = part.match(/^```(\w*)\n?([\s\S]*?)```$/);
          const lang = match?.[1] || "";
          const code = match?.[2] || part.slice(3, -3);
          return (
            <div key={i}>
              <CodeHeader language={lang} code={code} />
              <pre className="overflow-x-auto !rounded-t-none rounded-b-lg bg-black p-4 text-white text-xs">
                <code>{code}</code>
              </pre>
            </div>
          );
        }
        return (
          <div key={i} className="leading-7 [&>p]:mt-2 [&>p]:first:mt-0">
            {part.split("\n\n").map((para, j) => (
              <p key={j}>{para}</p>
            ))}
          </div>
        );
      })}
    </div>
  );
}

export const MarkdownText = memo(MarkdownTextImpl);
MarkdownText.displayName = "MarkdownText";
