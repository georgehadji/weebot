"use client";

/**
 * Live event feed component
 */

import { BehaviorEvent } from "@/hooks/useBehavior";

interface LiveFeedProps {
  events: BehaviorEvent[];
  maxItems?: number;
}

export function LiveFeed({ events, maxItems = 50 }: LiveFeedProps) {
  const displayEvents = events.slice(0, maxItems);

  const getEventIcon = (type: string) => {
    switch (type) {
      case "file.created": return "✚";
      case "file.modified": return "✎";
      case "file.deleted": return "✖";
      case "file.moved": return "➜";
      default: return "•";
    }
  };

  const getEventColor = (type: string) => {
    switch (type) {
      case "file.created": return "#22c55e"; // green
      case "file.modified": return "#f59e0b"; // yellow
      case "file.deleted": return "#ef4444"; // red
      case "file.moved": return "#06b6d4"; // cyan
      default: return "#888";
    }
  };

  const formatTime = (timestamp: string) => {
    try {
      return new Date(timestamp).toLocaleTimeString();
    } catch {
      return timestamp;
    }
  };

  const formatPath = (path: string) => {
    const parts = path.split("/");
    if (parts.length > 3) {
      return ".../" + parts.slice(-2).join("/");
    }
    return path;
  };

  return (
    <div style={{
      background: "#0f0f1a",
      borderRadius: "8px",
      padding: "12px",
      maxHeight: "300px",
      overflowY: "auto"
    }}>
      <div style={{
        fontSize: "12px",
        fontWeight: "600",
        color: "#888",
        textTransform: "uppercase",
        marginBottom: "8px",
        letterSpacing: "0.5px"
      }}>
        Live Feed ({events.length})
      </div>

      {displayEvents.length === 0 ? (
        <div style={{ color: "#555", fontSize: "12px", padding: "20px", textAlign: "center" }}>
          No events yet...
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
          {displayEvents.map((event, index) => (
            <div
              key={`${event.timestamp}-${index}`}
              style={{
                display: "flex",
                alignItems: "center",
                gap: "8px",
                padding: "4px 8px",
                borderRadius: "4px",
                fontSize: "12px",
                fontFamily: "monospace",
                background: index === 0 ? "rgba(255,255,255,0.05)" : "transparent"
              }}
            >
              <span style={{ 
                color: getEventColor(event.type),
                width: "16px",
                textAlign: "center"
              }}>
                {getEventIcon(event.type)}
              </span>
              
              <span style={{ color: "#666", minWidth: "60px" }}>
                {formatTime(event.timestamp)}
              </span>
              
              <span style={{ 
                color: "#ccc",
                flex: 1,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap"
              }}>
                {formatPath(event.path)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
