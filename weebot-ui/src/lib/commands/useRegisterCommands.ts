"use client";

import { useEffect, useState } from "react";
import { Command, commandRegistry } from "./registry";

/** Registers *commands* for the lifetime of the calling component. */
export function useRegisterCommands(commands: Command[]) {
  useEffect(() => {
    const unregisters = commands.map((c) => commandRegistry.register(c));
    return () => unregisters.forEach((fn) => fn());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(commands.map((c) => c.id))]);
}

/** Reactive read of the current command list — re-renders on register/unregister. */
export function useCommandList(): Command[] {
  const [, forceRender] = useState(0);
  useEffect(() => commandRegistry.subscribe(() => forceRender((n) => n + 1)), []);
  return commandRegistry.list();
}
