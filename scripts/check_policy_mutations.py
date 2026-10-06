#!/usr/bin/env python3
"""Measure whether the independent decision matrix detects removed policy guards."""

import ast
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
GUARDS = (
    "authenticated", "organization_matches", "project_matches", "organization_active",
    "membership_active", "project_active", "entitlement_active", "resource_published", "grant_active",
)


class MutateGuard(ast.NodeTransformer):
    def __init__(self, guard: str):
        self.guard = guard

    def visit_Attribute(self, node):
        if isinstance(node.value, ast.Name) and node.value.id == "context" and node.attr == self.guard:
            return ast.copy_location(ast.Constant(value=True), node)
        return self.generic_visit(node)

    def visit_Compare(self, node):
        if (
            self.guard == "expiry_boundary" and isinstance(node.left, ast.Attribute)
            and node.left.attr == "membership_expires_at" and isinstance(node.ops[0], ast.LtE)
        ):
            node.ops[0] = ast.Lt()
        return self.generic_visit(node)


def compile_variant(source: str, guard: str | None) -> ModuleType:
    tree = ast.parse(source)
    if guard:
        tree = MutateGuard(guard).visit(tree)
    module = ModuleType("_scopegate_policy_probe")
    sys.modules[module.__name__] = module
    try:
        # Compile only the repository-owned policy AST in this isolated check process.
        exec(compile(ast.fix_missing_locations(tree), "<policy-mutation-probe>", "exec"), module.__dict__)  # noqa: S102
    finally:
        del sys.modules[module.__name__]
    return module


def differences(module: ModuleType, cases: list[dict]) -> list[str]:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    changed = []
    for case in cases:
        data = case["input"]
        context = module.AccessContext(
            organization_active=data["organization_active"], membership_active=data["membership_active"],
            membership_expires_at=None if data["membership_unexpired"] else now,
            project_active=data["project_active"], entitlement_active=data["entitlement_active"],
            resource_published=data["resource_published"], grant_active=data["explicit_grant"], now=now,
            authenticated=data["authenticated"], organization_matches=data["organization_matches"],
            project_matches=data["project_matches"],
        )
        result = module.evaluate(context)
        if {"allowed": result.allowed, "reason": result.reason} != case["expected"]:
            changed.append(case["id"])
    return changed


def main() -> int:
    source = (ROOT / "backend/src/scopegate/domain/policy.py").read_text()
    cases = json.loads((ROOT / "specs/contracts/policy-cases.json").read_text())["cases"]
    baseline = differences(compile_variant(source, None), cases)
    mutations = [
        {"guard": guard, "detected_by": differences(compile_variant(source, guard), cases)}
        for guard in (*GUARDS, "expiry_boundary")
    ]
    survivors = [item["guard"] for item in mutations if not item["detected_by"]]
    report = {
        "scope": "Ten isolated authorization guard and expiry-boundary mutations against fifteen canonical cases",
        "full_code_mutation_coverage_claimed": False,
        "baseline_case_count": len(cases), "baseline_failures": baseline,
        "mutations": mutations, "killed": len(mutations) - len(survivors), "survivors": survivors,
    }
    output = ROOT / "artifacts/unit/policy-mutations.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    passed = not baseline and not survivors
    print(f"Policy mutation probe: {report['killed']}/{len(mutations)} detected; baseline {len(cases)-len(baseline)}/{len(cases)}.")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
