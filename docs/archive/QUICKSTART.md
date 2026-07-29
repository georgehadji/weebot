# Weebot Quick Start Guide

Οδηγός γρήγορης εκκίνησης για το Weebot με Web UI.

---

## 🚀 Εκκίνηση (3 Βήματα)

### Βήμα 1: Backend Server (Terminal 1)

```bash
cd E:\Documents\Vibe-Coding\weebot
python start_backend.py
```

Θα δεις:
```
============================================================
Starting Weebot Backend Server
============================================================

URL: http://localhost:8000
WebSocket: ws://localhost:8000/ws
API Docs: http://localhost:8000/docs

Press Ctrl+C to stop
============================================================

INFO:     Uvicorn running on http://0.0.0.0:8000
```

**Πρέπει να μείνει ανοιχτό αυτό το terminal!**

---

### Βήμα 2: Frontend (Terminal 2)

```bash
cd E:\Documents\Vibe-Coding\weebot\weebot-ui
npm run dev
```

Θα δεις:
```
  VITE v5.x.x  ready in XXX ms

  ➜  Local:   http://localhost:3000/
  ➜  Network: http://192.168.x.x:3000/
```

---

### Βήμα 3: Άνοιγμα Browser

Άνοιξε: http://localhost:3000

---

## 🔧 Αντιμετώπιση Προβλημάτων

### ❌ "WebSocket error" στο browser console

**Αιτία:** Το backend δεν τρέχει.

**Λύση:**
1. Βεβαιώσου ότι το Terminal 1 (backend) είναι ανοιχτό
2. Έλεγξε ότι δεν υπάρχει error στο terminal
3. Δοκίμασε: http://localhost:8000/ (πρέπει να δεις "Weebot Web UI")

### ❌ "Connection refused" στο frontend

**Αιτία:** Το backend δεν ακούει στη σωστή port.

**Λύση:**
```bash
# Έλεγχος αν η port 8000 είναι ελεύθερη
netstat -ano | findstr :8000

# Αν είναι κατειλημμένη, σκότωσε την:
taskkill /PID <PID> /F
```

### ❌ CORS errors

**Αιτία:** Το CORS δεν είναι σωστά ρυθμισμένο.

**Λύση:** Το CORS είναι ήδη ρυθμισμένο στο `weebot/interfaces/web/main.py`:
```python
allow_origins=["*"]  # Επιτρέπει όλα τα origins
```

Αν εξακολουθεί να μην δουλεύει, δοκίμασε hardcoded:
```python
allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"]
```

---

## 🧪 Έλεγχος με Diagnostic Tool

```bash
cd E:\Documents\Vibe-Coding\weebot
python check_websocket.py
```

Αναμενόμενο αποτέλεσμα:
```
============================================================
Weebot WebSocket Diagnostic Tool
============================================================

============================================================
1. Checking HTTP Server
============================================================
[OK] HTTP server is running (status 200)

============================================================
2. Checking Global WebSocket (/ws)
============================================================
[OK] Global WebSocket connected successfully

============================================================
3. Checking Session WebSocket (/ws/sessions/test-id)
============================================================
[OK] Session WebSocket connected successfully
```

---

## 📁 Παραδείγματα Κώδικα

Βρίσκονται στο φάκελο `examples/phase11/`:

```bash
# Εκτέλεση όλων των παραδειγμάτων
cd examples/phase11
python run_all.py

# Ή ξεχωριστά:
python 01_basic_usage.py      # Structured output
python 02_bash_safety.py      # Security
python 03_event_logging.py    # Event logging
```

---

## 📝 Βασικές Εντολές CLI

```bash
# Εκτέλεση εργασίας
python -m cli.main flow run "Φτιάξε μια Python συνάρτηση για Fibonacci"

# Προβολή sessions
python -m cli.main flow list

# Logs
python -m cli.main logs list
python -m cli.main logs show <session_id>

# Health check
python -m cli.main health
```

---

## 🔄 Συνήθης Ροή Εργασίας

```
1. Εκκίνηση backend (Terminal 1) - αφήνουμε ανοιχτό
2. Εκκίνηση frontend (Terminal 2) - αφήνουμε ανοιχτό
3. Άνοιγμα http://localhost:3000 στο browser
4. Χρήση του Web UI για εργασίες
5. Για CLI: νέο Terminal 3
```

---

**Version:** 2.7.0  
**Last Updated:** 2026-04-05
