# Weebot — development convenience targets
.PHONY: help install test test-live gen-entry-twins lint-entry-twins gen-map-index lint-map lint-map-drift lint-imports lint-env-access lint-unawaited lint-ruleset lint-di-wiring lint-settings-construction lint-container-construction lint-module-cycles lint-import-exemptions lint-ruff lint-long-functions lint-ui lint-unused-locals lint-bandit-b110 lint-agent-json-parsing check-arch check

# Ratchet ceilings for gates with pre-existing debt. Each blocks only ABOVE its
# ceiling, so existing debt does not fail the build but nothing new can be added.
# Lower these as debt is paid; never raise them.
#
# NOTE on --exclude-dir: GNU grep matches it against a directory's BASE NAME, so
# the previous `--exclude-dir=weebot/GitNexus-main` and `--exclude-dir=weebot/config`
# never excluded anything. Both are corrected below; the ceilings are measured
# with the corrected exclusions.

help:
	@echo "Available targets:"
	@echo "  install       Install dependencies"
	@echo "  test          Run all tests (excludes external/live-network tests)"
	@echo "  test-live     Run tests including external/live, billed LLM calls"
	@echo "  lint-imports  Run import-linter architecture checks"
	@echo "  check-arch    Run all architecture verification gates"
	@echo "  check         Run full suite: tests + arch + lint"
	@echo "  generate-capabilities Generate capabilities schema for UI"

generate-capabilities:
	@echo "=== Generating Capabilities Atlas Schema ==="
	python scripts/generate_capabilities_schema.py

generate-config:
	@echo "=== Generating Configuration Reference ==="
	python scripts/generate_config_reference.py

install:
	pip install -r requirements.txt
	pip install import-linter

test:
	pytest tests/ -v --tb=short -m "not external"

test-live:
	WEEBOT_TEST_LIVE=1 pytest tests/ -v --tb=short

lint-imports:
	@echo "=== Import-Linter Architecture Checks ==="
	lint-imports --config .importlinter --verbose
	@echo "All architecture contracts satisfied."

lint-async-io:
	@echo "=== Async I/O Blocking Check ==="
	@python scripts/lint_async_io.py

lint-bare-except-pass:
	@echo "=== Silent except-handler check (AST, ratcheted) ==="
	@python scripts/lint_except_pass.py

lint-di-wiring:
	@echo "=== DI bindings that nothing resolves (AST, ratcheted) ==="
	@python scripts/lint_di_wiring.py

lint-unawaited:
	@echo "=== Un-awaited coroutine check (AST) ==="
	@python scripts/lint_unawaited_coroutines.py

lint-module-cycles:
	@echo "=== Module import cycles (AST + Tarjan SCC, ratcheted) ==="
	@python scripts/lint_module_cycles.py

lint-import-exemptions:
	@echo "=== Import exemptions and dynamic weebot imports (ratcheted) ==="
	@python scripts/lint_import_exemptions.py

lint-ruff:
	@echo "=== ruff violations at the configured rules (ratcheted) ==="
	@python scripts/lint_ruff_violations.py

lint-long-functions:
	@echo "=== Functions over 150 lines (AST, ratcheted) ==="
	@python scripts/lint_long_functions.py

lint-unused-locals:
	@echo "=== Unused local variables (ruff F841, ratcheted) ==="
	@python scripts/lint_unused_locals.py

lint-bandit-b110:
	@echo "=== try/except/pass sites (bandit B110, ratcheted) ==="
	@python scripts/lint_bandit_b110.py

lint-agent-json-parsing:
	@echo "=== Agent structured-output parsing (ratcheted) ==="
	@python scripts/lint_agent_json_parsing.py

lint-ui:
	@echo "=== weebot-ui debt (ratcheted) ==="
	@python scripts/lint_ui_debt.py
	@python scripts/check_ui_contrast.py

lint-ruleset:
	@echo "=== Ruleset / workflow consistency (offline) ==="
	@python scripts/check_ruleset_consistency.py

# The grep still does the counting; only the ceiling comparison moved to
# scripts/quality_ceilings.py, so centralising the rule cannot change a number.
lint-env-access:
	@echo "=== Bare os.environ / os.getenv Access Check (ratcheted) ==="
	@count=$$(grep -Prn "os\.environ(?!(\.get|\[))|os\.getenv\(" \
	    --include="*.py" \
	    --exclude-dir=tests \
	    --exclude-dir=.venv \
	    --exclude-dir=Output \
	    --exclude-dir=config \
	    --exclude-dir=GitNexus-main \
	    weebot/ cli/ | wc -l); \
	  python scripts/quality_ceilings.py --check bare_env_reads --actual "$$count" \
	    || { echo "Use SecretAccessor instead of a bare os.environ/os.getenv."; exit 1; }

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

lint-no-print:
	@echo "=== print() statement check (ratcheted) ==="
	@count=$$(grep -Prn "^\s*print\(" \
	    --include="*.py" \
	    --exclude-dir=tests \
	    --exclude-dir=.venv \
	    --exclude-dir=Output \
	    --exclude-dir=GitNexus-main \
	    weebot/ cli/ | wc -l); \
	  python scripts/quality_ceilings.py --check print_in_production --actual "$$count" \
	    || { echo "Use logger instead of print() in production code."; exit 1; }

gen-entry-twins:
	@python scripts/gen_entry_twins.py

lint-entry-twins:
	@echo "=== AGENTS/GEMINI/QWEN.md match CLAUDE.md ==="
	@python scripts/gen_entry_twins.py --check

gen-map-index:
	@python scripts/gen_map_index.py

lint-map:
	@echo "=== map/ and tasks/ indexes generated, card citations resolve ==="
	@python scripts/gen_map_index.py --check
	@python scripts/check_map_citations.py
	@python scripts/gen_tasks_index.py --check

# Drift is enforced by `make check` (run it, or `check_map_citations.py --fix`, after moving cited
# code) and reported by CI as an advisory step, so one code move does not turn every PR red.
lint-map-drift:
	@python scripts/check_map_citations.py --drift

lint-settings-construction:
	@echo "=== Direct WeebotSettings() construction (AST, ratcheted) ==="
	@python scripts/lint_settings_construction.py

lint-container-construction:
	@echo "=== Hand-built Container() outside application/di (AST, ratcheted) ==="
	@python scripts/lint_container_construction.py

check: test check-arch lint-imports lint-bare-except-pass lint-async-io lint-unawaited lint-env-access lint-no-print lint-ruleset lint-di-wiring lint-entry-twins lint-map lint-map-drift lint-settings-construction lint-container-construction lint-module-cycles lint-import-exemptions lint-ruff lint-long-functions lint-ui lint-unused-locals lint-bandit-b110 lint-agent-json-parsing
	@echo "=== All checks passed ==="
