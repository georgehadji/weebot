"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Send, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import { ModelInfo } from "@/types/events";

export default function NewSessionPage() {
  const router = useRouter();
  const [prompt, setPrompt] = useState("");
  const [model, setModel] = useState("");
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [fetchingModels, setFetchingModels] = useState(true);

  useEffect(() => {
    api.models
      .list()
      .then((data) => {
        setModels(data);
        // Set default to first free or cheap model
        const defaultModel = data.find((m) => m.tier === "free") || data[0];
        if (defaultModel) {
          setModel(defaultModel.id);
        }
      })
      .finally(() => setFetchingModels(false));
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!prompt.trim()) return;

    try {
      setLoading(true);
      const session = await api.sessions.create({
        prompt: prompt.trim(),
        model: model || undefined,
      });
      // Start the Plan-Act flow in the background; navigate immediately so
      // the session page can pick up live WebSocket events as they arrive.
      await api.sessions.run(session.id);
      router.push(`/sessions/${session.id}`);
    } catch (e) {
      const message = e instanceof Error ? e.message : "Unknown error";
      if (message.includes("connect") || message.includes("fetch")) {
        alert("Failed to connect to backend.\n\nMake sure the backend is running:\npython -m weebot.interfaces.web.main");
      } else {
        alert("Failed to create session: " + message);
      }
      setLoading(false);
    }
  };

  const getModelDisplayName = (m: ModelInfo) => {
    const cost = m.cost_per_1k_tokens === 0 ? "FREE" : `$${(m.cost_per_1k_tokens * 1000).toFixed(2)}/M`;
    return `${m.name} (${cost})`;
  };

  return (
    <div className="container mx-auto py-8 px-4 max-w-3xl">
      <Card>
        <CardHeader>
          <CardTitle>New Session</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-6">
            <div className="space-y-2">
              <Label htmlFor="model">Model</Label>
              <Select value={model} onValueChange={(v) => setModel(v || "")} disabled={fetchingModels}>
                <SelectTrigger>
                  <SelectValue placeholder="Select a model" />
                </SelectTrigger>
                <SelectContent>
                  {models.map((m) => (
                    <SelectItem key={m.id} value={m.id}>
                      {getModelDisplayName(m)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="prompt">What would you like to do?</Label>
              <Textarea
                id="prompt"
                placeholder="e.g., Create a Python script to calculate Fibonacci numbers..."
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                rows={6}
                className="resize-none"
              />
            </div>

            <div className="flex justify-end">
              <Button type="submit" disabled={!prompt.trim() || loading} size="lg">
                {loading ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Creating...
                  </>
                ) : (
                  <>
                    <Send className="mr-2 h-4 w-4" />
                    Start Session
                  </>
                )}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
