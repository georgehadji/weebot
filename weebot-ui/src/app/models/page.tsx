"use client";

import { StateView } from "@/components/common/StateView";
import { useRemote } from "@/hooks/useRemote";
import { useIntlContext } from "@/hooks/useIntlContext";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import dynamic from "next/dynamic";
import { api } from "@/lib/api";
import { formatCurrency, formatNumber, plural } from "@/lib/format";
import { ModelInfo } from "@/types/events";
import { Brain, Zap, DollarSign } from "lucide-react";

const loadModels = () => api.models.list();

// The role editor pulls in the Select primitive, which only this page needs below the fold; loading
// it on demand keeps /models inside its first-load JavaScript budget (e2e/perf.spec.ts).
const RoleModelsPanel = dynamic(() => import("@/components/models/RoleModelsPanel").then((m) => m.RoleModelsPanel), {
  loading: () => <div role="status" className="mb-6 text-sm text-muted-foreground">Loading agent models…</div>,
});

function groupByProvider(models: ModelInfo[]): Record<string, ModelInfo[]> {
  return models.reduce((acc, model) => {
    (acc[model.provider] ??= []).push(model);
    return acc;
  }, {} as Record<string, ModelInfo[]>);
}

const TIER_DOT: Record<string, string> = {
  free: "bg-status-live",
  fast: "bg-sky",
  standard: "bg-status-waiting",
  premium: "bg-fig",
};

function ModelCatalog({ models }: { models: ModelInfo[] }) {
  const ctx = useIntlContext();
  const groupedModels = groupByProvider(models);

  return (
    <>
      <div className="mb-6 flex items-center justify-end gap-2 text-sm text-muted-foreground">
        <Brain className="h-4 w-4" aria-hidden="true" />
        <span>{plural(models.length, ctx, { one: "{n} model available", other: "{n} models available" })}</span>
      </div>

      <RoleModelsPanel models={models} />

      {Object.entries(groupedModels).map(([provider, providerModels]) => (
        <div key={provider} className="mb-8">
          <h2 className="text-xl font-semibold mb-4 capitalize">{provider}</h2>
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
            {providerModels.map((model) => (
              <Card key={model.id} className="cv-auto hover:border-primary/50 transition-colors">
                <CardHeader className="pb-2">
                  <div className="flex min-w-0 items-start justify-between gap-2">
                    <CardTitle render={<h3 />} className="min-w-0 break-words text-lg" translate="no" title={model.name}>
                      {model.name}
                    </CardTitle>
                    <span className="flex shrink-0 items-center gap-1.5 text-xs capitalize text-muted-foreground">
                      <span
                        className={`h-3 w-3 rounded-full ${TIER_DOT[model.tier] ?? "bg-muted-foreground"}`}
                        aria-hidden="true"
                      />
                      {model.tier}
                    </span>
                  </div>
                  <p className="truncate font-mono text-xs text-muted-foreground" translate="no" title={model.id}>
                    {model.id}
                  </p>
                </CardHeader>
                <CardContent>
                  <div className="space-y-2">
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-muted-foreground flex items-center gap-1">
                        <DollarSign className="h-3 w-3" aria-hidden="true" />
                        Cost per 1M tokens
                      </span>
                      <span className="font-medium tabular-nums">
                        {model.cost_per_1k_tokens === 0 ? (
                          <Badge variant="secondary" className="bg-status-live/10 text-status-live-fg">
                            FREE
                          </Badge>
                        ) : (
                          formatCurrency(model.cost_per_1k_tokens * 1000, ctx)
                        )}
                      </span>
                    </div>

                    {model.context_window && (
                      <div className="flex items-center justify-between text-sm">
                        <span className="text-muted-foreground flex items-center gap-1">
                          <Zap className="h-3 w-3" aria-hidden="true" />
                          Context
                        </span>
                        <span className="font-medium tabular-nums">
                          {formatNumber(model.context_window, ctx)} tokens
                        </span>
                      </div>
                    )}

                    {model.strengths && model.strengths.length > 0 && (
                      <div className="flex flex-wrap gap-1 pt-2">
                        {model.strengths.slice(0, 3).map((strength) => (
                          <Badge key={strength} variant="outline" className="text-xs">
                            {strength}
                          </Badge>
                        ))}
                        {model.strengths.length > 3 && (
                          <Badge variant="outline" className="text-xs">
                            +{model.strengths.length - 3}
                          </Badge>
                        )}
                      </div>
                    )}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      ))}
    </>
  );
}

export default function ModelsPage() {
  const { state, reload } = useRemote(loadModels);
  return (
    <div className="container mx-auto py-8 px-4">
      <h2 className="text-3xl font-bold mb-6">Available Models</h2>
      <StateView
        state={state}
        loadingLabel="Loading models"
        errorTitle="Couldn't load models"
        onRetry={reload}
        skeleton={
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {[...Array(6)].map((_, i) => (
              <Card key={i} className="h-24 animate-pulse" />
            ))}
          </div>
        }
      >
        {(models) => <ModelCatalog models={models} />}
      </StateView>
    </div>
  );
}
