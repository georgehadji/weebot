/**
 * Command registry — shared definitions consumed by the ⌘K palette,
 * toolbar buttons, and keybindings alike. One definition, three
 * surfaces, instead of duplicating "what New Session does" in each place.
 */

export interface Command {
  id: string;
  title: string;
  group?: string;
  shortcut?: string;
  /** Only shown/runnable when this returns true. Omit to always show. */
  when?: () => boolean;
  run: () => void;
}

type Listener = () => void;

class CommandRegistry {
  private commands = new Map<string, Command>();
  private listeners = new Set<Listener>();

  register(command: Command): () => void {
    this.commands.set(command.id, command);
    this.notify();
    return () => this.unregister(command.id);
  }

  unregister(id: string): void {
    this.commands.delete(id);
    this.notify();
  }

  list(): Command[] {
    return Array.from(this.commands.values()).filter((c) => !c.when || c.when());
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private notify(): void {
    this.listeners.forEach((l) => l());
  }
}

export const commandRegistry = new CommandRegistry();
