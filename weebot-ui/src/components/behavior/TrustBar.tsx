"use client";

/**
 * Trust score display component
 */

import { TrustScore } from "@/hooks/useBehavior";

interface TrustBarProps {
  trust: TrustScore | null;
}

export function TrustBar({ trust }: TrustBarProps) {
  if (!trust) {
    return (
      <div style={{ 
        padding: "12px 16px", 
        background: "#1a1a2e",
        borderRadius: "8px",
        marginBottom: "16px",
        color: "#888"
      }}>
        Loading trust score...
      </div>
    );
  }

  const getColor = () => {
    if (trust.score_percentage >= 90) return "#22c55e"; // green
    if (trust.score_percentage >= 70) return "#f59e0b"; // yellow
    return "#ef4444"; // red
  };

  const getStatusText = () => {
    switch (trust.status) {
      case "trusted": return "Trusted";
      case "review": return "Review Needed";
      case "supervision": return "Requires Supervision";
      default: return "Unknown";
    }
  };

  return (
    <div style={{ 
      padding: "12px 16px", 
      background: "#1a1a2e",
      borderRadius: "8px",
      marginBottom: "16px"
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: "16px" }}>
        {/* Score Circle */}
        <div style={{
          width: "60px",
          height: "60px",
          borderRadius: "50%",
          border: `3px solid ${getColor()}`,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: "20px",
          fontWeight: "bold",
          color: getColor()
        }}>
          {trust.score_percentage}%
        </div>

        {/* Details */}
        <div style={{ flex: 1 }}>
          <div style={{ 
            fontSize: "16px", 
            fontWeight: "600",
            color: getColor()
          }}>
            {getStatusText()}
          </div>
          <div style={{ 
            fontSize: "12px", 
            color: "#888",
            marginTop: "4px"
          }}>
            {trust.total_actions.toLocaleString()} actions · {trust.overrides} overrides
          </div>
        </div>

        {/* Progress Bar */}
        <div style={{ width: "120px" }}>
          <div style={{
            height: "8px",
            background: "#333",
            borderRadius: "4px",
            overflow: "hidden"
          }}>
            <div style={{
              width: `${trust.score_percentage}%`,
              height: "100%",
              background: getColor(),
              transition: "width 0.3s ease"
            }} />
          </div>
        </div>
      </div>
    </div>
  );
}
