# HARDEN Mode Staging Deployment Guide

**Version:** 2.3.0-harden  
**Date:** 2026-03-04  
**Status:** Ready for Staging

---

## Quick Start

```bash
# 1. Run deployment validation
python scripts/deploy_staging.py

# 2. If all tests pass, deploy to staging
./scripts/deploy_to_staging.sh

# 3. Verify metrics endpoint
curl http://staging.weebot.local/metrics

# 4. Check dashboards
open https://grafana.internal/d/weebot-harden
```

---

## Task 1: Deploy to Staging - Verify No Regressions

### Validation Script

**File:** `scripts/deploy_staging.py`

This script performs three-phase validation:

#### Phase 1: HARDEN Mode Implementation (5 tests)
- ✅ Privacy Audit Middleware validation
- ✅ Rate Limiter Bounds validation
- ✅ YAML Security Limits validation
- ✅ Circuit Breaker Jitter validation
- ✅ DB Pool Monitor validation

#### Phase 2: Regression Tests (4 tests)
- ✅ Circuit Breaker state machine
- ✅ Template Parser functionality
- ✅ Rate Limiter token bucket
- ✅ Workflow Orchestrator configuration

#### Phase 3: Integration Tests (1 test)
- ✅ Production Engine integration

### Running Validation

```bash
# Full validation
python scripts/deploy_staging.py

# Expected output:
# ============================================================
# HARDEN MODE STAGING DEPLOYMENT VALIDATION
# ============================================================
# [PHASE 1] HARDEN Mode Implementation Validation
#   [✓] Privacy Audit: Compliance tracking active
#   [✓] Rate Limiter Bounds: Max buckets: 10000
#   [✓] YAML Security: Limits working
#   [✓] Circuit Breaker Jitter: Variation: 47 values
#   [✓] DB Pool Monitor: Capacity tracking
# [PHASE 2] Regression Testing
#   [✓] CB Regression: State machine working
#   [✓] Parser Regression: Template parsing working
#   [✓] Rate Limiter Regression: Token bucket working
#   [✓] Orchestrator Regression: Configuration working
# [PHASE 3] Integration Testing
#   [✓] Production Engine: Hardening integrated
# ============================================================
# TOTAL: 10/10 passed, 0 failed
# ✓ ALL TESTS PASSED - READY FOR STAGING DEPLOYMENT
```

### Deployment Checklist

- [ ] Run `python scripts/deploy_staging.py` - all tests pass
- [ ] Check no import errors
- [ ] Verify existing unit tests still pass
- [ ] Deploy to staging environment
- [ ] Smoke test critical paths

---

## Task 2: Update Monitoring Dashboards

### Dashboard Configuration

**File:** `docs/monitoring_dashboard_config.yaml`

#### Import Instructions

**Grafana:**
1. Go to Dashboards → Import
2. Upload `docs/monitoring_dashboard_config.yaml`
3. Select your Prometheus datasource
4. Click Import

**Datadog:**
```bash
# Convert to Datadog format (requires dd-cli)
dd-cli dashboard import docs/monitoring_dashboard_config.yaml
```

**Custom (Prometheus + Grafana JSON):**
```python
from docs.monitoring_dashboard import generate_grafana_json

json_dashboard = generate_grafana_json(
    datasource="Prometheus",
    title="Weebot HARDEN Mode"
)
```

### Dashboard Panels

| Row | Panel | Metric | Target |
|-----|-------|--------|--------|
| 1 | Privacy Compliance Score | `weebot_privacy_compliance_score` | >95% |
| 1 | Privacy Violations (1h) | `increase(weebot_privacy_violations[1h])` | 0 |
| 2 | Rate Limiter Utilization | `active_buckets / max_buckets` | <80% |
| 2 | Bucket Evictions | `rate(weebot_ratelimiter_evictions[5m])` | <10/s |
| 3 | CB Recovery Rate | `weebot_circuitbreaker_recovery_rate` | >90% |
| 3 | State Changes/min | `rate(weebot_circuitbreaker_state_changes[1m])` | <50 |
| 4 | Pool Saturation | `weebot_dbpool_saturation` | <80% |
| 4 | Conn Acquisition (p95) | `histogram_quantile(0.95, ...)` | <1s |
| 5 | System Health Score | Composite | >70 |

### Metrics Endpoint

**File:** `weebot/templates/metrics_exporter.py`

#### Setup

```python
from weebot.templates.metrics_exporter import HardenModeMetrics

metrics = HardenModeMetrics()

# In your health check or metrics endpoint:
@app.get("/metrics")
async def get_metrics():
    return metrics.export_all_metrics(
        audit_middleware=privacy_audit,
        rate_limiter=rate_limiter,
        circuit_breaker=cb,
        pool_monitor=db_monitor,
    )
```

#### Available Metrics

**Privacy:**
- `weebot_privacy_compliance_score` (gauge, 0-1)
- `weebot_privacy_violations_total` (counter)
- `weebot_privacy_blocked_total` (counter)

**Rate Limiter:**
- `weebot_ratelimiter_active_buckets` (gauge)
- `weebot_ratelimiter_max_buckets` (gauge)
- `weebot_ratelimiter_utilization` (gauge, 0-1)
- `weebot_ratelimiter_evictions_total` (counter)
- `weebot_ratelimiter_rejections_total` (counter)

**Circuit Breaker:**
- `weebot_circuitbreaker_recovery_rate` (gauge, 0-1)
- `weebot_circuitbreaker_state_changes_total` (counter)
- `weebot_circuitbreaker_recovery_attempts_total` (counter)

**DB Pool:**
- `weebot_dbpool_saturation` (gauge, 0-1)
- `weebot_dbpool_active_connections` (gauge)
- `weebot_dbpool_saturation_alerts_total` (counter)

---

## Task 3: Set Alerting Thresholds

### Alerting Rules

**File:** `docs/alerting_rules.yaml`

#### Import to Prometheus AlertManager

```bash
# Copy rules to Prometheus
sudo cp docs/alerting_rules.yaml /etc/prometheus/rules/weebot-harden.yml

# Reload Prometheus
sudo systemctl reload prometheus
# or
curl -X POST http://localhost:9090/-/reload
```

#### Alert Summary

| Alert | Severity | Condition | Action |
|-------|----------|-----------|--------|
| `PrivacyViolationThresholdExceeded` | **critical** | >3 violations/hour | Disable collaborative filtering |
| `PrivacyComplianceScoreLow` | warning | <95% | Review violations |
| `RateLimiterHighUtilization` | warning | >80% capacity | Check user cardinality |
| `RateLimiterHighEvictionRate` | warning | >10 evictions/s | Increase MAX_BUCKETS |
| `YamlDoSAttackDetected` | **critical** | >10 blocks/min | Investigate attack |
| `CircuitBreakerLowRecoveryRate` | warning | <70% success | Check downstream health |
| `CircuitBreakerFlapping` | warning | >10 changes/min | Increase cooldown |
| `ManyCircuitsOpen` | **critical** | >10 circuits open | Check infrastructure |
| `DatabasePoolSaturation` | **critical** | >80% saturation | Check for leaks |
| `DatabaseSlowAcquisition` | warning | p95 >1s | Increase pool size |
| `HardenModeSystemHealthCritical` | **critical** | Composite <50 | Fallback A (defensive simplify) |

#### Trigger Mappings

| Alert | Trigger | Automated Response |
|-------|---------|-------------------|
| `PrivacyViolationThresholdExceeded` | T1 | Page on-call, suggest disable collaborative |
| `HardenModeSystemHealthCritical` | T3 | Recommend Fallback A (defensive simplify) |
| `HardenModeSystemHealthWarning` | T2 | Recommend Fallback B (shadow mode) |

### Notification Routing

```yaml
# PagerDuty for critical
critical → pagerduty-critical → immediate page

# Slack for warnings
warning → #weebot-alerts → team notification

# Security team for privacy
privacy alerts → #security-alerts → security review

# DBA team for database
database alerts → dba-team@ → DBA review
```

### Alert Inhibition

Prevents alert storms:
- System health critical → Suppresses component warnings
- Pool saturation → Suppresses slow acquisition (same root cause)

---

## Deployment Commands

```bash
# Step 1: Validation
python scripts/deploy_staging.py

# Step 2: Deploy (if validation passes)
git tag v2.3.0-harden
git push origin v2.3.0-harden

# Step 3: Staging deployment
kubectl apply -f k8s/staging/weebot-harden.yaml

# Step 4: Verify metrics
curl http://staging.weebot.local/metrics | grep weebot_

# Step 5: Check alerts
# Simulate: Privacy violation
curl -X POST http://staging.weebot.local/test/privacy-violation

# Step 6: Verify dashboards
open https://grafana.internal/d/weebot-harden
```

---

## Verification Checklist

### Immediate (0-1 hour)
- [ ] `/metrics` endpoint returns data
- [ ] All 10 validation tests pass
- [ ] No ERROR logs in application
- [ ] Dashboards show data

### Short-term (1-24 hours)
- [ ] Privacy compliance score >95%
- [ ] Rate limiter utilization <50%
- [ ] No circuit breaker flapping
- [ ] DB pool saturation <50%
- [ ] No unexpected alerts

### Medium-term (1-7 days)
- [ ] Alert thresholds appropriate
- [ ] No false positive alerts
- [ ] Metrics retention working
- [ ] Team trained on new dashboards

---

## Rollback Plan

If issues detected:

```bash
# Option 1: Full rollback
git revert HEAD
kubectl rollout undo deployment/weebot

# Option 2: Disable hardening features only
# Set environment variables:
WEEBOT_HARDEN_MODE=false
WEEBOT_ENABLE_PRIVACY_AUDIT=false
WEEBOT_ENABLE_RATE_LIMITER_BOUNDS=false
```

---

## Support

| Issue | Contact | Reference |
|-------|---------|-----------|
| Privacy alerts | security@company.com | `docs/privacy_audit.py` |
| Performance issues | perf@company.com | `HARDEN_MODE_IMPLEMENTATION.md` |
| False alerts | on-call | `docs/alerting_rules.yaml` |
| Dashboard issues | sre@company.com | `docs/monitoring_dashboard_config.yaml` |

---

## Next Steps

1. **Week 1:** Monitor staging metrics, tune thresholds
2. **Week 2:** Production canary deployment (10% traffic)
3. **Week 3:** Full production rollout if stable
4. **Day 30:** Review metrics, decide on EXPAND vs MAINTAIN

---

*Staging Deployment Guide v1.0 - HARDEN Mode*
