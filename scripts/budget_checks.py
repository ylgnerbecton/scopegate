"""Check proposed operational contract arithmetic without certifying runtime."""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from pathlib import Path

Require = Callable[[bool, str], None]
CONTRACTS = {
    "resilience": "resilience_configuration",
    "slo": "service_objectives",
    "capacity": "capacity_and_query_budget",
}
REQUIRED_VALUES = {
    "resilience": (
        "http_deadline", "identity_callback_deadline", "http_response_reserve",
        "database_lock", "database_statement", "database_transaction", "oidc_connect",
        "oidc_read", "oidc_exchange", "delivery_connect", "delivery_read", "delivery_attempt",
        "outbox_lease", "outbox_attempts_per_generation", "http_drain",
        "supervisor_termination_grace", "session_idle_bound", "session_maximum_lifetime",
        "sensitive_authentication_age",
    ),
    "slo": ("availability_target", "availability_window", "latency_target"),
    "capacity": (
        "http_replicas", "http_workers_per_replica", "http_pool_size", "http_pool_overflow",
        "outbox_workers", "outbox_pool_size", "outbox_pool_overflow",
        "operations_connection_allocation", "backfill_connections_within_operations",
        "database_connection_reserve", "application_connection_allocation",
        "database_max_connections", "rollout_maximum_surge", "minimum_ready_http_replicas",
        "normal_arrival", "sustained_peak_arrival", "burst_arrival",
        "mean_request_residence", "mean_database_checkout", "default_page", "maximum_page",
        "grant_additions", "grant_removals", "changed_grant_response",
    ),
}
DISCRETE_UNITS = {
    "rows", "requests", "replicas", "http_replicas", "processes", "connections",
    "connections_per_worker", "references", "attempts_including_initial", "calls",
    "consecutive_failures", "bytes",
}
EXPECTED_UNITS = {
    "resilience": dict.fromkeys(REQUIRED_VALUES["resilience"], "milliseconds") | {
        "outbox_lease": "seconds", "outbox_attempts_per_generation": "attempts_including_initial",
        "http_drain": "seconds", "supervisor_termination_grace": "seconds",
        "session_idle_bound": "seconds", "session_maximum_lifetime": "seconds",
        "sensitive_authentication_age": "seconds",
    },
    "slo": {
        "availability_target": "good_requests_per_eligible_request",
        "availability_window": "rolling_days",
        "latency_target": "within_endpoint_budget_per_eligible_attempt",
    },
    "capacity": {
        "http_replicas": "replicas", "http_workers_per_replica": "processes",
        "http_pool_size": "connections_per_worker", "http_pool_overflow": "connections_per_worker",
        "outbox_workers": "processes", "outbox_pool_size": "connections_per_worker",
        "outbox_pool_overflow": "connections_per_worker", "operations_connection_allocation": "connections",
        "backfill_connections_within_operations": "connections", "database_connection_reserve": "connections",
        "application_connection_allocation": "connections", "database_max_connections": "connections",
        "rollout_maximum_surge": "http_replicas", "minimum_ready_http_replicas": "replicas",
        "normal_arrival": "requests_per_second", "sustained_peak_arrival": "requests_per_second",
        "burst_arrival": "requests_per_second", "mean_request_residence": "milliseconds",
        "mean_database_checkout": "milliseconds", "default_page": "rows", "maximum_page": "rows",
        "grant_additions": "references", "grant_removals": "references", "changed_grant_response": "rows",
    },
}


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key}")
        result[key] = value
    return result


def _read(root: Path, relative: str, require: Require) -> dict:
    try:
        result = json.loads((root / relative).read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
        if not isinstance(result, dict):
            raise TypeError("JSON root must be an object")
        return result
    except (OSError, ValueError, TypeError) as error:
        require(False, f"{relative}: {error}")
        return {}


def _numeric(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _references(root: Path, document: dict, gates: set, label: str, require: Require) -> None:
    docs = document.get("canonical_documents", [])
    require(isinstance(docs, list) and bool(docs), f"{label}: canonical documents required")
    for relative in docs:
        candidate = (root / str(relative)).resolve()
        require(candidate.is_relative_to(root.resolve()) and candidate.is_file(), f"{label}: invalid document {relative}")
    referenced = document.get("evidence_gates", [])
    require(isinstance(referenced, list) and bool(referenced), f"{label}: evidence gates required")
    for gate in referenced:
        require(gate in gates, f"{label}: unknown gate {gate}")


def _metadata(root: Path, document: dict, kind: str, gates: set, require: Require) -> None:
    require(document.get("schema_version") == 1, f"{kind}: schema version must be one")
    require(document.get("project") == "Scopegate", f"{kind}: project mismatch")
    require(document.get("contract_type") == CONTRACTS[kind], f"{kind}: contract type mismatch")
    require(document.get("status") == "proposed", f"{kind}: values must remain explicitly proposed")
    require(document.get("implemented") is False, f"{kind}: cannot claim implemented runtime")
    owners = document.get("owners")
    require(isinstance(owners, list) and bool(owners), f"{kind}: owner list required")
    _references(root, document, gates, kind, require)


def _parameter(name: str, item: object, owners: list, gates: set, require: Require) -> bool:
    if not isinstance(item, dict):
        require(False, f"{name}: parameter must be an object")
        return False
    unit = item.get("unit")
    require(isinstance(unit, str) and bool(unit), f"{name}: unit required")
    require(item.get("owner") in owners, f"{name}: unknown owner")
    require(item.get("evidence_gate") in gates, f"{name}: unknown evidence gate")
    values = [item.get(key) for key in ("minimum", "value", "maximum")]
    if not all(_numeric(value) for value in values):
        require(False, f"{name}: finite numeric range and value required")
        return False
    minimum, value, maximum = values
    require(minimum <= value <= maximum, f"{name}: value outside declared range")
    if isinstance(unit, str) and unit in DISCRETE_UNITS:
        require(type(value) is int, f"{name}: discrete count must be an integer")
    return True


def _unit_checks(document: dict, kind: str, require: Require) -> None:
    parameters = document.get("parameters", {})
    if not isinstance(parameters, dict):
        return
    for name, unit in EXPECTED_UNITS[kind].items():
        item = parameters.get(name, {})
        if isinstance(item, dict):
            require(item.get("unit") == unit, f"{kind}.{name}: arithmetic requires {unit}")


def _values(document: dict, kind: str, gates: set, require: Require) -> dict | None:
    parameters = document.get("parameters", {})
    if not isinstance(parameters, dict):
        require(False, f"{kind}: parameters must be an object")
        return None
    result = {}
    for name, item in parameters.items():
        if _parameter(f"{kind}.{name}", item, document.get("owners", []), gates, require):
            result[name] = item["value"]
    missing = set(REQUIRED_VALUES[kind]) - set(result)
    require(not missing, f"{kind}: missing numeric values {sorted(missing)}")
    return None if missing else result


def _equals(actual: object, expected: float, label: str, require: Require) -> None:
    require(_numeric(actual) and math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-9), f"{label}: arithmetic mismatch")


def _pool_checks(p: dict, document: dict, require: Require) -> None:
    per_replica = p["http_workers_per_replica"] * (p["http_pool_size"] + p["http_pool_overflow"])
    http = p["http_replicas"] * per_replica
    outbox = p["outbox_workers"] * (p["outbox_pool_size"] + p["outbox_pool_overflow"])
    use = http + outbox + p["operations_connection_allocation"]
    allocation = p["application_connection_allocation"]
    reserve = p["database_connection_reserve"]
    engine_max = p["database_max_connections"]
    require(use <= allocation, "capacity: connection use exceeds application allocation")
    require(allocation + reserve <= engine_max, "capacity: allocation and reserve exceed database maximum")
    require(use + p["rollout_maximum_surge"] * per_replica <= allocation, "capacity: rollout overlap exceeds allocation")
    require(p["backfill_connections_within_operations"] <= p["operations_connection_allocation"], "capacity: backfill reserve exceeds operations allocation")
    require(1 <= p["minimum_ready_http_replicas"] <= p["http_replicas"], "capacity: invalid minimum ready replica count")
    examples = document.get("connection_budget", {})
    expected = {
        "proposed_http_connections": http, "proposed_outbox_connections": outbox,
        "proposed_application_and_operations_use": use, "proposed_allocation": allocation,
        "proposed_unused_allocation": allocation - use, "proposed_use_plus_reserve": use + reserve,
        "third_http_replica_use": use + per_replica, "third_http_replica_use_plus_reserve": use + per_replica + reserve,
    }
    for name, value in expected.items():
        _equals(examples.get(name), value, f"capacity.connection_budget.{name}", require)


def _concurrency_checks(p: dict, document: dict, require: Require) -> None:
    examples = document.get("concurrency_examples", {})
    expected = {
        "ordinary_mean_in_flight": p["normal_arrival"] * p["mean_request_residence"] / 1000,
        "peak_mean_in_flight": p["sustained_peak_arrival"] * p["mean_request_residence"] / 1000,
        "burst_mean_in_flight": p["burst_arrival"] * p["mean_request_residence"] / 1000,
        "peak_mean_database_occupancy": p["sustained_peak_arrival"] * p["mean_database_checkout"] / 1000,
        "burst_mean_database_occupancy": p["burst_arrival"] * p["mean_database_checkout"] / 1000,
    }
    for name, value in expected.items():
        _equals(examples.get(name), value, f"capacity.concurrency_examples.{name}", require)
    require(examples.get("p95_is_not_mean") is True, "capacity: Little's law must use mean residence")
    require(sum(document.get("workload_mix_percent", {}).values()) == 100, "capacity: workload mix must sum to 100")
    mutation = sum(document.get("mutation_mix_percent_of_all_requests", {}).values())
    _equals(mutation, document.get("workload_mix_percent", {}).get("access_mutations", 0), "capacity.mutation_mix", require)


def _timeout_checks(p: dict, require: Require) -> None:
    require(p["database_lock"] < p["database_statement"] <= p["database_transaction"], "resilience: lock/statement/transaction hierarchy invalid")
    require(p["database_transaction"] < p["http_deadline"] - p["http_response_reserve"], "resilience: transaction consumes response reserve")
    require(p["oidc_connect"] + p["oidc_read"] <= p["oidc_exchange"] < p["identity_callback_deadline"], "resilience: OIDC timeout hierarchy invalid")
    require(p["delivery_connect"] + p["delivery_read"] <= p["delivery_attempt"] < p["outbox_lease"] * 1000, "resilience: delivery attempt exceeds lease budget")
    require(p["http_drain"] < p["supervisor_termination_grace"], "resilience: shutdown cleanup has no grace")
    require(p["session_idle_bound"] <= p["session_maximum_lifetime"], "resilience: idle bound exceeds session lifetime")
    require(p["sensitive_authentication_age"] <= p["session_maximum_lifetime"], "resilience: fresh authentication bound exceeds session lifetime")
    require(p["outbox_attempts_per_generation"] <= 8, "resilience: outbox generation attempts exceed schema cap")


def _endpoint_checks(capacity: dict, resilience: dict, p: dict, gates: set, require: Require) -> None:
    require(p["default_page"] <= p["maximum_page"] <= 100, "capacity: pagination exceeds canonical bounds")
    require(p["grant_additions"] + p["grant_removals"] <= p["changed_grant_response"] <= 200, "capacity: grant delta response exceeds canonical bounds")
    budgets = capacity.get("endpoint_budgets", [])
    require(len(budgets) == 10, "capacity: all ten endpoint classes require budgets")
    seen = set()
    for item in budgets:
        name = item.get("class")
        require(bool(name) and name not in seen, "capacity: duplicate or missing endpoint class")
        seen.add(name)
        deadline = resilience["identity_callback_deadline"] if name == "identity_callback" else resilience["http_deadline"]
        latency = item.get("p95_milliseconds")
        require(_numeric(latency) and 0 < latency < deadline, f"capacity.{name}: invalid latency budget")
        count = item.get("maximum_application_sql_statements")
        require(type(count) is int and 1 <= count <= 16, f"capacity.{name}: invalid SQL statement budget")
        require(bool(item.get("owner")) and item.get("evidence_gate") in gates, f"capacity.{name}: owner or gate missing")


def _slo_checks(p: dict, document: dict, require: Require) -> None:
    target = p["availability_target"]
    window = p["availability_window"]
    require(0 < target < 1, "slo: availability target must leave a finite error budget")
    require(window > 0, "slo: availability window must be positive")
    if window <= 0:
        return
    _equals(document.get("error_budget", {}).get("uniform_traffic_time_equivalent_minutes"), window * 1440 * (1 - target), "slo.time_equivalent", require)
    require(document.get("contractual_sla") is None, "slo: proposed objectives cannot invent a contractual SLA")
    alerts = document.get("burn_alerts", [])
    require(len(alerts) == 3, "slo: fast slow and persistent burn alerts required")
    for alert in alerts:
        long_window = alert.get("long_window_seconds")
        short_window = alert.get("short_window_seconds")
        burn = alert.get("burn_rate")
        valid = all(_numeric(value) for value in (long_window, short_window, burn))
        require(valid, "slo: finite burn parameters required")
        if valid:
            require(0 < short_window < long_window and burn > 0, "slo: invalid burn windows")
            _equals(alert.get("budget_fraction_in_long_window"), burn * long_window / (window * 86400), "slo.burn_fraction", require)
        require(alert.get("both_windows_required") is True and bool(alert.get("owner")), "slo: burn alert must check both windows and name owner")


def _safety_checks(documents: dict, require: Require) -> None:
    auth = documents["resilience"].get("authorization_resilience", {})
    require(auth.get("data_source") == "primary", "resilience: authorization must read primary")
    require(auth.get("successful_decision_cache") is False and auth.get("replica_permission_read") is False, "resilience: stale permission fallback prohibited")
    recovery = documents["resilience"].get("recovery_protocol", {})
    require(recovery.get("legacy_authority_rollback") is False, "resilience: legacy authority rollback prohibited")
    require(recovery.get("externally_durable_prepared_intent_before_access_transaction") is True, "resilience: external prepared intent required")
    require(recovery.get("distributed_atomicity_claim") is False, "resilience: distributed atomicity claim prohibited")
    outbox = documents["resilience"].get("outbox_protocol", {})
    require(outbox.get("delivery_semantics") == "at_least_once" and outbox.get("exactly_once_claim") is False, "resilience: invalid delivery guarantee")
    require(documents["capacity"].get("cache_and_replica_policy", {}).get("authorization_cache") is False, "capacity: authorization cache prohibited")
    require(documents["capacity"].get("canary", {}).get("random_per_request_split") is False, "capacity: organization authority cannot split per request")


def check(root: Path, require: Require) -> dict:
    """Report each contract violation through the caller's require callback."""
    execution = _read(root, "specs/execution.json", require)
    gates = {item.get("id") for item in execution.get("runtime_gates", [])}
    documents = {}
    values = {}
    for kind in CONTRACTS:
        document = _read(root, f"specs/contracts/{kind}.json", require)
        documents[kind] = document
        _metadata(root, document, kind, gates, require)
        values[kind] = _values(document, kind, gates, require)
        _unit_checks(document, kind, require)
    if any(value is None for value in values.values()):
        return {"contracts": 3, "parameters": 0}
    _pool_checks(values["capacity"], documents["capacity"], require)
    _concurrency_checks(values["capacity"], documents["capacity"], require)
    _timeout_checks(values["resilience"], require)
    _endpoint_checks(documents["capacity"], values["resilience"], values["capacity"], gates, require)
    _slo_checks(values["slo"], documents["slo"], require)
    _safety_checks(documents, require)
    return {"contracts": len(documents), "parameters": sum(len(items) for items in values.values())}
