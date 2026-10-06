#!/usr/bin/env python3
"""Validate planning package consistency without claiming application behavior."""

import argparse
import re
import subprocess
import sys
from pathlib import Path

from spec_io import load_json

ROOT = Path(__file__).resolve().parents[1]
FAILURES = []


def public_files():
    """Inspect publishable files, including forced tracked private files."""
    result = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=ROOT,
                            capture_output=True, check=False)
    if result.returncode:
        raise ValueError("Cannot determine the public repository inventory")
    return sorted({ROOT / name for name in result.stdout.decode().split("\0") if name})


def require(condition, message):
    if not condition:
        FAILURES.append(message)


def read_json(relative):
    try:
        return load_json(ROOT / relative)
    except (OSError, ValueError) as error:
        FAILURES.append(f"{relative}: {error}")
        return {}


def order_nodes(nodes, label):
    by_id = {item.get("id"): item for item in nodes}
    require(len(by_id) == len(nodes), f"{label}: duplicate IDs")
    for item in nodes:
        for dependency in item.get("depends_on", []):
            require(dependency in by_id, f"{item.get('id')}: unknown dependency {dependency}")
    remaining = dict(by_id)
    result = []
    while remaining:
        ready = sorted(
            key for key, item in remaining.items()
            if all(dependency in result for dependency in item.get("depends_on", []))
        )
        if not ready:
            FAILURES.append(f"{label}: cycle or unresolved dependency in {sorted(remaining)}")
            break
        for key in ready:
            result.append(key)
            del remaining[key]
    return result


def check_documents():
    count = 0
    for path in public_files():
        if path.suffix != ".md":
            continue
        count += 1
        contents = path.read_text(encoding="utf-8")
        require(contents.endswith("\n"), f"{path.relative_to(ROOT)}: missing final newline")
        require(contents.count("```") % 2 == 0, f"{path.relative_to(ROOT)}: unclosed code fence")
        prose = re.sub(r"```.*?```", "", contents, flags=re.DOTALL)
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", prose):
            target = target.strip().strip("<>")
            if re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith("#"):
                continue
            relative = target.split("#", 1)[0]
            resolved = (path.parent / relative).resolve()
            require(resolved.is_relative_to(ROOT), f"{path.relative_to(ROOT)}: link escapes repository {target}")
            require(resolved.exists(), f"{path.relative_to(ROOT)}: broken link {target}")
    return count


def resolve_pointer(document, pointer):
    if not pointer.startswith("#/"):
        raise ValueError("only local contract references are supported")
    value = document
    for key in pointer[2:].split("/"):
        value = value[key.replace("~1", "/").replace("~0", "~")]
    return value


def check_contract_node(api, value):
    if "$ref" in value:
        try:
            resolve_pointer(api, value["$ref"])
        except (KeyError, TypeError, ValueError) as error:
            FAILURES.append(f"OpenAPI unresolved reference {value['$ref']}: {error}")
    if "required" in value and "properties" in value:
        require(set(value["required"]) <= set(value["properties"]), "OpenAPI: undeclared required property")
    if "minimum" in value and "maximum" in value:
        require(value["minimum"] <= value["maximum"], "OpenAPI: contradictory numeric bounds")


def walk_contract(api, value):
    if isinstance(value, dict):
        check_contract_node(api, value)
        for child in value.values():
            walk_contract(api, child)
    elif isinstance(value, list):
        for child in value:
            walk_contract(api, child)


def operation_parameters(api, path_item, operation):
    parameters = []
    for parameter in path_item.get("parameters", []) + operation.get("parameters", []):
        try:
            parameters.append(resolve_pointer(api, parameter["$ref"]) if "$ref" in parameter else parameter)
        except (KeyError, TypeError, ValueError):
            continue
    return parameters


def check_operation(api, path, path_item, method, operation, seen):
    name = operation.get("operationId")
    require(name and name not in seen, f"OpenAPI: duplicate/missing operation ID at {method} {path}")
    seen.add(name)
    parameters = operation_parameters(api, path_item, operation)
    declared = {p.get("name") for p in parameters if p.get("in") == "path" and p.get("required") is True}
    required = set(re.findall(r"\{([^}]+)\}", path))
    require(declared == required, f"OpenAPI path parameters differ at {method} {path}: {declared} != {required}")
    require(bool(operation.get("responses")), f"OpenAPI responses missing at {method} {path}")
    public = path.startswith("/health/") or path in {"/auth/login", "/auth/callback"}
    require("security" in operation and (public or bool(operation["security"])), f"OpenAPI authority missing at {method} {path}")
    if method == "patch":
        names = {p.get("name") for p in parameters}
        require({"If-Match", "Idempotency-Key"} <= names, f"OpenAPI mutation concurrency headers missing at {path}")


def check_openapi():
    api = read_json("specs/contracts/openapi.json")
    require(api.get("openapi") == "3.1.0", "OpenAPI: contract version must be 3.1.0")
    walk_contract(api, api)
    seen = set()
    for path, path_item in api.get("paths", {}).items():
        for method, operation in path_item.items():
            if method in {"get", "post", "put", "patch", "delete"}:
                check_operation(api, path, path_item, method, operation, seen)
    return len(seen)


def check_hygiene():
    for path in public_files():
        if not path.is_file() or ".git" in path.parts:
            continue
        relative = path.relative_to(ROOT)
        private = path.suffix.lower() in {".pdf", ".docx"} or path.name == ".env"
        private = private or any(part == "private" for part in relative.parts)
        require(not private, f"Private input must be outside the public package: {relative}")


def check_features(execution, requirements):
    features = []
    scenarios = set()
    covered = set()
    for reference in execution.get("features", []):
        feature = read_json(reference.get("path", ""))
        require(feature.get("id") == reference.get("id"), f"Feature ID mismatch: {reference}")
        features.append(feature)
        declared = set(feature.get("requirements", []))
        require(declared <= requirements and bool(declared), f"{feature.get('id')}: invalid requirements")
        covered.update(declared)
        for field in ["title", "scope", "excluded", "invariants", "acceptance", "documents"]:
            require(bool(feature.get(field)), f"{feature.get('id')}: missing {field}")
        for document in feature.get("documents", []):
            require((ROOT / document).is_file(), f"{feature.get('id')}: missing document {document}")
        for scenario in feature.get("acceptance", []):
            sid = scenario.get("id")
            require(sid and sid not in scenarios, f"Duplicate/missing scenario ID: {sid}")
            scenarios.add(sid)
            for field in ["given", "when", "then", "evidence"]:
                require(bool(scenario.get(field)), f"{sid}: missing {field}")
    require(covered == requirements, f"Uncovered requirements: {sorted(requirements - covered)}")
    order_nodes(features, "Feature graph")
    return features, scenarios


def check_tasks(execution, features, scenarios):
    feature_ids = {item.get("id") for item in features}
    tasks = execution.get("tasks", [])
    task_order = order_nodes(tasks, "Task graph")
    task_coverage = set()
    scenario_coverage = set()
    for task in tasks:
        assigned = set(task.get("features", []))
        require(assigned <= feature_ids and bool(assigned), f"{task.get('id')}: invalid features")
        task_coverage.update(assigned)
        for field in ["owner", "status", "input_gates", "planned_outputs", "required_evidence"]:
            require(bool(task.get(field)), f"{task.get('id')}: missing {field}")
        for evidence in task.get("required_evidence", []):
            if re.fullmatch(r"F\d{2}-AC-\d{2}", evidence):
                require(evidence in scenarios, f"{task.get('id')}: unknown scenario {evidence}")
                scenario_coverage.add(evidence)
    require(task_coverage == feature_ids, f"Features without task: {sorted(feature_ids - task_coverage)}")
    require(scenario_coverage == scenarios, f"Scenarios without task evidence: {sorted(scenarios - scenario_coverage)}")
    return tasks, task_order


def check_contracts_and_gates(execution):
    for contract in execution.get("contracts", []):
        require((ROOT / contract).is_file(), f"Missing contract: {contract}")
    gates = execution.get("runtime_gates", [])
    require(len({g.get("id") for g in gates}) == len(gates) and bool(gates), "Runtime gate IDs must be unique and nonempty")
    for gate in gates:
        require(bool(gate.get("purpose")) and bool(gate.get("planned_entrypoint")), f"Incomplete runtime gate {gate}")
    order_nodes(gates, "Runtime gate graph")


def check_policy_examples():
    policy = read_json("specs/contracts/policy-cases.json")
    cases = policy.get("cases", [])
    require(len(cases) >= 10 and len({c.get("id") for c in cases}) == len(cases), "Policy examples missing or duplicate")
    for case in cases:
        require(isinstance(case.get("expected", {}).get("allowed"), bool), f"Invalid policy expectation {case.get('id')}")
        require(bool(case.get("input")) and bool(case.get("expected", {}).get("reason")), f"Incomplete policy example {case.get('id')}")


def check_clause(clause, execution, feature_ids):
    for field in ["outcome", "documents", "requirements", "features", "design_status", "runtime_status", "review_method"]:
        require(bool(clause.get(field)), f"{clause.get('id')}: missing coverage {field}")
    require(set(clause.get("requirements", [])) <= set(execution["requirements"]), f"{clause.get('id')}: unknown requirement")
    require(set(clause.get("features", [])) <= feature_ids, f"{clause.get('id')}: unknown feature")
    for document in clause.get("documents", []):
        require((ROOT / document).is_file(), f"{clause.get('id')}: missing coverage document {document}")


def check_coverage(execution, feature_ids):
    coverage = read_json("specs/coverage.json")
    clauses = coverage.get("clauses", [])
    expected = {f"A{n:02}" for n in range(1, 4)} | {f"B{n:02}" for n in range(1, 6)}
    expected |= {f"C{n:02}" for n in range(1, 8)} | {f"D{n:02}" for n in range(1, 5)}
    expected |= {f"E{n:02}" for n in range(1, 5)} | {f"M{n:02}" for n in range(1, 5)}
    require({clause.get("id") for clause in clauses} == expected and len(clauses) == 27, "Written-delivery clause coverage must contain all 27 atomic clauses")
    for clause in clauses:
        check_clause(clause, execution, feature_ids)
    return len(clauses)


def check_standard_group(group, gates, seen):
    require((ROOT / group.get("canonical_document", "")).is_file(), f"{group.get('id')}: missing standards document")
    require(bool(group.get("concepts")), f"{group.get('id')}: no concepts")
    for concept in group.get("concepts", []):
        cid = concept.get("id")
        require(bool(cid) and cid not in seen, f"Missing or duplicate standard concept: {cid}")
        seen.add(cid)
        for field in ["name", "disposition", "rationale", "component", "owner", "gate", "evidence", "revisit"]:
            require(bool(concept.get(field)), f"{cid}: missing standard {field}")
        require(concept.get("disposition") in {"adopted", "context_dependent", "deferred", "not_applicable"}, f"{cid}: invalid disposition")
        require(concept.get("gate") in gates, f"{cid}: unknown gate {concept.get('gate')}")


def check_standards(execution):
    standards = read_json("specs/standards.json")
    groups = standards.get("groups", [])
    require({group.get("id") for group in groups} == {f"STD-{n:02}" for n in range(1,16)} and len(groups) == 15, "Standards must cover 15 groups")
    gates = {gate["id"] for gate in execution["runtime_gates"]}
    seen = set()
    for group in groups:
        check_standard_group(group, gates, seen)
    require(len(seen) >= 230, "Engineering concept coverage is incomplete")
    return len(seen)


def check_implementation_state():
    evidence = read_json("specs/implementation-evidence.json")
    required = {"schema_version", "revision", "gates", "scenarios", "tasks", "live_approvals"}
    require(set(evidence) == required and evidence.get("schema_version") == 1, "Implementation evidence shape invalid")
    if evidence.get("revision") is None:
        require(all(evidence.get(field) == [] for field in required - {"schema_version", "revision"}), "Unimplemented package cannot claim runtime completion")


def ancestors(tid, tasks):
    found = set()
    pending = list(tasks[tid].get("depends_on", []))
    while pending:
        current = pending.pop()
        if current in found or current not in tasks:
            continue
        found.add(current)
        pending.extend(tasks[current].get("depends_on", []))
    return found


def check_evidence_order(features, tasks):
    by_id = {task["id"]: task for task in tasks}
    scenarios = {item["id"]: item for feature in features for item in feature["acceptance"]}
    for sid, scenario in scenarios.items():
        first = scenario.get("first_evidence_task")
        require(first in by_id, f"{sid}: missing first evidence task")
        require(sid in by_id.get(first, {}).get("required_evidence", []), f"{sid}: first evidence task does not own the scenario")
    for task in tasks:
        allowed = ancestors(task["id"], by_id) | {task["id"]}
        for sid in set(task["required_evidence"]) & set(scenarios):
            require(scenarios[sid].get("first_evidence_task") in allowed, f"{task['id']}: premature evidence assignment for {sid}")


def report(args, requirements, features, scenarios, tasks, order, counts):
    if FAILURES:
        for failure in FAILURES:
            print(f"FAIL: {failure}", file=sys.stderr)
        print(f"Specification validation failed: {len(FAILURES)} violation(s).", file=sys.stderr)
        return 1
    print(f"PASS: {len(requirements)} requirements, {len(features)} features, {len(scenarios)} scenarios, {len(tasks)} tasks, {counts['api']} API operations, {counts['docs']} documents, {counts['clauses']} clauses, {counts['standards']} standard concepts.")
    print("Scope: package consistency only. Application and migration behavior require their separate runtime gates.")
    if args.plan:
        by_id = {task["id"]: task for task in tasks}
        for tid in order:
            print(f"{tid}: {by_id[tid]['title']} [{by_id[tid]['owner']}]")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", action="store_true", help="print implementation order after validation")
    args = parser.parse_args()
    execution = read_json("specs/execution.json")
    requirements = set(execution.get("requirements", []))
    require(requirements == {f"REQ-{number:02}" for number in range(1, 21)}, "Requirements must cover REQ-01 through REQ-20")
    require(execution.get("stage") in {"specifications", "local_product"}, "Explicit package stage required")
    features, scenarios = check_features(execution, requirements)
    tasks, order = check_tasks(execution, features, scenarios)
    check_evidence_order(features, tasks)
    check_contracts_and_gates(execution)
    check_policy_examples()
    check_implementation_state()
    from budget_checks import check as check_budgets
    check_budgets(ROOT, require)
    counts = {"clauses":check_coverage(execution, {feature["id"] for feature in features}), "standards":check_standards(execution), "docs":check_documents(), "api":check_openapi()}
    check_hygiene()
    return report(args, requirements, features, scenarios, tasks, order, counts)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyError, TypeError, ValueError) as error:
        print(f"Specification validation failed: malformed input: {error}", file=sys.stderr)
        sys.exit(1)
