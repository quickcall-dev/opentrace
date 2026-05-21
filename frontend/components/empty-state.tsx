"use client";

import { cn } from "@/lib/utils";
import { Copy, Check } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { type ReactNode, useState, useCallback } from "react";

interface EmptyStateProps {
  icon?: LucideIcon;
  title: string;
  description?: string;
  action?: ReactNode;
  className?: string;
  installCommand?: string;
  learnMoreHref?: string;
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
  installCommand,
  learnMoreHref,
}: EmptyStateProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(() => {
    if (!installCommand) return;
    navigator.clipboard.writeText(installCommand).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }, [installCommand]);

  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center py-12 text-center",
        className,
      )}
    >
      {Icon && (
        <Icon className="size-10 text-muted-foreground/50 mb-3" />
      )}
      <h3 className="text-sm font-medium text-foreground mb-1">
        {title}
      </h3>
      {description && (
        <p className="text-sm text-muted-foreground max-w-sm">
          {description}
        </p>
      )}
      {installCommand && (
        <div className="mt-4 relative group">
          <pre className="bg-muted text-xs text-foreground rounded-lg px-4 py-3 pr-10 font-mono select-all">
            {installCommand}
          </pre>
          <button
            type="button"
            onClick={handleCopy}
            className="absolute top-2 right-2 p-1 rounded text-muted-foreground hover:text-muted-foreground transition-colors"
            aria-label="Copy command"
          >
            {copied ? (
              <Check className="size-4 text-green-500" />
            ) : (
              <Copy className="size-4" />
            )}
          </button>
        </div>
      )}
      {learnMoreHref && (
        <a
          href={learnMoreHref}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-3 text-sm text-foreground underline decoration-muted-foreground/40 hover:decoration-foreground"
        >
          Learn more
        </a>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
