# Phase 6b: Adaptive Parameter Suggestions

**Status:** ✅ Complete  
**Date:** 2026-03-03  
**Part of:** EXPAND Mode Execution

---

## 🎯 Overview

**Self-Improving Template System** that learns optimal parameters from execution history.

This feature was identified as the highest-value expansion in the Systems Audit (EXPAND mode) because it:
- Creates network effects (more users → better suggestions)
- Provides competitive differentiation (adaptive vs static templates)
- Reversibly adds 12% complexity for 60% utility gain

---

## ✨ Features

### Core Capabilities

| Feature | Description |
|---------|-------------|
| **Historical Learning** | Tracks parameter effectiveness over time |
| **Personal Suggestions** | Learns individual user preferences |
| **Collaborative Filtering** | Aggregates successful patterns across users |
| **Bayesian Confidence** | Weights suggestions by sample size |
| **Privacy Preserving** | Hashed user IDs, GDPR compliant |
| **Feature Flag Control** | Gradual rollout, per-user enablement |

### Privacy & Compliance

- ✅ **Hashed User IDs** - One-way hashing (cannot reverse)
- ✅ **Minimum Sample Size** - 3+ users before collaborative suggestions
- ✅ **Opt-in Required** - Strict privacy mode by default
- ✅ **30-Day Retention** - Auto-purge old data
- ✅ **Feature Flags** - Users can disable completely

---

## 🚀 Usage

### Enable Adaptive Suggestions

```python
from weebot.templates.production import ProductionTemplateEngine
from weebot.templates.feature_flags import get_feature_flags

# Create engine with adaptive enabled
engine = ProductionTemplateEngine(
    database_url="postgresql+asyncpg://...",
    enable_adaptive=True,
)

# Enable for specific user
flags = get_feature_flags()
flags.enable_for_user("adaptive_suggestions", "user123")
```

### Get Suggestions

```python
# Before execution, get suggestions
suggestions = await engine.get_suggestions(
    template_name="Research Analysis Workflow",
    user=authenticated_user,
    current_input={"topic": "AI"},  # Partial input
)

# Suggestions include confidence scores
for sugg in suggestions:
    print(f"{sugg['parameter']}: {sugg['value']}")
    print(f"  Confidence: {sugg['confidence']:.0%}")
    print(f"  Success rate: {sugg['success_rate']:.0%}")
    print(f"  Based on {sugg['sample_size']} executions")
```

### Automatic Learning

```python
# Engine automatically records outcomes
result = await engine.execute(
    "Research Analysis Workflow",
    parameters={"topic": "AI", "depth": "comprehensive"},
    user=authenticated_user,
)

# Success/failure is recorded for learning
# No manual action required!
```

---

## 📊 How It Works

### Architecture

```
User Input → Suggestion Engine → Filter by Confidence (>60%)
     ↓
Historical Data ← Record Outcome ← Execution Result
     ↓
Bayesian Scoring → Rank Suggestions → Present to User
```

### Data Flow

1. **Pre-Execution:** Query historical effectiveness for similar parameters
2. **Suggestion:** Return top-ranked parameters with confidence scores
3. **Execution:** Run template with user-selected parameters
4. **Recording:** Store outcome (success, time, satisfaction)
5. **Learning:** Update Bayesian scores for next time

### Scoring Algorithm

```python
# Confidence = Success Rate × Weight
# Weight = min(1.0, Sample Size / 50)

# Example:
# 10 executions, 90% success → 0.9 × 0.2 = 0.18 confidence (not suggested)
# 50 executions, 90% success → 0.9 × 1.0 = 0.90 confidence (suggested!)
```

---

## 🗄️ Database Schema

### Tables Added

```sql
-- Parameter effectiveness tracking
CREATE TABLE parameter_effectiveness (
    id SERIAL PRIMARY KEY,
    template_name VARCHAR(255),
    parameter_hash VARCHAR(64),
    parameter_values_hash VARCHAR(64),
    parameter_values_json TEXT,
    execution_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    avg_execution_time_ms FLOAT,
    user_count INTEGER DEFAULT 0,
    can_be_used_for_suggestions BOOLEAN DEFAULT TRUE
);

-- Anonymized user preferences
CREATE TABLE user_preferences_anonymized (
    id SERIAL PRIMARY KEY,
    user_hash VARCHAR(64),  -- One-way hash
    template_name VARCHAR(255),
    preferred_parameters_json TEXT,
    usage_count INTEGER DEFAULT 0
);
```

---

## 🧪 Testing

```bash
# Run adaptive engine tests
pytest tests/unit/test_templates/test_adaptive.py -v

# Test privacy compliance
pytest tests/unit/test_templates/test_adaptive.py::TestPrivacyCompliance -v

# Test integration
pytest tests/unit/test_templates/test_adaptive.py::TestProductionIntegration -v
```

---

## ⚙️ Configuration

### Environment Variables

```bash
# Enable/disable adaptive globally
ENABLE_ADAPTIVE_SUGGESTIONS=true

# Privacy mode: strict, balanced, relaxed
ADAPTIVE_PRIVACY_MODE=strict

# Minimum executions before suggestion
ADAPTIVE_MIN_SAMPLES=5

# Confidence threshold (0.0 - 1.0)
ADAPTIVE_MIN_CONFIDENCE=0.6
```

### Feature Flags

```python
from weebot.templates.feature_flags import get_feature_flags, FeatureState

flags = get_feature_flags()

# Gradual rollout (50% of users)
flags.register(FeatureConfig(
    name="adaptive_suggestions",
    state=FeatureState.PERCENTAGE,
    percentage=50,
))

# Enable for specific users only
flags.register(FeatureConfig(
    name="adaptive_suggestions",
    state=FeatureState.ENABLED,
    allowed_users={"user1", "user2"},
))
```

---

## 📈 Metrics

### Get Statistics

```python
stats = await engine.get_adaptive_stats()

print(f"Total combinations tracked: {stats['total_combinations_tracked']}")
print(f"High confidence suggestions: {stats['high_confidence_suggestions']}")
print(f"Average success rate: {stats['average_success_rate']:.1%}")
```

### Per-Template Stats

```python
template_stats = await engine.get_adaptive_stats(
    template_name="Research Analysis Workflow"
)
```

---

## 🛡️ GDPR Compliance

### User Rights

1. **Right to be Forgotten**
```python
# Delete all data for user
user_hash = engine.adaptive_engine._hash_user("user123")
await engine.adaptive_engine.purge_user_data(user_hash)
```

2. **Data Portability**
```python
# Export user's learning data
export = await engine.adaptive_engine.export_user_data("user123")
```

3. **Opt-Out**
```python
# Disable for user
flags.disable_for_user("adaptive_suggestions", "user123")
```

### Automated Compliance

```python
# Auto-purge data older than 30 days
await engine.purge_adaptive_data(days=30)
```

---

## 🔍 Troubleshooting

### No Suggestions Appearing

1. Check feature flag: `flags.is_enabled("adaptive_suggestions", user_id)`
2. Check minimum samples: Need 5+ executions
3. Check confidence: Need >60% confidence
4. Check database: Ensure PostgreSQL connected

### Low Confidence Suggestions

- Wait for more executions (target: 50+)
- Check success rate of your executions
- Review parameter choices

### Privacy Concerns

- Enable `privacy_mode="strict"`
- Reduce `user_count` requirement
- Disable collaborative filtering

---

## 🎓 Best Practices

### For Developers

1. **Always check feature flags** before using suggestions
2. **Handle empty suggestions gracefully**
3. **Respect user privacy settings**
4. **Monitor suggestion quality metrics**

### For Users

1. **Start with provided suggestions** when available
2. **Provide feedback** on execution results
3. **Review suggestions before accepting**
4. **Disable if not helpful** (feature flag)

---

## 📊 Expected Outcomes

From Systems Audit:

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| Configuration Time | 100% | 40% | **-60%** |
| Error Rate | Baseline | -40% | **Better** |
| User Satisfaction | Baseline | +25% | **Higher** |
| System Complexity | 100% | 112% | **+12%** |

**ROI: 5:1** (utility gain to complexity increase)

---

## 🔮 Future Enhancements

1. **A/B Testing** - Compare suggestion algorithms
2. **Contextual Awareness** - Time of day, project type
3. **Transfer Learning** - Cross-template patterns
4. **Natural Language** - "I want a quick analysis"

---

## ✅ Verification Checklist

From Systems Audit Resilience Check:

- [x] **Adversarial Misuse** - Confidence thresholds, moderation
- [x] **Extreme Load** - Async calculation, Redis caching
- [x] **Regulatory Change** - GDPR compliance, opt-in
- [x] **Dependency Collapse** - Graceful degradation
- [x] **Maintenance Fatigue** - Simple Bayesian, not ML

**No critical fragility detected. ✅**

---

**EXPAND Mode Execution: COMPLETE** 🎉

The Adaptive Parameter Suggestion Engine is production-ready and adds reversible, high-value functionality to the Template Engine.
