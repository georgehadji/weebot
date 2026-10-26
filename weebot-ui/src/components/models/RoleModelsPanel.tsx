"use client";

import { useCallback, useState } from "react";
import { StateView } from "@/components/common/StateView";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useRemote } from "@/hooks/useRemote";
import { api } from "@/lib/api";
import { ModelInfo, RoleModel } from "@/types/events";

const SUBAGENT_ROLES = new Set(["subagent", "planner_sub"]);

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

  const change = async (model: string) => {
    setBusy(true);
    setError(null);
    try {
      await onChange(row.role, model);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save");
    } finally {
      setBusy(false);
    }
  };

  return (
    <li className="flex flex-col gap-1 border-b py-3 last:border-b-0 sm:flex-row sm:items-center sm:gap-4">
      <label htmlFor={id} className="min-w-0 sm:w-48">
        <span className="block text-sm font-medium capitalize">{row.role.replace(/_/g, " ")}</span>
        <span className="block truncate font-mono text-xs text-muted-foreground">
          {row.override ? "your pick" : "default"}
        </span>
      </label>
      <select
        id={id}
        value={row.override ?? ""}
        disabled={busy}
        onChange={(e) => void change(e.target.value)}
        className="h-10 min-w-0 flex-1 rounded-md border border-input bg-transparent px-3 text-sm focus:outline-hidden focus:ring-2 focus:ring-ring disabled:opacity-50"
      >
        <option value="">Default · {row.default[0]}</option>
        {groupByProvider(models).map(([provider, group]) => (
          <optgroup key={provider} label={provider}>
            {group.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
      <Button
        variant="ghost"
        size="sm"
        disabled={busy || !row.override}
        onClick={() => void change("")}
        aria-label={`Reset ${row.role} to default`}
      >
        Reset
      </Button>
      {error && (
        <p role="alert" className="text-xs text-red-500 sm:basis-full">
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
