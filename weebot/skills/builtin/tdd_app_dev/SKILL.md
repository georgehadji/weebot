---
name: tdd_app_dev
description: Test-Driven Development protocol for building apps and features. Enforces Red-Green-Refactor cycle. Triggered when building, implementing, or coding any app, feature, module, class, function, or API. Covers Python (pytest), JavaScript/TypeScript (Jest/Vitest), and web frameworks.
metadata:
  emoji: 🧪
  env: []
---

# TDD App Development

You are a **test-first developer**. Before writing any implementation code, you write a failing test. Then you write the minimum code to make it pass. Then you refactor.

**Non-negotiable rule**: If a step asks you to implement something, write the test file first and confirm it fails before writing any implementation.

**Fallback**: If the environment cannot run tests at all (no test runner installed, no package.json/requirements.txt, pure HTML/CSS task), skip TDD and implement directly — note the fallback in your output.

---

## The Cycle (always in this order)

```
RED   → Write a failing test that describes expected behavior
RUN   → Execute the test suite and confirm it FAILS
GREEN → Write the minimum implementation to make the test pass
RUN   → Execute the test suite and confirm it PASSES
CLEAN → Refactor for clarity without breaking tests
```

Never skip RUN steps. You must see a failure before you implement, and a pass after.

---

## Step 1 — Detect the language and test runner

Before writing anything, determine:

| Language | Test runner | Command |
|----------|------------|---------|
| Python | pytest | `pytest <test_file> -v` |
| JS/TS (Node) | jest | `npx jest <test_file> --no-coverage` |
| JS/TS (Vite) | vitest | `npx vitest run <test_file>` |
| JS/TS (web) | jest/vitest | detect from `package.json` scripts |

If the test runner is not installed:
- Python: `pip install pytest` (or check `requirements.txt`)
- JS: `npm install --save-dev jest` or `vitest`

---

## Step 2 — Write the test file FIRST

### Test file location rules

- Python: `tests/test_<module_name>.py` or `tests/unit/test_<module_name>.py`
- JS/TS: `<module>.test.ts` co-located, or `__tests__/<module>.test.ts`
- Use the same directory convention already present in the project. If none, default to `tests/`.

### Python test template

```python
import pytest
from <module_path> import <ClassName or function>

class Test<ClassName>:
    def test_<behavior>(self):
        # Arrange
        <setup>

        # Act
        result = <function_or_method_call>

        # Assert
        assert result == <expected>

    def test_<edge_case>(self):
        with pytest.raises(<ExceptionType>):
            <function_that_should_raise>
```

### JS/TS test template

```typescript
import { describe, it, expect } from 'vitest'  // or jest
import { <functionOrClass> } from './<module>'

describe('<ClassName or module>', () => {
  it('<should do expected behavior>', () => {
    // Arrange
    const input = <value>

    // Act
    const result = <functionOrClass>(input)

    // Assert
    expect(result).toEqual(<expected>)
  })

  it('throws on invalid input', () => {
    expect(() => <function>(null)).toThrow()
  })
})
```

### Coverage rules

Write tests for:
1. The happy path (normal inputs, expected output)
2. At least one edge case (empty, zero, null, boundary)
3. At least one error path (invalid input, exception expected)

Minimum: 3 tests per module being built. More is better, but do not block on 100% coverage before moving to GREEN.

---

## Step 3 — Run the tests and confirm RED

```bash
# Python
pytest tests/test_<module>.py -v

# JS/TS
npx jest <module>.test.ts --no-coverage
# or
npx vitest run <module>.test.ts
```

**You MUST see failures here.** If all tests pass without any implementation, the tests are wrong — go back and fix them.

Expected output shape:
```
FAILED tests/test_module.py::TestClass::test_behavior - ImportError / NameError / AssertionError
```

---

## Step 4 — Write the minimum implementation

Create or edit the source file. Rules:
- Write only what is needed to make the current tests pass
- Do NOT add features, methods, or logic not tested yet
- Keep functions small — one responsibility each
- Use type annotations (Python) or TypeScript types

### Python module template

```python
from __future__ import annotations

class <ClassName>:
    def <method>(self, <params>) -> <ReturnType>:
        <minimal implementation>
```

### TypeScript module template

```typescript
export function <name>(<params>: <Types>): <ReturnType> {
  <minimal implementation>
}

export class <ClassName> {
  <method>(<params>: <Types>): <ReturnType> {
    <minimal implementation>
  }
}
```

---

## Step 5 — Run the tests and confirm GREEN

Run the exact same command as Step 3. You MUST see all tests pass.

```
PASSED tests/test_module.py::TestClass::test_behavior
PASSED tests/test_module.py::TestClass::test_edge_case
```

If any test still fails:
- Read the error message carefully
- Fix only the failing assertion — do not rewrite passing tests
- Repeat until all green

---

## Step 6 — Refactor (CLEAN)

Once GREEN, you may improve:
- Extract helper functions for repeated logic
- Rename variables/functions for clarity
- Add docstrings for public interfaces
- Remove dead code

After every refactor change, re-run tests to confirm still GREEN.

---

## Multi-module apps

For apps with multiple modules (e.g., API + service + repository):

1. Start with the innermost layer (domain/service/utility) — it has no dependencies
2. Write tests for that layer → RED → GREEN → CLEAN
3. Move outward: write tests for the next layer mocking the inner one
4. Repeat up to the interface layer (CLI, HTTP handler, etc.)

This outside-in order prevents circular mocking and keeps tests fast.

---

## Framework-specific notes

### FastAPI

- Use `httpx.AsyncClient` + `TestClient` for endpoint tests
- Test the response status code, body shape, and error responses
- Mock external services (DB, third-party APIs) with `unittest.mock.patch`

```python
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_get_items():
    response = client.get("/items")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
```

### Next.js / React

- Unit-test pure functions and hooks with Vitest
- Use React Testing Library for component tests
- E2E tests with Playwright are optional unless user requests

```typescript
import { render, screen } from '@testing-library/react'
import { MyComponent } from './MyComponent'

it('renders the title', () => {
  render(<MyComponent title="Hello" />)
  expect(screen.getByText('Hello')).toBeInTheDocument()
})
```

---

## When TDD is NOT applicable (skip to direct implementation)

- Pure HTML/CSS static pages with no logic
- Configuration files (JSON, YAML, TOML)
- Shell scripts under 20 lines with no conditionals
- Asset generation (images, icons, fonts)
- Database migrations (schema changes — use migration tool directly)

In these cases, implement directly and add a note: `[TDD skipped: <reason>]`
