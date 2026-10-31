"use client";

import { StateView } from "@/components/common/StateView";
import { useRemote } from "@/hooks/useRemote";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { RoleModelsPanel } from "@/components/models/RoleModelsPanel";
import { api } from "@/lib/api";
import { ModelInfo } from "@/types/events";
import { Brain, Zap, DollarSign } from "lucide-react";

const loadModels = () => api.models.list();

function groupByProvider(models: ModelInfo[]): Record<string, ModelInfo[]> {
  return models.reduce((acc, model) => {
    (acc[model.provider] ??= []).push(model);
    return acc;
  }, {} as Record<string, ModelInfo[]>);
}

function ModelCatalog({ models }: { models: ModelInfo[] }) {
  const groupedModels = groupByProvider(models);
  const getTierColor = (tier: string) => {
    switch (tier) {
      case "free":
        return "bg-green-500";
      case "fast":
        return "bg-blue-500";
      case "standard":
        return "bg-yellow-500";
      case "premium":
        return "bg-purple-500";
      default:
        return "bg-gray-500";
    }
  };

  return (
    <>
      <div className="mb-6 flex items-center justify-end gap-2 text-sm text-muted-foreground">
        <Brain className="h-4 w-4" />
        <span>{models.length} models available</span>
      </div>

      <RoleModelsPanel models={models} />

      {Object.entries(groupedModels).map(([provider, providerModels]) => (
        <div key={provider} className="mb-8">
          <h2 className="text-xl font-semibold mb-4 capitalize">{provider}</h2>
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
            {providerModels.map((model) => (
              <Card key={model.id} className="hover:border-primary/50 transition-colors">
                <CardHeader className="pb-2">
                  <div className="flex items-start justify-between">
                    <CardTitle className="text-lg">{model.name}</CardTitle>
                    <div className={`w-3 h-3 rounded-full ${getTierColor(model.tier)}`} />
                  </div>
                  <p className="text-xs text-muted-foreground font-mono">{model.id}</p>
                </CardHeader>
                <CardContent>
                  <div className="space-y-2">
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-muted-foreground flex items-center gap-1">
                        <DollarSign className="h-3 w-3" />
                        Cost per 1K tokens
                      </span>
                      <span className="font-medium">
                        {model.cost_per_1k_tokens === 0 ? (
                          <Badge variant="secondary" className="bg-green-500/10 text-green-600">
                            FREE
                          </Badge>
                        ) : (
                          `$${(model.cost_per_1k_tokens * 1000).toFixed(2)}`
                        )}
                      </span>
                    </div>

                    {model.context_window && (
                      <div className="flex items-center justify-between text-sm">
                        <span className="text-muted-foreground flex items-center gap-1">
                          <Zap className="h-3 w-3" />
                          Context
                        </span>
                        <span className="font-medium" suppressHydrationWarning>
                          {model.context_window.toLocaleString()} tokens
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
      <h1 className="text-3xl font-bold mb-6">Available Models</h1>
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
