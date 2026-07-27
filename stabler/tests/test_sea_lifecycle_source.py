"""Structural guards for the shared sea lifecycle endpoints.

Frappe-free. These protect the properties that make the sync safe to run
against 243 live invoices.
"""

from __future__ import annotations

import os
import re
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, ".."))
API = os.path.join(_ROOT, "api", "imports.py")
MATH = os.path.join(_ROOT, "stabler", "imports_module", "sea_lifecycle.py")


def read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def body(src, name):
    m = re.search(rf"^def {name}\(", src, re.M)
    assert m, f"{name} not found"
    tail = src[m.start():]
    nxt = re.search(r"\n(?:@frappe\.whitelist\(\)|def |# ---)", tail[1:])
    return tail[: nxt.start() + 1] if nxt else tail


class ReadEndpointTest(unittest.TestCase):
    def setUp(self):
        self.src = read(API)
        self.body = body(self.src, "ci_sea_lifecycle")

    def test_whitelisted_and_scoped(self):
        self.assertRegex(self.src, r"@frappe\.whitelist\(\)\ndef ci_sea_lifecycle\(")
        self.assertIn("_assert_imports_access(company)", self.body)
        self.assertIn('_assert_can_read("Commercial Invoice"', self.body)

    def test_read_endpoint_never_writes(self):
        for token in (".save(", ".insert(", "db_set(", "db.set_value(", "db.commit("):
            with self.subTest(token=token):
                self.assertNotIn(token, self.body)


class SyncEndpointTest(unittest.TestCase):
    def setUp(self):
        self.src = read(API)
        self.body = body(self.src, "sync_containers_to_ci")

    def test_whitelisted_and_scoped(self):
        self.assertRegex(self.src, r"@frappe\.whitelist\(\)\ndef sync_containers_to_ci\(")
        self.assertIn("_assert_imports_access(company)", self.body)

    def test_requires_write_permission_not_just_read(self):
        self.assertIn('_assert_can_write("Commercial Invoice"', self.body)

    def test_dry_run_is_the_default(self):
        self.assertIn("dry_run: int = 1", self.src)
        # Indentation is deliberately not pinned. What this guards is that a dry
        # run short-circuits before the write — not how imports.py happens to be
        # indented. Pinned to 12 spaces, it broke on the `ruff format` sweep,
        # which normalised that file's mixed indentation without touching a line
        # of logic: a green-to-red flip with no behaviour change behind it.
        self.assertRegex(self.body, r"if dry_run:\s*\n\s+continue")

    def test_only_lagging_containers_move(self):
        self.assertIn("sea_lifecycle.syncable(ci_status, c.status)", self.body)

    def test_walks_the_pipeline_rather_than_jumping(self):
        # The Import Container controller enforces one step at a time; setting
        # the final status directly would trip its own transition guard.
        self.assertIn("sea_lifecycle.path(c.status, ci_status)", self.body)
        self.assertIn("for step in steps:", self.body)

    def test_goes_through_the_controller_not_raw_sql(self):
        # doc.save() runs the transition rules; db.set_value would bypass them.
        self.assertIn('frappe.get_doc("Import Container", c.name)', self.body)
        self.assertIn("doc.save()", self.body)
        self.assertNotIn("db.set_value", self.body)
        self.assertNotIn("frappe.db.sql", self.body)

    def test_a_failure_rolls_back_and_is_reported(self):
        self.assertIn("frappe.db.rollback()", self.body)
        self.assertIn("failed.append(", self.body)

    def test_reports_what_it_refused_to_touch(self):
        self.assertIn("skipped.append(", self.body)


class PolicyTest(unittest.TestCase):
    def setUp(self):
        self.math = read(MATH)

    def test_ahead_containers_are_never_synced(self):
        m = re.search(r"def syncable\(.*?\n\n\n", self.math, re.S).group(0)
        self.assertIn('== "behind"', m)

    def test_cancelled_is_out_of_the_voyage(self):
        self.assertIn('TERMINAL = {"Cancelled"}', self.math)

    def test_sync_is_not_wired_to_a_hook(self):
        # An automatic sync would erase the drift before it could be measured.
        hooks = read(os.path.join(_ROOT, "hooks.py"))
        self.assertNotIn("sync_containers_to_ci", hooks)


if __name__ == "__main__":
    unittest.main()
