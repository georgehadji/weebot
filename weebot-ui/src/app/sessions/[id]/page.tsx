"use client";

import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { formatDistanceToNow } from "date-fns";
import { Send, Loader2, AlertCircle, CheckCircle2, Circle, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { useWebSocket } from "@/hooks/useWebSocket";
import { api } from "@/lib/api";
import { AgentEvent, MessageEvent, ToolEvent, StepEvent, WaitForUserEvent, PlanReviewEvent, Session } from "@/types/events";
import { PlanReviewCard } from "@/components/PlanReviewCard";

function StatusIcon({ status }: { status: string }) {
  switch (status) {
    case "completed":
      return <CheckCircle2 className="h-4 w-4 text-green-500" />;
    case "running":
      return <Loader2 className="h-4 w-4 animate-spin text-yellow-500" />;
    case "error":
      return <XCircle className="h-4 w-4 text-red-500" />;
    default:
      return <Circle className="h-4 w-4 text-gray-400" />;
  }
}

function EventCard({ event }: { event: AgentEvent }) {
  switch (event.type) {
    case "message":
      const msg = event as MessageEvent;
      return (
        <div className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
          <div
            className={`max-w-[80%] rounded-lg p-3 ${
              msg.role === "user"
                ? "bg-primary text-primary-foreground"
                : "bg-muted"
            }`}
          >
            <p className="whitespace-pre-wrap">{msg.message}</p>
          </div>
        </div>
      );

    case "step":
      const step = event as StepEvent;
      return (
        <div className="flex items-center gap-2 text-sm text-muted-foreground py-1">
          <StatusIcon status={step.status} />
          <span>{step.description}</span>
        </div>
      );

    case "tool":
      const tool = event as ToolEvent;
      return (
        <div className="rounded-lg border bg-card p-3 my-2">
          <div className="flex items-center gap-2 text-sm">
            <Badge variant="outline">{tool.tool_name}</Badge>
            <span className="font-mono text-xs">{tool.function_name}</span>
            <span className="text-muted-foreground text-xs">
              {tool.status === "calling" ? "calling..." : "completed"}
            </span>
          </div>
          {tool.result && (
            <pre className="mt-2 text-xs bg-muted p-2 rounded overflow-x-auto">
              {tool.result.slice(0, 500)}
              {tool.result.length > 500 && "..."}
            </pre>
          )}
        </div>
      );

    case "error":
      return (
        <div className="flex items-center gap-2 text-red-500 bg-red-50 p-3 rounded-lg">
          <AlertCircle className="h-4 w-4" />
          <span className="text-sm">{(event as { error: string }).error}</span>
        </div>
      );

    case "wait_for_user":
      const wfu = event as WaitForUserEvent;
      return (
        <div className="rounded-lg border border-yellow-200 bg-yellow-50 dark:border-yellow-800 dark:bg-yellow-950 p-3">
          <p className="text-sm font-medium text-yellow-800 dark:text-yellow-200 whitespace-pre-wrap">
            {wfu.question}
          </p>
        </div>
      );

    case "plan_review":
      return <PlanReviewCard event={event as PlanReviewEvent} />;

    case "done":
      return (
        <div className="flex items-center justify-center py-2">
          <Badge variant="secondary">Session completed</Badge>
        </div>
      );

    default:
      return null;
  }
}

export default function SessionPage() {
  const params = useParams();
  const sessionId = params.id as string;
  const [session, setSession] = useState<Session | null>(null);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(true);
  const [waitingForInput, setWaitingForInput] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const { isConnected, lastMessage } = useWebSocket(sessionId);

  // Load session data
  useEffect(() => {
    const loadSession = async () => {
      try {
        const data = await api.sessions.get(sessionId);
        setSession(data);
        // Convert stored events
        if (data.context?.events) {
          setEvents(data.context.events as AgentEvent[]);
        }
      } catch (e) {
        console.error("Failed to load session:", e);
      } finally {
        setLoading(false);
      }
    };
    loadSession();
  }, [sessionId]);

  // Handle WebSocket messages
  useEffect(() => {
    if (lastMessage) {
      setEvents((prev) => [...prev, lastMessage]);
      
      // Check if waiting for user input
      if (lastMessage.type === "wait_for_user") {
        setWaitingForInput(true);
      }
      if (lastMessage.type === "done") {
        setWaitingForInput(false);
      }
    }
  }, [lastMessage]);

  // Auto-scroll to bottom
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [events]);

  const handleSend = async () => {
    if (!input.trim() || !waitingForInput) return;

    try {
      await api.sessions.resume(sessionId, input.trim());
      setInput("");
      setWaitingForInput(false);
    } catch {
      alert("Failed to send message");
    }
  };

  if (loading) {
    return (
      <div className="container mx-auto py-8 px-4 flex items-center justify-center h-64">
        <Loader2 className="h-8 w-8 animate-spin" />
      </div>
    );
  }

  if (!session) {
    return (
      <div className="container mx-auto py-8 px-4">
        <Card>
          <CardContent className="flex items-center justify-center h-64 text-muted-foreground">
            Session not found
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="container mx-auto py-4 px-4 h-[calc(100vh-64px)] flex flex-col">
      <Card className="flex-1 flex flex-col">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-lg">
                {session.title || "Untitled Session"}
              </CardTitle>
              <p className="text-sm text-muted-foreground">
                {formatDistanceToNow(new Date(session.created_at), { addSuffix: true })}
                {" · "}
                <Badge variant={isConnected ? "default" : "secondary"}>
                  {isConnected ? "Live" : "Disconnected"}
                </Badge>
              </p>
            </div>
            <Badge variant={session.status === "active" ? "default" : "secondary"}>
              {session.status}
            </Badge>
          </div>
        </CardHeader>

        <Separator />

        <ScrollArea ref={scrollRef} className="flex-1 p-4">
          <div className="space-y-4">
            {events.length === 0 ? (
              <div className="text-center text-muted-foreground py-8">
                Waiting for events...
              </div>
            ) : (
              events.map((event, i) => (
                <EventCard key={i} event={event} />
              ))
            )}
          </div>
        </ScrollArea>

        <Separator />

        <CardContent className="pt-4">
          {waitingForInput ? (
            <div className="space-y-2">
              <p className="text-sm text-muted-foreground">
                Waiting for your response...
              </p>
              <div className="flex gap-2">
                <Textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder="Type your response..."
                  rows={2}
                  className="flex-1 resize-none"
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && e.metaKey) {
                      handleSend();
                    }
                  }}
                />
                <Button onClick={handleSend} disabled={!input.trim()}>
                  <Send className="h-4 w-4" />
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex items-center justify-center text-sm text-muted-foreground py-2">
              {session.status === "completed" ? (
                <Badge variant="secondary">Session completed</Badge>
              ) : (
                <span>Agent is working...</span>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
