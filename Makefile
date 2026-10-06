PYTHON ?= python3
BACKEND := backend/.venv/bin

.PHONY: check plan check-schema check-evidence check-validators
check:
	$(PYTHON) scripts/check_specs.py

plan:
	$(PYTHON) scripts/check_specs.py --plan

check-schema:
	$(PYTHON) scripts/check_schema.py

check-evidence:
	$(PYTHON) scripts/check_evidence.py

check-validators:
	$(PYTHON) scripts/check_validator_behaviour.py

.PHONY: setup deps up down bootstrap dev lint typecheck test-unit test-integration check-contracts test-browser test-migration test-identity build smoke check-runtime test-performance test-security test-operations verify package
.PHONY: screenshots
screenshots:
	$(PYTHON) scripts/capture_workspace.py

setup:
	$(PYTHON) scripts/setup_local.py

deps: setup
	uv sync --project backend --frozen
	npm ci --prefix frontend

up: setup
	docker compose up --build -d

down:
	docker compose down

bootstrap:
	$(BACKEND)/python -m scopegate.bootstrap

dev: deps
	$(PYTHON) scripts/develop.py

lint:
	$(BACKEND)/ruff check backend/src backend/tests identity_provider scripts
	$(BACKEND)/python scripts/check_architecture.py
	npm --prefix frontend run lint

typecheck:
	$(BACKEND)/mypy --config-file backend/pyproject.toml backend/src identity_provider
	npm --prefix frontend run typecheck

test-unit:
	$(BACKEND)/pytest backend/tests/test_policy.py backend/tests/test_cli.py backend/tests/test_runtime.py backend/tests/test_tracing.py scripts/tests -m 'not integration' -q
	$(BACKEND)/python scripts/check_policy_mutations.py
	npm --prefix frontend test -- --reporter=default --reporter=json --outputFile=$${SCOPEGATE_VITEST_RESULTS:-../artifacts/unit/results.json}

test-integration:
	$(BACKEND)/pytest backend/tests -m 'integration and not performance and not operations' -q

check-contracts:
	$(BACKEND)/pytest backend/tests/test_contracts.py -q
	npm --prefix frontend run types:check

test-browser:
	npm --prefix frontend run test:browser

test-migration:
	$(BACKEND)/pytest backend/tests/test_diagnosis.py backend/tests/test_migration.py -q

test-identity:
	$(BACKEND)/pytest backend/tests/test_identity.py backend/tests/test_invitations.py -q

build:
	npm --prefix frontend run build
	docker compose build

smoke:
	$(BACKEND)/python scripts/check_runtime.py

check-runtime: check check-validators smoke

test-performance:
	$(BACKEND)/pytest backend/tests/test_performance.py -q

test-security:
	$(BACKEND)/pytest backend/tests -m security -q
	$(BACKEND)/python scripts/audit_dependencies.py

test-operations:
	$(BACKEND)/pytest backend/tests/test_delivery.py backend/tests/test_operations.py backend/tests/test_alerts.py backend/tests/test_runtime.py backend/tests/test_tracing.py -q
	$(BACKEND)/python scripts/rehearse_worker.py
	$(BACKEND)/python scripts/rehearse_proxy.py
	docker compose --profile maintenance run --rm --build operations --help

verify:
	$(BACKEND)/python scripts/record_evidence.py

package:
	$(PYTHON) scripts/package_review.py
