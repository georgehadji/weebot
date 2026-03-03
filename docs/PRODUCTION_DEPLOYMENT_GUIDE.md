# Production Deployment Guide - Agent Context v2

## Changes Applied

### Issue #1: Race Condition Fix
- Added `asyncio.Lock` protection for `shared_data`
- Lock shared between parent and child contexts
- Added timeout handling (10s write, 5s read)
- Lock excluded from serialization

### Issue #2: EventBroker Retry
- Exponential backoff retry (3 attempts)
- Bounded event history (1000 events max)
- Metrics exposed for monitoring
- Returns delivery status

### Issue #3: StateManager Async
- Verified async methods already in use
- No changes required

---

## Monitoring Triggers

### Critical Alerts (Page on-call)

```python
# Trigger: AgentContext lock timeout
if agent_context_lock_timeout_rate > 0.01:  # >1% of operations
    ALERT("AgentContext lock contention detected")

# Trigger: EventBroker high drop rate
if event_broker_dropped_events > 10 per minute:
    ALERT("EventBroker failing to deliver events")

# Trigger: Event history at capacity
if event_broker_history_size > 900:  # 90% of MAX_HISTORY_SIZE
    WARN("Event history approaching capacity")
```

### Warning Alerts (Log and dashboard)

```python
# Trigger: Retry attempts
if event_broker_retry_attempts > 100 per minute:
    WARN("High event retry rate - check subscriber performance")

# Trigger: Slow lock acquisition
if agent_context_lock_wait_time > 1.0:  # p99 > 1 second
    WARN("Slow lock acquisition - possible contention")
```

### Metrics to Export

```python
# From AgentContext.get_metrics()
{
    "agent_id": str,
    "nesting_level": int,
    "shared_data_keys": int,
    "event_broker": {
        "dropped_events": int,
        "total_events": int,
        "active_subscriptions": dict
    }
}
```

---

## Migration Guide

### Step 1: Deploy New Module
```bash
# New file: weebot/core/agent_context_v2.py
# Old file: weebot/core/agent_context.py (keep for rollback)
```

### Step 2: Gradual Rollout
```python
# In agent_factory.py, use new context
from weebot.core.agent_context_v2 import AgentContext  # New
# from weebot.core.agent_context import AgentContext   # Old
```

### Step 3: Monitor
- Watch for lock timeout logs
- Monitor event drop rate
- Check memory usage (bounded history)

### Step 4: Full Rollback Available
```python
# Revert to old implementation if issues
from weebot.core.agent_context import AgentContext  # Rollback
```

---

## Testing Checklist

- [ ] Multi-agent workflow with concurrent writes
- [ ] Event delivery under high load
- [ ] Lock timeout scenarios
- [ ] Memory usage over extended run
- [ ] Serialization/deserialization round-trip

---

## Known Limitations

1. **Lock Contention:** All agents in hierarchy share one lock - slow operations block others
2. **Sequential Event Processing:** Slow subscribers block fast ones
3. **No Dead Letter Queue:** Failed events logged but not persisted
4. **No Subscriber Heartbeat:** Can't detect dead subscribers

These are accepted trade-offs per Dev/Adversary cost-benefit analysis.
