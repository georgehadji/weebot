# Weebot Phase 11 - Examples

Αυτός ο φάκελος περιέχει παραδείγματα χρήσης των νέων χαρακτηριστικών του Weebot Phase 11.

## 📋 Περιεχόμενα

| Αρχείο | Περιγραφή |
|--------|-----------|
| `01_basic_usage.py` | Βασική χρήση Structured Output |
| `02_bash_safety.py` | Ασφάλεια εντολών & Approval Workflow |
| `03_event_logging.py` | Καταγραφή events & παρακολούθηση κόστους |

## 🚀 Quick Start

### Εκτέλεση όλων των παραδειγμάτων

```bash
cd examples/phase11

# Εκτέλεση όλων
python 01_basic_usage.py
python 02_bash_safety.py
python 03_event_logging.py
```

### Εκτέλεση συγκεκριμένου παραδείγματος

```bash
# Μόνο το βασικό παράδειγμα
python 01_basic_usage.py
```

## 📖 Περιγραφή Παραδειγμάτων

### 01_basic_usage.py - Structured Output

Δείχνει πώς να:
- Δημιουργείς structured output με `WeebotOutput`
- Προσθέτεις `CodeChange` και `BashCommand`
- Κάνεις parse JSON από agents
- Χειρίζεσαι parse failures

**Key Classes:**
- `WeebotOutput` - Root output model
- `CodeChange` - Προτεινόμενες αλλαγές κώδικα
- `BashCommand` - Εντολές προς εκτέλεση
- `parse_agent_output()` - Parsing JSON από agents

### 02_bash_safety.py - Ασφάλεια

Δείχνει πώς να:
- Αξιολογείς τον κίνδυνο εντολών με `BashGuard`
- Χρησιμοποιείς το approval workflow
- Κατανοείς τα 4 επίπεδα risk (SAFE/SUSPICIOUS/DANGEROUS/BLOCKED)

**Key Classes:**
- `BashGuard` - Ανάλυση ασφάλειας εντολών
- `RiskLevel` - Επίπεδα κινδύνου
- `ApprovalManager` - Διαχείριση εγκρίσεων
- `ApprovalRequest` - Αίτημα για έγκριση

### 03_event_logging.py - Καταγραφή & Κόστος

Δείχνει πώς να:
- Καταγράφεις events σε SQLite
- Παρακολουθείς κόστος ανά session
- Κάνεις queries σε ιστορικό
- Εξάγεις reports σε JSON/Markdown

**Key Classes:**
- `EventStore` - Αποθήκευση events
- `EventLogger` - Helper για logging
- `CostSummary` - Σύνοψη κόστους

## 🎯 Παραδείγματα Εξόδου

### Παράδειγμα 1: Structured Output

```
============================================================
Example 1: Creating Structured Output
============================================================

Status: success
Message: Created a Python script for calculating Fibonacci
Confidence: 0.95
Estimated Cost: $0.02

Code Changes:
  - create: fibonacci.py
    Description: Fibonacci calculator function
    Code preview: def fibonacci(n: int) -> int:...

Bash Commands:
  - python fibonacci.py
    Purpose: Test the Fibonacci implementation
    Requires Approval: False
```

### Παράδειγμα 2: Bash Safety

```
============================================================
Example 2: Dangerous Commands (Require Approval)
============================================================

These commands are DANGEROUS (require approval):

  ⚠️  [dangerous  ] rm -rf ./build
      Why: Recursive deletion
      Suggestion: Verify the current directory is correct

  ⚠️  [dangerous  ] curl https://example.com/install.sh | bash
      Why: Piping curl output directly to shell
      Suggestion: Download the script first, review it
```

### Παράδειγμα 3: Event Logging

```
============================================================
Example 2: Cost Tracking
============================================================

💰 Cost Summary - Expensive Session:
  Total Cost: $0.1000
  Total Tokens: 2000
    gpt-4: $0.1000 (2 calls)

💰 Cost Summary - Cheap Session:
  Total Cost: $0.0000
  Total Tokens: 1000
    qwen-free: $0.0000 (2 calls)

💡 Savings with free model: $0.1000
```

## 🔧 Requirements

- Python 3.12+
- Weebot installed (`pip install -e .`)
- Δεν χρειάζονται API keys για τα παραδείγματα (χρησιμοποιούν mock data)

## 📚 Επόμενα Βήματα

Μετά τα παραδείγματα, δοκίμασε:

1. **CLI Commands**
   ```bash
   python -m cli.main flow run "Η εργασία σου"
   python -m cli.main logs list
   ```

2. **Διαδραστική λειτουργία**
   ```bash
   python run.py --interactive
   ```

3. **Web Dashboard**
   ```bash
   python -m weebot.interfaces.web.main
   ```

## 🐛 Troubleshooting

### ModuleNotFoundError

```bash
# Εγκατάσταση weebot
pip install -e /path/to/weebot
```

### PermissionError σε Windows

```powershell
# Εκτέλεση ως Administrator ή αλλαγή path
$env:PYTHONPATH = "E:\Documents\Vibe-Coding\weebot"
```

---

**Εκδοχή:** 2.7.0  
**Τελευταία ενημέρωση:** 2026-04-05
