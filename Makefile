# Weebot — development convenience targets
.PHONY: help install test lint-imports check-arch check

help:
	@echo "Available targets:"
	@echo "  install       Install dependencies"
	@echo "  test          Run all tests"
	@echo "  lint-imports  Run import-linter architecture checks"
	@echo "  check-arch    Run all architecture verification gates"
	@echo "  check         Run full suite: tests + arch + lint"

install:
	pip install -r requirements.txt
	pip install import-linter

test:
	pytest tests/ -v --tb=short

lint-imports:
	@echo "=== Import-Linter Architecture Checks ==="
	lint-imports --config .importlinter
	@echo "All architecture contracts satisfied."

check-arch:
	@echo "=== Architecture Fitness Tests ==="
	pytest tests/unit/test_architecture_fitness.py -v --tb=short
	@echo ""
	@echo "=== Event Bridge Contract Tests ==="
	pytest tests/integration/test_event_bridge_contract.py -v --tb=short
	@echo ""
	@echo "=== Security Penetration Tests ==="
	pytest tests/integration/test_security_penetration.py -v --tb=short
	@echo ""
	@echo "=== E2E Persistence Tests ==="
	pytest tests/e2e/test_persistence.py -v --tb=short

check: test check-arch lint-imports
	@echo "=== All checks passed ==="
