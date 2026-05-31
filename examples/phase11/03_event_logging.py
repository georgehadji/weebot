#!/usr/bin/env python3
"""
Example 3: Event Logging & Cost Tracking
=========================================

This example demonstrates the event logging system
for audit trails and cost tracking.

Run with:
    python examples/phase11/03_event_logging.py

The EventStore provides:
    - SQLite-based persistent storage
    - Automatic cost aggregation
    - Session management
    - Export to JSON/Markdown
"""

import tempfile
from datetime import datetime, timedelta

from weebot.infrastructure.event_store import EventStore
from weebot.infrastructure.event_logging import EventLogger


def example_1_basic_logging():
    """Demonstrate basic event logging."""
    print("=" * 60)
    print("Example 1: Basic Event Logging")
    print("=" * 60)
    
    # Create temporary database
    with tempfile.TemporaryDirectory() as tmp:
        db_path = f"{tmp}/events.db"
        store = EventStore(db_path=db_path)
        
        # Start a session
        store.start_session("session-1", user_id="user-123")
        print("\n✓ Session started: session-1")
        
        # Log various events
        store.log_event(
            session_id="session-1",
            event_type="llm_call",
            data={"prompt": "Hello, how are you?", "response_length": 50},
            cost=0.02,
            model="gpt-4",
            tokens_used=150
        )
        print("✓ Logged: LLM call (gpt-4, $0.02, 150 tokens)")
        
        store.log_event(
            session_id="session-1",
            event_type="tool_call",
            data={"tool": "bash", "command": "ls -la"},
        )
        print("✓ Logged: Tool call (bash)")
        
        store.log_event(
            session_id="session-1",
            event_type="code_change",
            data={"file": "main.py", "change_type": "modify"},
        )
        print("✓ Logged: Code change (main.py)")
        
        # End session
        store.end_session("session-1", status="completed")
        print("✓ Session ended: completed")
        
        # Retrieve events
        events = store.get_session_events("session-1")
        print(f"\n📊 Total events logged: {len(events)}")
        
        for event in events:
            print(f"  - {event.event_type}: ${event.cost:.2f}, {event.tokens_used} tokens")


def example_2_cost_tracking():
    """Demonstrate cost tracking across sessions."""
    print("\n" + "=" * 60)
    print("Example 2: Cost Tracking")
    print("=" * 60)
    
    with tempfile.TemporaryDirectory() as tmp:
        db_path = f"{tmp}/events.db"
        store = EventStore(db_path=db_path)
        
        # Session 1: Expensive model
        store.start_session("session-expensive", user_id="user-1")
        store.log_event("session-expensive", "llm_call", {}, 0.05, "gpt-4", 1000)
        store.log_event("session-expensive", "llm_call", {}, 0.05, "gpt-4", 1000)
        store.end_session("session-expensive")
        
        # Session 2: Free model
        store.start_session("session-cheap", user_id="user-1")
        store.log_event("session-cheap", "llm_call", {}, 0.00, "qwen-free", 500)
        store.log_event("session-cheap", "llm_call", {}, 0.00, "qwen-free", 500)
        store.end_session("session-cheap")
        
        # Get cost summaries
        print("\n💰 Cost Summary - Expensive Session:")
        summary_exp = store.get_cost_summary("session-expensive")
        print(f"  Total Cost: ${summary_exp.total_cost:.4f}")
        print(f"  Total Tokens: {summary_exp.total_tokens}")
        for model, stats in summary_exp.model_breakdown.items():
            print(f"    {model}: ${stats['cost']:.4f} ({stats['calls']} calls)")
        
        print("\n💰 Cost Summary - Cheap Session:")
        summary_cheap = store.get_cost_summary("session-cheap")
        print(f"  Total Cost: ${summary_cheap.total_cost:.4f}")
        print(f"  Total Tokens: {summary_cheap.total_tokens}")
        for model, stats in summary_cheap.model_breakdown.items():
            print(f"    {model}: ${stats['cost']:.4f} ({stats['calls']} calls)")
        
        savings = summary_exp.total_cost - summary_cheap.total_cost
        print(f"\n💡 Savings with free model: ${savings:.4f}")


def example_3_session_queries():
    """Demonstrate session querying."""
    print("\n" + "=" * 60)
    print("Example 3: Session Queries")
    print("=" * 60)
    
    with tempfile.TemporaryDirectory() as tmp:
        db_path = f"{tmp}/events.db"
        store = EventStore(db_path=db_path)
        
        # Create multiple sessions
        for i in range(5):
            store.start_session(f"session-{i}", user_id=f"user-{i % 2}")
            store.log_event(f"session-{i}", "test", {})
            if i == 2:  # One failed session
                store.end_session(f"session-{i}", status="failed")
            else:
                store.end_session(f"session-{i}", status="completed")
        
        # Query all sessions
        all_sessions = store.list_sessions()
        print(f"\n📋 All sessions: {len(all_sessions)}")
        
        # Query by user
        user_0_sessions = store.list_sessions(user_id="user-0")
        print(f"📋 User-0 sessions: {len(user_0_sessions)}")
        
        # Query by status
        failed_sessions = store.list_sessions(status="failed")
        print(f"📋 Failed sessions: {len(failed_sessions)}")
        
        # Get recent failed
        recent_failed = store.get_recent_failed_sessions(limit=10)
        print(f"📋 Recent failed: {len(recent_failed)}")


def example_4_event_logger_helper():
    """Demonstrate the EventLogger helper class."""
    print("\n" + "=" * 60)
    print("Example 4: EventLogger Helper")
    print("=" * 60)
    
    with tempfile.TemporaryDirectory() as tmp:
        db_path = f"{tmp}/events.db"
        logger = EventLogger(EventStore(db_path=db_path))
        
        # Start session
        logger.event_store.start_session("session-helper", "user-1")
        
        # Log various activities
        logger.log_llm_call(
            session_id="session-helper",
            model="gpt-4",
            prompt="Calculate 2+2",
            response="The answer is 4",
            tokens_used=50,
            cost=0.01
        )
        print("✓ Logged LLM call")
        
        logger.log_tool_call(
            session_id="session-helper",
            tool_name="bash",
            parameters={"command": "ls"},
            result={"output": "file1.txt file2.txt", "success": True},
            duration_ms=100
        )
        print("✓ Logged tool call")
        
        logger.log_bash_command(
            session_id="session-helper",
            command="rm -rf temp/",
            risk_level="dangerous",
            approved=True,
            output="Files deleted",
            exit_code=0
        )
        print("✓ Logged bash command with risk assessment")
        
        logger.log_plan_created(
            session_id="session-helper",
            plan={
                "id": "plan-1",
                "title": "Calculate sum",
                "steps": ["Parse input", "Calculate", "Return result"]
            }
        )
        print("✓ Logged plan creation")
        
        # Show stats
        stats = logger.event_store.get_stats()
        print(f"\n📊 Database Stats:")
        print(f"  Sessions: {stats['sessions']}")
        print(f"  Events: {stats['events']}")
        print(f"  Total Cost: ${stats['total_cost']:.4f}")
        print(f"  Total Tokens: {stats['total_tokens']}")


def example_5_export():
    """Demonstrate session export."""
    print("\n" + "=" * 60)
    print("Example 5: Session Export")
    print("=" * 60)
    
    with tempfile.TemporaryDirectory() as tmp:
        db_path = f"{tmp}/events.db"
        store = EventStore(db_path=db_path)
        
        # Create session with data
        store.start_session("export-session", "demo-user")
        store.log_event("export-session", "llm_call", {"prompt": "Hello"}, 0.01, "gpt-4", 50)
        store.log_event("export-session", "code_change", {"file": "test.py"})
        store.end_session("export-session", "completed")
        
        # Export as JSON
        json_export = store.export_session("export-session", format="json")
        print("\n📄 JSON Export (first 800 chars):")
        print("-" * 40)
        print(json_export[:800])
        print("...")
        
        # Export as Markdown
        md_export = store.export_session("export-session", format="markdown")
        print("\n\n📄 Markdown Export (first 800 chars):")
        print("-" * 40)
        print(md_export[:800])
        print("...")


if __name__ == "__main__":
    print("\n" + "📊 " * 15)
    print("Weebot Phase 11 - Event Logging Examples")
    print("📊 " * 15 + "\n")
    
    try:
        example_1_basic_logging()
        example_2_cost_tracking()
        example_3_session_queries()
        example_4_event_logger_helper()
        example_5_export()
        
        print("\n" + "=" * 60)
        print("✅ All logging examples completed!")
        print("=" * 60)
        print("\nKey Takeaways:")
        print("  • Events stored in SQLite with full persistence")
        print("  • Automatic cost aggregation per session")
        print("  • Query by user, status, time range")
        print("  • Export to JSON/Markdown for sharing")
        print("  • Complete audit trail for debugging")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
