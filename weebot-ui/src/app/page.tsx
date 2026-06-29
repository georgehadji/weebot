import Link from "next/link";
import { Bot, MessageSquare, Zap, Shield } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConnectionStatus } from "@/components/ConnectionStatus";

export default function Home() {
  return (
    <div className="container mx-auto py-12 px-4">
      <div className="max-w-3xl mx-auto mb-8">
        <ConnectionStatus />
      </div>

      <div className="text-center max-w-3xl mx-auto mb-12">
        <h1 className="text-4xl font-bold mb-4">Welcome to Weebot</h1>
        <p className="text-xl text-muted-foreground mb-8">
          A production-grade AI agent framework with real-time event streaming,
          advanced planning, and multi-model support.
        </p>
        <div className="flex gap-4 justify-center">
          <Link href="/sessions/new">
            <Button size="lg">
              <Bot className="mr-2 h-5 w-5" />
              Start New Session
            </Button>
          </Link>
          <Link href="/sessions">
            <Button size="lg" variant="outline">View Sessions</Button>
          </Link>
        </div>
      </div>

      <div className="grid md:grid-cols-3 gap-6 max-w-5xl mx-auto">
        <Card>
          <CardHeader>
            <MessageSquare className="h-8 w-8 mb-2 text-primary" />
            <CardTitle>Real-time Chat</CardTitle>
            <CardDescription>
              Interactive conversations with AI agents, complete with tool calling
              and streaming responses.
            </CardDescription>
          </CardHeader>
        </Card>

        <Card>
          <CardHeader>
            <Zap className="h-8 w-8 mb-2 text-primary" />
            <CardTitle>Plan-Act Flow</CardTitle>
            <CardDescription>
              Intelligent planning and execution with PlanActFlow, supporting
              complex multi-step tasks.
            </CardDescription>
          </CardHeader>
        </Card>

        <Card>
          <CardHeader>
            <Shield className="h-8 w-8 mb-2 text-primary" />
            <CardTitle>58+ Models</CardTitle>
            <CardDescription>
              Support for 58+ models including GPT-5, Claude 4.6, Gemini 3.1,
              and open-source alternatives.
            </CardDescription>
          </CardHeader>
        </Card>
      </div>
    </div>
  );
}
