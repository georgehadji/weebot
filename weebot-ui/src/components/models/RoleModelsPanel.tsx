"use client";

import { useCallback, useState } from "react";
import { StateView } from "@/components/common/StateView";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useRemote } from "@/hooks/useRemote";
import { api } from "@/lib/api";
import { ModelInfo, RoleModel } from "@/types/events";

const SUBAGENT_ROLES = new Set(["subagent", "planner_sub"]);

/** Ids that do not read well as "id with underscores replaced". */
const ROLE_LABELS: Record<string, string> = {
  planner_sub: "Planner (sub-agent)",
  subagent: "Sub-agent",
};

const roleLabel = (role: string) =>
  ROLE_LABELS[role] ?? role.charAt(0).toUpperCase() + role.slice(1).replace(/_/g, " ");

/** The Select's value for "no override"; an empty string would read as "nothing chosen". */
const DEFAULT = "__default__";

/** Models grouped by provider, so a long catalog stays scannable in a dropdown. */
function groupByProvider(models: ModelInfo[]): [string, ModelInfo[]][] {
  const groups = new Map<string, ModelInfo[]>();
  for (const m of models) groups.set(m.provider, [...(groups.get(m.provider) ?? []), m]);
  return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b));
}

function RoleRow({
  row,
  models,
  onChange,
}: {
  row: RoleModel;
  models: ModelInfo[];
  onChange: (role: string, model: string) => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const id = `role-model-${row.role}`;
  const errorId = `${id}-error`;
  const label = roleLabel(row.role);

  const change = async (model: string) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await onChange(row.role, model);
    } catch (e) {
      const reason = e instanceof Error ? e.message : "unknown error";
      setError(`Couldn’t save this model (${reason}). Try again, or reload the page if it keeps failing.`);
    } finally {
      setBusy(false);
    }
  };

  const fallback = row.default[0];
  const defaultLabel = fallback
    ? `Default · ${models.find((m) => m.id === fallback)?.name ?? fallback}`
    : "Default";
  const labels: Record<string, string> = { [DEFAULT]: defaultLabel };
  for (const m of models) labels[m.id] = m.name;

  return (
    <li className="flex flex-col gap-1 border-b py-3 last:border-b-0 sm:flex-row sm:items-center sm:gap-4">
      <label htmlFor={id} className="min-w-0 sm:w-48">
        <span className="block text-sm font-medium">{label}</span>
        <span className="block truncate font-mono text-xs text-muted-foreground">
          {row.override ? "your pick" : "default"}
        </span>
      </label>
      {/* readOnly + aria-busy while saving, never `disabled`: that would drop keyboard focus. */}
      <Select
        value={row.override ?? DEFAULT}
        items={labels}
        readOnly={busy}
        onValueChange={(v) => void change(v === null || v === DEFAULT ? "" : v)}
      >
        <SelectTrigger
          id={id}
          aria-busy={busy || undefined}
          aria-disabled={busy || undefined}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? errorId : undefined}
          className="min-w-0 flex-1"
        >
          <SelectValue translate="no">{(v: string) => labels[v] ?? v}</SelectValue>
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={DEFAULT}>{defaultLabel}</SelectItem>
          {groupByProvider(models).map(([provider, group]) => (
            <SelectGroup key={provider}>
              <SelectLabel>{provider}</SelectLabel>
              {group.map((m) => (
                <SelectItem key={m.id} value={m.id}>
                  <span translate="no">{m.name}</span>
                </SelectItem>
              ))}
            </SelectGroup>
          ))}
        </SelectContent>
      </Select>
      <Button
        variant="ghost"
        size="sm"
        loading={busy}
        aria-disabled={!row.override || busy || undefined}
        onClick={() => row.override && void change("")}
        aria-label={`Reset ${label} to default`}
        className="aria-disabled:opacity-50"
      >
        Reset
      </Button>
      {error && (
        <p id={errorId} role="alert" className="text-xs text-status-error-fg sm:basis-full">
          {error}
        </p>
      )}
    </li>
  );
}

/** Pick the model each agent role (and the sub-agent roles) tries first. */
export function RoleModelsPanel({ models }: { models: ModelInfo[] }) {
  const load = useCallback(() => api.models.roles(), []);
  const { state, reload } = useRemote(load);

  const onChange = useCallback(
    async (role: string, model: string) => {
      if (model) await api.models.setRole(role, model);
      else await api.models.resetRole(role);
      reload();
    },
    [reload]
  );

  return (
    <Card className="mb-8">
      <CardHeader>
        <CardTitle className="text-xl">Agent models</CardTitle>
        <p className="text-sm text-muted-foreground">
          The model each role tries first. The built-in fallbacks stay behind your pick, so a
          failing model still falls through. Applies to new runs.
        </p>
      </CardHeader>
      <CardContent>
        <StateView
          state={state}
          errorTitle="Couldn't load agent roles"
          loadingLabel="Loading agent roles"
          onRetry={reload}
        >
          {(rows) => {
            const agents = rows.filter((r) => !SUBAGENT_ROLES.has(r.role));
            const subs = rows.filter((r) => SUBAGENT_ROLES.has(r.role));
            return (
              <div className="space-y-6">
                <section aria-labelledby="agents-h">
                  <h3 id="agents-h" className="mb-1 text-sm font-semibold">
                    Agents
                  </h3>
                  <ul>
                    {agents.map((r) => (
                      <RoleRow key={r.role} row={r} models={models} onChange={onChange} />
                    ))}
                  </ul>
                </section>
                <section aria-labelledby="subagents-h">
                  <h3 id="subagents-h" className="mb-1 text-sm font-semibold">
                    Sub-agents
                  </h3>
                  <ul>
                    {subs.map((r) => (
                      <RoleRow key={r.role} row={r} models={models} onChange={onChange} />
                    ))}
                  </ul>
                </section>
              </div>
            );
          }}
        </StateView>
      </CardContent>
    </Card>
  );
}
