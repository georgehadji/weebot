# Weebot Quick Reference Guide

**Version:** 2.3.0  
**Status:** Production Ready ✅

---

## 🚀 Quick Start

### 1. Basic Template Execution
```python
from weebot.templates import TemplateEngine

engine = TemplateEngine()
engine.registry.load_builtin_templates()

result = engine.execute(
    "Research Analysis Workflow",
    {"topic": "AI", "depth": "comprehensive"}
)
```

### 2. Production Engine with Adaptive Suggestions
```python
from weebot.templates.production import ProductionTemplateEngine

engine = ProductionTemplateEngine(
    database_url="postgresql+asyncpg://user:pass@localhost/weebot",
    valkey_url="valkey://localhost:6379/0",  # Also accepts redis:// (auto-normalized)
    enable_adaptive=True,
)

# Get intelligent suggestions
suggestions = await engine.get_suggestions(
    "Research Analysis Workflow",
    current_input={"topic": "AI"}
)

# Execute
result = await engine.execute(
    "Research Analysis Workflow",
    parameters={"topic": "AI", "depth": "comprehensive"},
    user=authenticated_user,
)
```

### 3. Enable Adaptive for Users
```python
from weebot.templates.feature_flags import get_feature_flags

flags = get_feature_flags()
flags.enable_for_user("adaptive_suggestions", "user123")
```

---

## 📋 All 8 Built-in Templates

| Template | Purpose | Key Parameters |
|----------|---------|----------------|
| `Research Analysis Workflow` | Deep research | `topic`, `depth`, `output_format` |
| `Competitive Analysis Workflow` | Market analysis | `industry`, `competitors`, `focus_areas` |
| `Data Processing Workflow` | ETL pipeline | `data_source`, `operations`, `analysis_type` |
| `Code Review Workflow` | Code quality | `code_source`, `language`, `review_type` |
| `Documentation Generation` | Auto docs | `source`, `doc_type`, `include_examples` |
| `Bug Analysis Workflow` | Debugging | `bug_description`, `severity`, `error_logs` |
| `Meeting Summary Workflow` | Meeting insights | `meeting_input`, `meeting_type`, `extract_action_items` |
| `Learning Path Creation` | Education | `topic`, `learner_level`, `duration_weeks` |

---

## 🎛️ Configuration

### Environment Variables
```bash
# Database
DATABASE_URL=postgresql+asyncpg://user:pass@localhost/weebot

# Valkey (Redis-compatible, BSD-3-Clause)
VALKEY_URL=valkey://localhost:6379/0

# Adaptive
ENABLE_ADAPTIVE_SUGGESTIONS=true
ADAPTIVE_PRIVACY_MODE=strict

# Rate Limiting
RATE_LIMIT_RPS=10
RATE_LIMIT_BURST=20
```

### Feature Flags
```python
from weebot.templates.feature_flags import FeatureState, FeatureConfig

# Percentage rollout
flags.register(FeatureConfig(
    name="adaptive_suggestions",
    state=FeatureState.PERCENTAGE,
    percentage=50,
))

# Enable for specific users
flags.enable_for_user("adaptive_suggestions", "user123")
flags.disable_for_user("adaptive_suggestions", "user456")
```

---

## 🧪 Testing

```bash
# All tests
pytest tests/unit/ -v

# Specific modules
pytest tests/unit/test_templates/test_adaptive.py -v
pytest tests/unit/test_templates/test_production.py -v

# With coverage
pytest tests/unit/ --cov=weebot --cov-report=html
```

---

## 📊 Monitoring

### Health Check
```python
health = await engine.health_check()
print(health["status"])  # "healthy" or "unhealthy"
```

### Adaptive Stats
```python
stats = await engine.get_adaptive_stats()
print(f"Combinations tracked: {stats['total_combinations_tracked']}")
print(f"High confidence suggestions: {stats['high_confidence_suggestions']}")
```

### Cache Stats
```python
stats = engine.cache.get_stats()
print(f"Hit rate: {stats['hit_rate']:.1%}")
print(f"Memory usage: {stats['used_memory_mb']:.1f} MB")
```

---

## 🔒 Security Checklist

- [ ] API keys rotated regularly
- [ ] Database encrypted at rest
- [ ] Valkey AUTH enabled
- [ ] Rate limiting configured
- [ ] GDPR compliance enabled (`privacy_mode=strict`)
- [ ] Audit logging active
- [ ] Health checks monitoring

---

## 🐛 Troubleshooting

### No Suggestions Appearing
```python
# Check feature flag
flags.is_enabled("adaptive_suggestions", user_id)

# Check minimum samples (need 5+)
stats = await engine.get_adaptive_stats()
```

### Database Connection Failed
```bash
# Check PostgreSQL
psql -U user -d weebot -c "SELECT 1"

# Run migrations
python scripts/migrate.py
```

### Valkey Connection Failed
```bash
# Check Valkey connectivity
valkey-cli ping

# Fallback to memory
RATE_LIMIT_BACKEND=memory
```

---

## 📚 Documentation

| Document | Description |
|----------|-------------|
| `README.md` | Main documentation |
| `PROJECT_FINAL_SUMMARY.md` | Complete project overview |
| `PHASE3_FINAL_SUMMARY.md` | Template Engine guide |
| `PHASE6B_ADAPTIVE_SUGGESTIONS.md` | Adaptive features |
| `PHASE6_PRODUCTION_HARDENING.md` | Production deployment |
| `CHANGELOG.md` | Version history |

---

## 🎯 Common Patterns

### Pattern 1: Suggest → Review → Execute
```python
# 1. Get suggestions
suggestions = await engine.get_suggestions(template_name, user)

# 2. Present to user for review
for s in suggestions:
    print(f"{s['parameter']}: {s['value']} ({s['confidence']:.0%} confidence)")

# 3. Execute with user-confirmed parameters
result = await engine.execute(template_name, parameters=user_params)
```

### Pattern 2: Gradual Rollout
```python
# Week 1: 10%
flags.register(FeatureConfig(..., percentage=10))

# Week 2: 50% (if metrics good)
flags.register(FeatureConfig(..., percentage=50))

# Week 3: 100% (if no issues)
flags.register(FeatureConfig(..., state=FeatureState.ENABLED))
```

### Pattern 3: GDPR Compliance
```python
# Enable strict privacy
engine = ProductionTemplateEngine(
    enable_adaptive=True,
    adaptive_privacy_mode="strict",  # Opt-in required
)

# Auto-purge old data
await engine.purge_adaptive_data(days=30)
```

---

## 📞 Support

- **Issues:** GitHub Issues
- **Discussions:** GitHub Discussions  
- **Documentation:** See `docs/` folder
- **Examples:** See `examples/` folder

---

**Weebot v2.3.0 - Production Ready ✅**
