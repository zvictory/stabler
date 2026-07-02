"""Static guard: every whitelisted endpoint that takes a `company` argument must
enforce tenant isolation.

Background: `@frappe.whitelist()` gates *method* access only — it does NOT scope a
call to the caller's permitted companies. An endpoint that accepts `company` and
uses it in a query/write without `_assert_company_scope(company)` (or an equivalent
guard) lets any authenticated user read or mutate another company's data by passing
a foreign `company` argument. See docs/SECURITY-AUDIT-2026-07-02.md.

This test parses the API source with `ast` (no Frappe runtime needed) and fails if a
whitelisted, `company`-taking function contains none of the accepted scope guards.
It is the automated form of the review rule in CLAUDE.md.

If you add an endpoint that legitimately must NOT scope by company (e.g. a global
reference-data reader), add it to `_ALLOWLIST` below WITH a one-line justification —
do not weaken the check.
"""

from __future__ import annotations

import ast
import glob
import os
import unittest

# Tokens that count as "this function enforces tenant isolation". Any one is enough:
#   _assert_company_scope   — the canonical guard (stabler.api.approvals)
#   _require_service        — wraps _assert_company_scope for the Service module
#   _user_allowed_companies — manual scoping against the allowed-companies list
#   _company_filter         — SFA's per-company filter helper
#   _require_admin          — admin-only endpoint; company boundary is moot
_SCOPE_TOKENS = (
    "_assert_company_scope",
    "_require_service",
    "_user_allowed_companies",
    "_company_filter",
    "_require_admin",
)

# doctype::function -> reason. Keep this empty unless there is a real exemption.
_ALLOWLIST: dict[str, str] = {}

_APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../stabler


def _is_whitelist(dec: ast.expr) -> bool:
    d = dec.func if isinstance(dec, ast.Call) else dec
    if isinstance(d, ast.Attribute):
        return d.attr == "whitelist"
    if isinstance(d, ast.Name):
        return d.id == "whitelist"
    return False


def _iter_source_files():
    for pat in ("api/*.py", "integrations/**/*.py"):
        yield from glob.glob(os.path.join(_APP_ROOT, pat), recursive=True)


def _find_violations() -> list[str]:
    violations: list[str] = []
    for path in sorted(_iter_source_files()):
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        rel = os.path.relpath(path, _APP_ROOT)
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if not any(_is_whitelist(d) for d in node.decorator_list):
                continue
            argnames = [a.arg for a in node.args.args] + [a.arg for a in node.args.kwonlyargs]
            if "company" not in argnames:
                continue
            key = f"{rel}::{node.name}"
            if key in _ALLOWLIST:
                continue
            seg = ast.get_source_segment(src, node) or ""
            if not any(tok in seg for tok in _SCOPE_TOKENS):
                violations.append(key)
    return violations


class TestCompanyScopeGuard(unittest.TestCase):
    def test_all_company_endpoints_are_scoped(self):
        violations = _find_violations()
        self.assertEqual(
            violations,
            [],
            "Whitelisted endpoints take a `company` arg but never call "
            "_assert_company_scope (or an accepted guard). Add the guard, or "
            "allowlist with justification in this test:\n  - "
            + "\n  - ".join(violations),
        )


if __name__ == "__main__":
    unittest.main()
