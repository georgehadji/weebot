# Weebot Redis-to-Valkey Migration Plan

## 1. Executive Summary
This document outlines a thorough, step-by-step plan to swap **Redis** with **Valkey** within the Weebot AI Agent Framework. 

Following Redis's license transition in 2024 to a non-free model, the open-source community created **Valkey** under the BSD-3-Clause license, hosted by the Linux Foundation and backed by industry leaders (including AWS, Google Cloud, and Oracle). Valkey is a high-performance, fully open-source, and fully compatible drop-in replacement for Redis 7.2.4+.

To align Weebot with absolute open-source standards, we are transitioning our caching, rate-limiting, and diagnostic infrastructure to utilize Valkey as our default in-memory key-value store. This migration leverages **`valkey-py`** (the official, highly compatible Python client for Valkey) to ensure seamless API and feature parity.

---

## 2. Current Architecture Impact Analysis

Weebot uses in-memory caching and rate limiting primarily inside its template engine and production workflow coordinator. The following components will be affected by this migration:

| Component | Current Implementation | Proposed Valkey Replacement |
| :--- | :--- | :--- |
| **Dependencies** | `redis` package in Python requirements | `valkey` package (`valkey-py` client) |
| **Caching Layer** | `RedisCache` in `weebot/templates/production.py` | Refactored `ValkeyCache` (with a deprecated `RedisCache` alias for backward-compatibility) |
| **Egress Security** | Redis URI patterns in `weebot/core/egress_guard.py` | Support for both `redis://` and `valkey://` URI patterns |
| **Documentation** | `redis-cli` commands in `QUICK_REFERENCE.md` | `valkey-cli` commands |
| **Diagnostics** | Model/service health monitoring checks | Refactored check for Valkey connection |

---

## 3. Python Client Selection & Parity

We select **`valkey-py`** (installed via `pip install valkey`) as Weebot's Python client. 

### Why `valkey-py` over `valkey-glide`?
* **Drop-in Compatibility:** `valkey-py` is a direct fork of `redis-py` (retaining full import, initialization, and command structure parity). This allows a surgical swap with zero risk of breaking active API patterns.
* **RESP2/RESP3 Support:** Full support for Valkey's network protocol versions.
* **Low Migration Cost:** `valkey-py` provides a compatibility module allowing `import valkey as redis`, simplifying transitional code.

### Command Mapping Parity:
All Redis operations used by Weebot translate exactly to Valkey commands:
* `GET` / `SET` / `DELETE` -> Maps identically to Valkey.
* `EXPIRE` / `SETEX` -> Maps identically to Valkey.
* `HMSET` / `HGETALL` -> Maps identically to Valkey.
* `PIPELINE` -> Maps identically to Valkey pipelines.

---

## 4. Step-by-Step Implementation Roadmap

### Step 1: Update Dependency Specifications
Replace the legacy `redis` library with `valkey` in our dependency files.

* **File:** `requirements.txt` (and `pyproject.toml` if applicable)
* **Changes:**
  ```text
  # Remove: redis>=5.0.0
  valkey>=1.0.0
  ```

---

### Step 2: Refactor Caching & Rate-Limiting Interfaces
Refactor Weebot's caching engine to import and configure the `valkey` client instead of `redis`.

* **File:** `weebot/templates/production.py`
* **Changes:**
  1. Swap the imports:
     ```python
     # Replace:
     # import redis
     # With:
     import valkey as redis  # Transitional compatibility
     ```
  2. Implement `ValkeyCache` inheriting from / replacing `RedisCache`:
     ```python
     # Refactor RedisCache to ValkeyCache:
     class ValkeyCache:
         """Valkey-based caching for templates and results."""
         
         def __init__(
             self,
             valkey_url: str = "valkey://localhost:6379/0",
             default_ttl: int = 3600,
         ):
             # Support fallback to redis:// URLs automatically
             if valkey_url.startswith("redis://"):
                 valkey_url = valkey_url.replace("redis://", "valkey://", 1)
             
             import valkey
             self.redis = valkey.from_url(valkey_url, decode_responses=True)
             self.default_ttl = default_ttl
             
         # Keep all get_template, set_template methods unchanged (Valkey client is 100% API compatible)
     
     # Retain backward-compatibility alias
     RedisCache = ValkeyCache
     ```
  3. Update initialization patterns in `ProductionEnvironment` to accept `valkey_url` while dynamically adapting `redis_url` to avoid breaking downstream setups.

---

### Step 3: Upgrade Egress Guard Rules
Weebot's safety layer must screen for leaked Valkey connection details (which can carry passwords or sensitive endpoints) just as it does for Redis.

* **File:** `weebot/core/egress_guard.py`
* **Changes:**
  Update the connection-string regex to capture both `redis://` and `valkey://` patterns:
  ```python
  # Old:
  # re.compile(r'(?:postgres|mysql|mongodb|redis)://[^\s<>"]+', re.IGNORECASE)
  
  # New:
  re.compile(r'(?:postgres|mysql|mongodb|redis|valkey)://[^\s<>"]+', re.IGNORECASE)
  ```

---

### Step 4: Update Diagnostics & Model Health Tests
Refactor Weebot's internal diagnostics (`doctor` check) to verify Valkey connectivity.

* **File:** `weebot/templates/production.py` (and related clinical doctor tools)
* **Changes:**
  Update check descriptions to output `valkey` health check status:
  ```python
  def check_valkey(self) -> bool:
      """Check Valkey connectivity."""
      if not self.redis:
          return True  # No Valkey configured
      try:
          self.redis.ping()
          return True
      except Exception:
          return False
  ```

---

### Step 5: Update Infrastructure & Compose Configurations
Ensure that standard multi-process deployments deploy Valkey instead of Redis.

* **File:** Future docker-compose configs (or `docker-compose.yml` if externalized)
* **Image Swap:**
  ```yaml
  # Replace:
  # image: redis:7-alpine
  # With:
  image: valkey/valkey:8-alpine
  ```

---

### Step 6: Refactor Documentation & Quick References
Ensure developers are using up-to-date Valkey operations.

* **File:** `QUICK_REFERENCE.md`
* **Updates:**
  Update references from Redis to Valkey:
  ```markdown
  # Valkey
  VALKEY_URL=valkey://localhost:6379/0
  
  # Troubleshooting Connection:
  valkey-cli ping
  ```

---

## 5. Risk & Mitigation Matrix

| Risk | Impact | Likelihood | Mitigation Strategy |
| :--- | :--- | :--- | :--- |
| **Server/Library Version Mismatch** | Medium | Low | Weebot's default client utilizes `valkey-py` which supports both standard Redis protocols (RESP2) and Valkey protocols (RESP3), ensuring backward-compatibility with older Redis instances. |
| **Legacy connection configs (`redis://`) crash** | High | Medium | `ValkeyCache` initialization parses the connection URL and automatically normalizes any `redis://` schemas to `valkey://` schemas seamlessly. |
| **Production performance degradation** | Low | Low | Valkey has proven benchmarks showing 10–20% throughput improvements over standard Redis 7.2. Valkey GLIDE is available as a high-performance fallback if needed. |

---

## 6. Testing & Quality Assurance Plan

### 1. Mock-Based Unit Testing
Ensure all operations function perfectly without a live Valkey instance running:
* **File:** `tests/unit/templates/test_production_valkey.py`
* **Test cases:**
  - Verify `ValkeyCache` correctly initializes with both `valkey://` and `redis://` URLs.
  - Verify `get_template` and `set_template` operations trigger appropriate mock client calls.
  - Assert that importing `RedisCache` from `weebot.templates` resolved correctly to `ValkeyCache`.

### 2. Live Docker Verification (Smoke Test)
Validate connectivity on a live environment:
1. Start Valkey container:
   ```bash
   docker run --name valkey-test -p 6379:6379 -d valkey/valkey:8-alpine
   ```
2. Run diagnostic tests to verify active caching:
   ```bash
   pytest tests/unit/ -v --tb=short
   ```
3. Destroy test container:
   ```bash
   docker rm -f valkey-test
   ```
