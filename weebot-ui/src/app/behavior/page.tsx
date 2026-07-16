"use client";

/**
 * Behavior Tracking Demo Page
 * Demonstrates the Iterance-inspired behavior monitoring system
 */

import { BehaviorPanel } from "@/components/behavior";
import { useState } from "react";

export default function BehaviorPage() {
  const [sessionId, setSessionId] = useState(`demo-${Date.now().toString(36)}`);

  return (
    <div style={{ padding: "24px", maxWidth: "1200px", margin: "0 auto" }}>
      <h1 style={{ marginBottom: "8px" }}>🛡️ Behavior Tracking Demo</h1>
      <p style={{ color: "#888", marginBottom: "24px" }}>
        Real-time filesystem monitoring with trust scoring
      </p>

      {/* Session Controls */}
      <div style={{ 
        marginBottom: "24px", 
        padding: "16px", 
        background: "#1a1a2e",
        borderRadius: "8px"
      }}>
        <label style={{ display: "block", marginBottom: "8px", color: "#888" }}>
          Session ID:
        </label>
        <div style={{ display: "flex", gap: "8px" }}>
          <input
            type="text"
            value={sessionId}
            onChange={(e) => setSessionId(e.target.value)}
            style={{
              flex: 1,
              padding: "8px 12px",
              background: "#0f0f1a",
              border: "1px solid #333",
              borderRadius: "4px",
              color: "#fff",
              fontFamily: "monospace"
            }}
          />
          <button
            onClick={() => setSessionId(`demo-${Date.now().toString(36)}`)}
            style={{
              padding: "8px 16px",
              background: "#333",
              border: "none",
              borderRadius: "4px",
              color: "#fff",
              cursor: "pointer"
            }}
          >
            New Session
          </button>
        </div>
      </div>

      {/* Main Behavior Panel */}
      <BehaviorPanel sessionId={sessionId} />

      {/* Documentation */}
      <div style={{ 
        marginTop: "32px",
        padding: "24px",
        background: "#111118",
        borderRadius: "8px"
      }}>
        <h2>About Behavior Tracking</h2>
        
        <p style={{ color: "#aaa", lineHeight: "1.6" }}>
          This feature is inspired by <a href="https://github.com/Tetrahedroned/iterance" target="_blank" rel="noopener noreferrer" style={{ color: "#60a5fa" }}>Iterance</a> — 
          a behavioral witness layer that creates an immutable record of AI agent actions.
        </p>

        <h3 style={{ marginTop: "24px", marginBottom: "12px" }}>Key Features</h3>
        <ul style={{ color: "#aaa", lineHeight: "1.8" }}>
          <li><strong>Real-time Monitoring:</strong> Watch filesystem changes as they happen</li>
          <li><strong>Git-Backed Ledger:</strong> Every action is committed to a git repository for auditability</li>
          <li><strong>Trust Scoring:</strong> Evidence-based trust metric calculated from override history</li>
          <li><strong>Override Tracking:</strong> Mark unsanctioned actions to improve future behavior</li>
          <li><strong>Self-Knowledge:</strong> Agents can read their own history via <code>~/.weebot/WEEBOT_SELF.md</code></li>
        </ul>

        <h3 style={{ marginTop: "24px", marginBottom: "12px" }}>CLI Commands</h3>
        <pre style={{ 
          background: "#0f0f1a",
          padding: "16px",
          borderRadius: "4px",
          overflow: "auto",
          fontSize: "12px"
        }}>
{`# Start tracking a session
weebot behavior watch ./my-project --session-id abc123

# View trust score
weebot behavior trust

# Show recent actions
weebot behavior log --count 20

# Mark action as override
weebot behavior override --timestamp "2026-04-05 14:32:18" --reason "Incorrect file deletion"

# Generate self-knowledge file
weebot behavior reflect
`}
        </pre>

        <h3 style={{ marginTop: "24px", marginBottom: "12px" }}>Color Legend</h3>
        <div style={{ display: "flex", gap: "16px", flexWrap: "wrap" }}>
          <span style={{ color: "#22c55e" }}>✚ Created</span>
          <span style={{ color: "#f59e0b" }}>✎ Modified</span>
          <span style={{ color: "#ef4444" }}>✖ Deleted</span>
          <span style={{ color: "#06b6d4" }}>➜ Moved</span>
        </div>
      </div>
    </div>
  );
}
