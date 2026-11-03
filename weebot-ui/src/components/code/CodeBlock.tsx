"use client";

import { useEffect, useRef, useState } from "react";
import { Copy, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAnnounce } from "@/providers/AnnouncerProvider";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { vscDarkPlus } from "react-syntax-highlighter/dist/esm/styles/prism";

interface CodeBlockProps {
  code: string;
  language?: string;
  filename?: string;
  showLineNumbers?: boolean;
}

type CopyState = "idle" | "copied" | "failed";

// The block stays dark in both themes (the syntax theme is a dark one): palette tokens, not hex.
export function CodeBlock({
  code,
  language = "python",
  filename,
  showLineNumbers = true,
}: CodeBlockProps) {
  const [copy, setCopy] = useState<CopyState>("idle");
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const announce = useAnnounce();

  useEffect(() => () => clearTimeout(timer.current), []);

  const handleCopy = async () => {
    let next: CopyState = "copied";
    try {
      await navigator.clipboard.writeText(code);
    } catch {
      // Insecure origin, denied permission or no Clipboard API.
      next = "failed";
    }
    setCopy(next);
    announce(next === "copied" ? "Copied" : "Couldn’t copy. Select the code and copy it by hand.");
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopy("idle"), 2000);
  };

  return (
    <div className="overflow-hidden rounded-lg border bg-[hsl(var(--p-ink-850))]">
      <div className="flex items-center justify-between gap-2 border-b bg-[hsl(var(--p-ink-800))] px-4 py-2">
        <span className="min-w-0 truncate text-sm text-[hsl(var(--p-ink-400))]" translate="no" title={filename}>
          {filename}
        </span>
        <Button
          variant="ghost"
          size="sm"
          onClick={handleCopy}
          className="ml-auto h-8 text-[hsl(var(--p-ink-400))] hover:text-[hsl(var(--p-ink-50))]"
        >
          {copy === "copied" ? (
            <Check className="mr-1 h-4 w-4" aria-hidden="true" />
          ) : (
            <Copy className="mr-1 h-4 w-4" aria-hidden="true" />
          )}
          {copy === "copied" ? "Copied" : copy === "failed" ? "Copy failed" : "Copy"}
        </Button>
      </div>
      {/* Focusable so a keyboard user can scroll long lines. */}
      <div
        role="region"
        tabIndex={0}
        aria-label={filename ? `Code: ${filename}` : "Code"}
        translate="no"
        className="focus-ring overflow-auto overscroll-contain"
      >
        <SyntaxHighlighter
          language={language}
          style={vscDarkPlus}
          showLineNumbers={showLineNumbers}
          customStyle={{
            margin: 0,
            padding: "1rem",
            fontSize: "0.875rem",
            background: "transparent",
            overflow: "visible",
          }}
        >
          {code}
        </SyntaxHighlighter>
      </div>
    </div>
  );
}
