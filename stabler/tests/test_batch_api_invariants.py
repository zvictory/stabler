"""Source-level guards for the batch/expiry endpoints.

Frappe-free, like test_imports_api_invariants: the source is read as text and
the properties that must not regress are asserted structurally. These endpoints
read stock across a whole company, so tenant isolation matters most.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_batch_api_invariants -v
"""

from __future__ import annotations

import os
import re
import unittest

from stabler.api import _fefo  # pure module, safe to import

_HERE = os.path.dirname(os.path.abspath(__file__))
_API = os.path.normpath(os.path.join(_HERE, "..", "api"))

BATCH_ENDPOINTS = ["batch_availability", "suggest_fefo", "expiring_batches"]


def _read(name: str) -> str:
    with open(os.path.join(_API, name), encoding="utf-8") as f:
        return f.read()


def _func_body(src: str, name: str) -> str:
    m = re.search(rf"^def {name}\(", src, re.M)
    assert m, f"function {name} not found"
    tail = src[m.start():]
    nxt = re.search(r"\n(?:@frappe\.whitelist\(\)|def )", tail[1:])
    return tail[: nxt.start() + 1] if nxt else tail


class TenantIsolationTest(unittest.TestCase):
    def setUp(self):
        self.src = _read("inventory.py")

    def test_every_batch_endpoint_scopes_the_company(self):
        for name in BATCH_ENDPOINTS:
            with self.subTest(endpoint=name):
                body = _func_body(self.src, name)
                self.assertIn("_require_company(company)", body)
                self.assertIn("_assert_company_scope(company)", body)

    def test_every_batch_endpoint_is_whitelisted(self):
        for name in BATCH_ENDPOINTS:
            with self.subTest(endpoint=name):
                self.assertRegex(
                    self.src,
                    rf"@frappe\.whitelist\(\)\ndef {name}\(",
                    f"{name} must be decorated with @frappe.whitelist()",
                )


class ReadOnlyTest(unittest.TestCase):
    """Visibility endpoints. Writing a batch onto a document is a separate,
    riskier change and must not sneak in here."""

    def test_batch_endpoints_never_write(self):
        src = _read("inventory.py")
        forbidden = ("db_set(", ".insert(", ".save(", ".submit(", "db.set_value(", "db.commit(")
        for name in BATCH_ENDPOINTS:
            body = _func_body(src, name)
            for token in forbidden:
                with self.subTest(endpoint=name, token=token):
                    self.assertNotIn(token, body)


class BalanceSourceTest(unittest.TestCase):
    def setUp(self):
        self.body = _func_body(_read("inventory.py"), "_batch_rows")

    def test_quantities_come_from_the_ledger_not_batch_qty(self):
        # tabBatch.batch_qty is a company-wide figure — using it would report
        # stock sitting in another warehouse as available here.
        self.assertIn("tabStock Ledger Entry", self.body)
        self.assertIn("SUM(sle.actual_qty)", self.body)
        # Match the column reference, not the word — the docstring explains why
        # batch_qty is wrong, and a prose mention must not fail the guard.
        self.assertNotIn("b.batch_qty", self.body)

    def test_cancelled_ledger_entries_are_excluded(self):
        self.assertIn("is_cancelled = 0", self.body)

    def test_zero_and_negative_balances_are_filtered_out(self):
        self.assertIn("HAVING SUM(sle.actual_qty) > 0", self.body)

    def test_no_caller_value_reaches_the_sql_string(self):
        # The only interpolation is the joined condition list, built from
        # literals; every caller value goes through %(name)s parameters.
        interpolations = set(re.findall(r"\{(\w+)\}", self.body))
        self.assertTrue(
            interpolations <= {"conds"},
            f"unexpected f-string interpolation into SQL: {interpolations}",
        )


class FefoPolicyTest(unittest.TestCase):
    def test_expired_stock_is_not_allocated_by_default(self):
        res = _fefo.allocate_fefo(10, [{"batch_no": "X", "qty": 100, "days_left": -1}])
        self.assertEqual(res["lines"], [])
        self.assertEqual(res["shortfall"], 10)
        self.assertEqual(res["skipped_expired"], ["X"])

    def test_undated_batch_is_not_ranked_as_freshest(self):
        rows = [
            {"batch_no": "NO_DATE", "qty": 100, "expiry_date": None},
            {"batch_no": "DATED", "qty": 100, "expiry_date": "2030-01-01"},
        ]
        self.assertEqual([r["batch_no"] for r in _fefo.sort_fefo(rows)], ["DATED", "NO_DATE"])


if __name__ == "__main__":
    unittest.main()
