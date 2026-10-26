"use client";

/**
 * CommandPalette — ⌘K launcher over the shared command registry.
 * Every action here is also reachable however else it's registered
 * (toolbar button, keybinding) — this is just another surface for the
 * same Command objects, not a separate feature.
 *
 * Built on the Dialog primitive (Escape, focus trap, `aria-modal`, focus return) with the
 * ARIA combobox pattern: DOM focus stays in the input and `aria-activedescendant` points at
 * the highlighted option.
 */

import { useEffect, useMemo, useState } from "react";
import { Search } from "lucide-react";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { useCommandList } from "@/hooks/useRegisterCommands";
import { cn } from "@/lib/utils";

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
}

const LISTBOX_ID = "command-palette-list";
const optionId = (id: string) => `command-palette-option-${id.replace(/[^\w-]/g, "-")}`;

export function CommandPalette({ open, onClose }: CommandPaletteProps) {
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent
        showCloseButton={false}
        className="top-[15dvh] gap-0 -translate-y-0 bg-surface-2 p-0 sm:max-w-lg"
      >
        <DialogTitle className="sr-only">Command palette</DialogTitle>
        {/* Unmounted with the popup, so every open starts with a fresh query and selection. */}
        <PaletteBody onClose={onClose} />
      </DialogContent>
    </Dialog>
  );
}

function PaletteBody({ onClose }: Pick<CommandPaletteProps, "onClose">) {
  const commands = useCommandList();
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return commands;
    return commands.filter((c) => c.title.toLowerCase().includes(q));
  }, [commands, query]);

  const active = filtered[activeIndex];

  useEffect(() => {
    if (active) document.getElementById(optionId(active.id))?.scrollIntoView({ block: "nearest" });
  }, [active]);

  const run = (command: (typeof filtered)[number] | undefined) => {
    if (!command) return;
    command.run();
    onClose();
  };

  return (
    <>
      <div className="flex items-center gap-2 border-b px-3 py-2.5">
        <Search className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
        <input
          role="combobox"
          aria-expanded="true"
          aria-controls={LISTBOX_ID}
          aria-autocomplete="list"
          aria-activedescendant={active ? optionId(active.id) : undefined}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setActiveIndex(0);
          }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setActiveIndex((i) => Math.min(i + 1, filtered.length - 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setActiveIndex((i) => Math.max(i - 1, 0));
            } else if (e.key === "Enter" && !e.nativeEvent.isComposing) {
              e.preventDefault();
              run(active);
            }
          }}
          placeholder="Type a command…"
          className="flex-1 bg-transparent text-sm outline-hidden placeholder:text-muted-foreground"
          aria-label="Search commands"
        />
      </div>
      <ul id={LISTBOX_ID} role="listbox" aria-label="Commands" className="max-h-80 overflow-y-auto p-1.5">
        {filtered.length === 0 ? (
          <li role="presentation" className="px-3 py-6 text-center text-sm text-muted-foreground">
            No matching commands.
          </li>
        ) : (
          filtered.map((command, i) => (
            <li
              key={command.id}
              id={optionId(command.id)}
              role="option"
              aria-selected={i === activeIndex}
              onClick={() => run(command)}
              onMouseEnter={() => setActiveIndex(i)}
              className={cn(
                "flex w-full cursor-pointer items-center justify-between rounded-md px-3 py-2 text-left text-sm transition-colors",
                i === activeIndex ? "bg-agent/15 text-foreground" : "text-muted-foreground hover:bg-surface-3"
              )}
            >
              <span>{command.title}</span>
              {command.shortcut && <span className="text-xs text-muted-foreground">{command.shortcut}</span>}
            </li>
          ))
        )}
      </ul>
    </>
  );
}
