"use client";

/**
 * Recent actions list with override capability
 */

import { useState } from "react";
import { RecentAction } from "@/hooks/useBehavior";

interface RecentActionsProps {
  actions: RecentAction[];
  onRefresh?: () => void;
}

export function RecentActions({ actions, onRefresh }: RecentActionsProps) {
  const [selectedAction, setSelectedAction] = useState<RecentAction | null>(null);
  const [overrideReason, setOverrideReason] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

  const getActionIcon = (action: string) => {
    switch (action) {
      case "created": return "✚";
      case "modified": return "✎";
      case "deleted": return "✖";
      case "moved": return "➜";
      default: return "•";
    }
  };

  const getActionColor = (action: string) => {
    switch (action) {
      case "created": return "#22c55e";
      case "modified": return "#f59e0b";
      case "deleted": return "#ef4444";
      case "moved": return "#06b6d4";
      default: return "#888";
    }
  };

  const formatTime = (timestamp: string) => {
    try {
      const date = new Date(timestamp);
      return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    } catch {
      return "--:--";
    }
  };

  const formatPath = (path: string) => {
    const parts = path.split("/");
    return parts.slice(-2).join("/");
  };

  const handleOverride = async () => {
    if (!selectedAction || !overrideReason.trim()) return;

    setIsSubmitting(true);
    
    try {
      const res = await fetch(`${API_URL}/behavior/override`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          timestamp: selectedAction.timestamp,
          reason: overrideReason
        })
      });

      if (res.ok) {
        setSelectedAction(null);
        setOverrideReason("");
        onRefresh?.();
      }
    } catch (e) {
      console.error("Failed to submit override:", e);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div style={{
      background: "#0f0f1a",
      borderRadius: "8px",
      padding: "12px"
    }}>
      <div style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        marginBottom: "8px"
      }}>
        <div style={{
          fontSize: "12px",
          fontWeight: "600",
          color: "#888",
          textTransform: "uppercase",
          letterSpacing: "0.5px"
        }}>
          Recent Actions
        </div>
        
        <button
          onClick={onRefresh}
          style={{
            fontSize: "11px",
            padding: "4px 8px",
            background: "#222",
            border: "none",
            borderRadius: "4px",
            color: "#888",
            cursor: "pointer"
          }}
        >
          Refresh
        </button>
      </div>

      <div style={{ 
        maxHeight: "260px", 
        overflowY: "auto",
        display: "flex",
        flexDirection: "column",
        gap: "2px"
      }}>
        {actions.length === 0 ? (
          <div style={{ 
            color: "#555", 
            fontSize: "12px", 
            padding: "20px", 
            textAlign: "center" 
          }}>
            No actions recorded
          </div>
        ) : (
          actions.map((action, index) => (
            <button
              key={`${action.timestamp}-${index}`}
              onClick={() => setSelectedAction(action)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: "8px",
                padding: "6px 8px",
                borderRadius: "4px",
                fontSize: "11px",
                fontFamily: "monospace",
                background: selectedAction?.timestamp === action.timestamp ? "rgba(255,255,255,0.1)" : "transparent",
                border: "none",
                cursor: "pointer",
                textAlign: "left",
                width: "100%"
              }}
            >
              <span style={{ 
                color: getActionColor(action.action),
                width: "16px",
                textAlign: "center"
              }}>
                {action.is_override ? "⚠" : getActionIcon(action.action)}
              </span>
              
              <span style={{ color: "#666", minWidth: "40px" }}>
                {formatTime(action.timestamp)}
              </span>
              
              <span style={{ 
                color: action.is_override ? "#f59e0b" : "#ccc",
                flex: 1,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap"
              }}>
                {formatPath(action.path)}
              </span>
            </button>
          ))
        )}
      </div>

      {/* Override Modal */}
      {selectedAction && (
        <div style={{
          position: "fixed",
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: "rgba(0,0,0,0.7)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          zIndex: 1000
        }}>
          <div style={{
            background: "#1a1a2e",
            padding: "24px",
            borderRadius: "12px",
            width: "90%",
            maxWidth: "400px"
          }}>
            <h4 style={{ margin: "0 0 16px 0", color: "#fff" }}>
              Mark as Override
            </h4>
            
            <div style={{ marginBottom: "16px" }}>
              <div style={{ fontSize: "12px", color: "#888", marginBottom: "8px" }}>
                Action:
              </div>
              <div style={{ 
                padding: "8px 12px", 
                background: "#0f0f1a",
                borderRadius: "4px",
                fontSize: "12px",
                fontFamily: "monospace",
                color: "#ccc"
              }}>
                {selectedAction.action} {selectedAction.path.slice(-40)}
              </div>
            </div>

            <div style={{ marginBottom: "16px" }}>
              <label style={{ 
                display: "block", 
                fontSize: "12px", 
                color: "#888", 
                marginBottom: "8px" 
              }}>
                Reason for override:
              </label>
              <textarea
                value={overrideReason}
                onChange={(e) => setOverrideReason(e.target.value)}
                placeholder="Why was this action incorrect?"
                style={{
                  width: "100%",
                  padding: "8px 12px",
                  background: "#0f0f1a",
                  border: "1px solid #333",
                  borderRadius: "4px",
                  color: "#fff",
                  fontSize: "12px",
                  minHeight: "80px",
                  resize: "vertical"
                }}
              />
            </div>

            <div style={{ display: "flex", gap: "8px", justifyContent: "flex-end" }}>
              <button
                onClick={() => setSelectedAction(null)}
                style={{
                  padding: "8px 16px",
                  background: "transparent",
                  border: "1px solid #444",
                  borderRadius: "4px",
                  color: "#888",
                  cursor: "pointer"
                }}
              >
                Cancel
              </button>
              <button
                onClick={handleOverride}
                disabled={!overrideReason.trim() || isSubmitting}
                style={{
                  padding: "8px 16px",
                  background: "#ef4444",
                  border: "none",
                  borderRadius: "4px",
                  color: "#fff",
                  cursor: overrideReason.trim() && !isSubmitting ? "pointer" : "not-allowed",
                  opacity: overrideReason.trim() && !isSubmitting ? 1 : 0.5
                }}
              >
                {isSubmitting ? "Submitting..." : "Mark Override"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
