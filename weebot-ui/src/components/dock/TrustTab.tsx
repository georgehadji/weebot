import { BehaviorPanel } from "@/components/behavior/BehaviorPanel";

export function TrustTab({ sessionId }: { sessionId: string }) {
  return <BehaviorPanel sessionId={sessionId} showLiveFeed={false} className="rounded-none bg-transparent p-3" />;
}
