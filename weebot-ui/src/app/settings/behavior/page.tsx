"use client";

/**
 * Behavior Tracking Settings Page
 */

import { useEffect, useState } from "react";

export default function BehaviorSettingsPage() {
  const [enabled, setEnabled] = useState(true);
  const [autoStart, setAutoStart] = useState(true);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    // Load current settings from API
    fetch("/api/behavior/settings")
      .then(res => res.json())
      .then(data => {
        setEnabled(data.enabled ?? true);
        setAutoStart(data.auto_start ?? true);
      })
      .catch(() => {
        // Use defaults if API not available
      });
  }, []);

  const saveSettings = async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/behavior/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled, auto_start: autoStart })
      });
      if (res.ok) {
        setMessage("Settings saved!");
        setTimeout(() => setMessage(""), 3000);
      }
    } catch {
      setMessage("Failed to save settings");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ padding: "24px", maxWidth: "800px", margin: "0 auto" }}>
      <h1>🛡️ Behavior Tracking Settings</h1>
      <p style={{ color: "#888" }}>
        Configure automatic behavior monitoring for agent sessions
      </p>

      <div style={{
        background: "#1a1a2e",
        borderRadius: "8px",
        padding: "24px",
        marginTop: "24px"
      }}>
        {/* Enable/Disable */}
        <div style={{ 
          display: "flex", 
          alignItems: "center", 
          justifyContent: "space-between",
          padding: "16px 0",
          borderBottom: "1px solid #333"
        }}>
          <div>
            <h3 style={{ margin: 0 }}>Enable Behavior Tracking</h3>
            <p style={{ margin: "4px 0 0 0", color: "#888", fontSize: "14px" }}>
              Record all filesystem actions during agent sessions
            </p>
          </div>
          <label style={{
            position: "relative",
            display: "inline-block",
            width: "50px",
            height: "26px"
          }}>
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
              style={{ opacity: 0, width: 0, height: 0 }}
            />
            <span style={{
              position: "absolute",
              cursor: "pointer",
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              backgroundColor: enabled ? "#22c55e" : "#333",
              transition: ".3s",
              borderRadius: "26px"
            }}>
              <span style={{
                position: "absolute",
                content: "",
                height: "18px",
                width: "18px",
                left: enabled ? "28px" : "4px",
                bottom: "4px",
                backgroundColor: "white",
                transition: ".3s",
                borderRadius: "50%"
              }} />
            </span>
          </label>
        </div>

        {/* Auto-start */}
        <div style={{ 
          display: "flex", 
          alignItems: "center", 
          justifyContent: "space-between",
          padding: "16px 0",
          borderBottom: "1px solid #333",
          opacity: enabled ? 1 : 0.5
        }}>
          <div>
            <h3 style={{ margin: 0 }}>Auto-start with Sessions</h3>
            <p style={{ margin: "4px 0 0 0", color: "#888", fontSize: "14px" }}>
              Automatically start tracking when a new session begins
            </p>
          </div>
          <label style={{
            position: "relative",
            display: "inline-block",
            width: "50px",
            height: "26px"
          }}>
            <input
              type="checkbox"
              checked={autoStart && enabled}
              onChange={(e) => setAutoStart(e.target.checked)}
              disabled={!enabled}
              style={{ opacity: 0, width: 0, height: 0 }}
            />
            <span style={{
              position: "absolute",
              cursor: enabled ? "pointer" : "not-allowed",
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              backgroundColor: autoStart && enabled ? "#22c55e" : "#333",
              transition: ".3s",
              borderRadius: "26px"
            }}>
              <span style={{
                position: "absolute",
                content: "",
                height: "18px",
                width: "18px",
                left: autoStart && enabled ? "28px" : "4px",
                bottom: "4px",
                backgroundColor: "white",
                transition: ".3s",
                borderRadius: "50%"
              }} />
            </span>
          </label>
        </div>

        {/* Storage Info */}
        <div style={{ padding: "16px 0" }}>
          <h3 style={{ margin: 0 }}>Storage Location</h3>
          <code style={{
            display: "block",
            marginTop: "8px",
            padding: "12px",
            background: "#0f0f1a",
            borderRadius: "4px",
            fontSize: "13px",
            color: "#888"
          }}>
            ~/.weebot/ledger/
          </code>
          <p style={{ margin: "8px 0 0 0", color: "#666", fontSize: "12px" }}>
            Behavior data is stored locally in a git-backed ledger
          </p>
        </div>
      </div>

      {/* Actions */}
      <div style={{ marginTop: "24px", display: "flex", gap: "12px" }}>
        <button
          onClick={saveSettings}
          disabled={loading}
          style={{
            padding: "12px 24px",
            background: "#22c55e",
            border: "none",
            borderRadius: "6px",
            color: "#fff",
            fontSize: "14px",
            fontWeight: "500",
            cursor: loading ? "wait" : "pointer",
            opacity: loading ? 0.7 : 1
          }}
        >
          {loading ? "Saving..." : "Save Settings"}
        </button>

        <button
          onClick={() => {
            fetch("/api/behavior/self-knowledge")
              .then(res => res.json())
              .then(data => {
                const blob = new Blob([data.content], { type: "text/markdown" });
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = "WEEBOT_SELF.md";
                a.click();
              });
          }}
          style={{
            padding: "12px 24px",
            background: "transparent",
            border: "1px solid #444",
            borderRadius: "6px",
            color: "#888",
            fontSize: "14px",
            cursor: "pointer"
          }}
        >
          Download Self-Knowledge
        </button>
      </div>

      {message && (
        <div style={{
          marginTop: "16px",
          padding: "12px 16px",
          background: message.includes("saved") ? "rgba(34, 197, 94, 0.1)" : "rgba(239, 68, 68, 0.1)",
          borderRadius: "6px",
          color: message.includes("saved") ? "#22c55e" : "#ef4444"
        }}>
          {message}
        </div>
      )}

      {/* CLI Instructions */}
      <div style={{ marginTop: "32px" }}>
        <h3>CLI Environment Variables</h3>
        <pre style={{
          background: "#0f0f1a",
          padding: "16px",
          borderRadius: "8px",
          overflow: "auto",
          fontSize: "13px"
        }}>
{`# Disable behavior tracking
export WEEBOT_BEHAVIOR_TRACKING=false

# Custom ledger location
export WEEBOT_LEDGER_DIR=/path/to/ledger

# Extra ignore patterns
export WEEBOT_EXTRA_IGNORE="*.log,dist/"`}
        </pre>
      </div>
    </div>
  );
}
