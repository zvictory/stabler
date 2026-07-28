"""Structural guards for the sandbox-ported PI shipment UX.

The sandbox (~/msa-sandbox) settled these rules against the real book; this
file pins the port: everything delegates to _imports_rules (one math in the
whole app), over-shipment stays its own figure, and column aliases match what
the pure module actually reads.
"""

from __future__ import annotations

import os
import re
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, ".."))
API = os.path.join(_ROOT, "api", "imports.py")
PAGES = os.path.join(_ROOT, "public", "js", "pages", "imports")


def read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def body(src, name):
    m = re.search(rf"^def {name}\(", src, re.M)
    assert m, f"{name} not found"
    tail = src[m.start():]
    nxt = re.search(r"\n(?:@frappe\.whitelist\(\)|def |# ---)", tail[1:])
    return tail[: nxt.start() + 1] if nxt else tail


class RollupTest(unittest.TestCase):
    def setUp(self):
        self.src = read(API)
        self.body = body(self.src, "_attach_proforma_match_rollups")

    def test_delegates_to_the_rules_module(self):
        for call in ("rules.contract_index(", "rules.shipped_index(", "rules.remaining_for("):
            with self.subTest(call=call):
                self.assertIn(call, self.body)

    def test_sql_aliases_match_what_the_rules_read(self):
        # _contract_pi reads pi_name/parent; _shipped_pi reads pi_name/
        # custom_proforma_invoice. Any other alias yields an empty match key
        # and every balance silently reads zero.
        self.assertIn("AS pi_name", self.body)
        self.assertNotIn("AS proforma_invoice", self.body)

    def test_over_shipment_is_its_own_figure(self):
        self.assertIn('r["over_boxes"]', self.body)
        self.assertNotIn("max(0", self.body)

    def test_wired_into_the_list(self):
        lst = body(self.src, "list_proformas")
        self.assertIn("_attach_proforma_match_rollups(rows)", lst)


class CompareEndpointTest(unittest.TestCase):
    def setUp(self):
        self.src = read(API)
        self.body = body(self.src, "compare_proformas")

    def test_whitelisted_gated_and_read_only(self):
        self.assertRegex(self.src, r"@frappe\.whitelist\(\)\ndef compare_proformas\(")
        self.assertIn("_assert_imports_access(company)", self.body)
        for token in (".save(", ".insert(", "db_set(", "db.set_value(", "db.commit("):
            with self.subTest(token=token):
                self.assertNotIn(token, self.body)

    def test_uses_the_same_contract_index(self):
        self.assertIn("rules.contract_index(", self.body)

    def test_requires_at_least_two_and_caps(self):
        self.assertIn("len(pis) < 2", self.body)
        self.assertIn("[:10]", self.body)


class PiScopedInfoTest(unittest.TestCase):
    def test_single_pi_call_carries_the_sub_cut_rows(self):
        # The PI form's sub-cut breakdown is the info rows; a whole-book call
        # still filters them (they would drown the payload).
        src = read(API)
        b = body(src, "get_ci_pi_discrepancies")
        self.assertIn('not (pi and level == "info")', b)


class PagesTest(unittest.TestCase):
    def test_list_shows_the_sandbox_columns(self):
        lst = read(os.path.join(PAGES, "ProformaInvoices.vue"))
        for token in ("shipped_pct", "remaining_boxes", "over_boxes"):
            with self.subTest(token=token):
                self.assertIn(token, lst)
        # Over-shipment is a red badge, not folded into the remainder.
        self.assertIn("bg-red-lt", lst)

    def test_list_selection_feeds_compare(self):
        lst = read(os.path.join(PAGES, "ProformaInvoices.vue"))
        self.assertIn("selectedPis", lst)
        self.assertIn('"/imports/proformas/compare"', lst)

    def test_compare_page_exists_and_flags_differences(self):
        cmp_src = read(os.path.join(PAGES, "ProformaCompare.vue"))
        self.assertIn('call("stabler.api.imports.compare_proformas"', cmp_src)
        for flag in ("on_all", "boxes_differ", "agreed_differ"):
            with self.subTest(flag=flag):
                self.assertIn(flag, cmp_src)
        self.assertNotIn('"/app', cmp_src)

    def test_form_match_panel_uses_the_shared_endpoint(self):
        form = read(os.path.join(PAGES, "ProformaForm.vue"))
        self.assertIn('call("stabler.api.imports.get_ci_pi_discrepancies"', form)
        self.assertIn("subCuts", form)

    def test_routes_registered(self):
        router = read(os.path.join(_ROOT, "public", "js", "router.js"))
        self.assertIn('"imports-proformas-compare"', router)


if __name__ == "__main__":
    unittest.main()
