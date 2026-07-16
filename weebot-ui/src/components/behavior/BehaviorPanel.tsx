"use client";

/**
 * Main behavior tracking panel
 * Combines trust bar, live feed, and recent actions
 */

import { useBehavior, useBehaviorREST } from "@/hooks/useBehavior";
import { TrustBar } from "./TrustBar";
import { LiveFeed } from "./LiveFeed";
import { RecentActions } from "./RecentActions";

interface BehaviorPanelProps {
  sessionId?: string;
  showLiveFeed?: boolean;
  showRecentActions?: boolean;
  className?: string;
}

export function BehaviorPanel({
  sessionId,
  showLiveFeed = true,
  showRecentActions = true,
  className = ""
}: BehaviorPanelProps) {
  // Try WebSocket first, fallback to REST
  const ws = useBehavior(sessionId);
  const rest = useBehaviorREST(sessionId);

  // Use WebSocket data if connected, otherwise REST
  const trustScore = ws.trustScore || rest.trustScore;
  const recentActions = ws.recentActions.length > 0 ? ws.recentActions : rest.recentActions;
  const isConnected = ws.isConnected;
  const isLoading = rest.isLoading;

  return (
    <div className={`behavior-panel ${className}`} style={{
      background: "#111118",
      borderRadius: "12px",
      padding: "16px",
      minWidth: "300px"
    }}>
      {/* Header */}
      <div style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        marginBottom: "16px"
      }}>
        <h3 style={{
          margin: 0,
          fontSize: "16px",
          fontWeight: "600",
          color: "#fff"
        }}>
          🛡️ Behavior Monitor
        </h3>
        
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          {isConnected ? (
            <span style={{
              fontSize: "11px",
              color: "#22c55e",
              display: "flex",
              alignItems: "center",
              gap: "4px"
            }}>
              <span style={{
                width: "6px",
                height: "6px",
                borderRadius: "50%",
                background: "#22c55e"
              }} />
              Live
            </span>
          ) : isLoading ? (
            <span style={{ fontSize: "11px", color: "#888" }}>Loading...</span>
          ) : (
            <span style={{
              fontSize: "11px",
              color: "#f59e0b",
              display: "flex",
              alignItems: "center",
              gap: "4px"
            }}>
              <span style={{
                width: "6px",
                height: "6px",
                borderRadius: "50%",
                background: "#f59e0b"
              }} />
              Polling
            </span>
          )}
        </div>
      </div>

      {/* Trust Score */}
      <TrustBar trust={trustScore} />

      {/* Two-column layout */}
      <div style={{
        display: "grid",
        gridTemplateColumns: showLiveFeed && showRecentActions ? "1fr 1fr" : "1fr",
        gap: "16px"
      }}>
        {showLiveFeed && (
          <LiveFeed events={ws.events} maxItems={30} />
        )}
        
        {showRecentActions && (
          <RecentActions 
            actions={recentActions} 
            onRefresh={rest.refreshAll}
          />
        )}
      </div>

      {/* Footer info */}
      <div style={{
        marginTop: "12px",
        paddingTop: "12px",
        borderTop: "1px solid #222",
        fontSize: "11px",
        color: "#666"
      }}>
        {sessionId ? (
          <span>Session: {sessionId.slice(0, 8)}...</span>
        ) : (
          <span>Global behavior tracking</span>
        )}
      </div>
    </div>
  );
}
