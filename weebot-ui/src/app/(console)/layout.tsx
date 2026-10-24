import { ConsoleShell } from "@/components/shell/ConsoleShell";

/** The conversation routes share one persistent shell; it mounts once and survives navigation. */
export default function ConsoleLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <ConsoleShell>{children}</ConsoleShell>;
}
