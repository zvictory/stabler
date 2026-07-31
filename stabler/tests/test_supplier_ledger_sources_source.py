"""Structural guards for the Vendor Center ledger's source-document column.

The supplier ledger is one running debit/credit story, but the GL only knows
accounting vouchers. These guards pin the rule the owner asked for: the line
is named by the document the business recognises (the Commercial Invoice),
clicking it opens that document's OWN form, and resolving it never costs a
query per row.
"""

from __future__ import annotations

import os
import re
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, ".."))
API = os.path.join(_ROOT, "api", "purchasing.py")
VUE = os.path.join(_ROOT, "public", "js", "pages", "purchasing", "Suppliers.vue")
ROUTER = os.path.join(_ROOT, "public", "js", "router.js")


def read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def body(src, name):
    m = re.search(rf"^def {name}\(", src, re.M)
    assert m, f"{name} not found"
    tail = src[m.start():]
    nxt = re.search(r"\n(?:@frappe\.whitelist\(\)|def |# ---)", tail[1:])
    return tail[: nxt.start() + 1] if nxt else tail


class ResolverTest(unittest.TestCase):
    def setUp(self):
        self.src = read(API)
        self.body = body(self.src, "_attach_ledger_sources")

    def test_wired_into_the_ledger(self):
        self.assertIn("_attach_ledger_sources(company, window)", body(self.src, "supplier_ledger"))

    def test_read_only(self):
        for token in (".save(", ".insert(", "db_set(", "db.set_value(", "db.commit("):
            with self.subTest(token=token):
                self.assertNotIn(token, self.body)

    def test_batched_never_per_row(self):
        # A 1000-line ledger must not fire 1000 lookups: one get_all per
        # doctype, each inside a guard, never in the row loop.
        self.assertEqual(self.body.count("frappe.get_all("), 3)
        self.assertEqual(self.body.count("frappe.db.get_value("), 0)
        loop = self.body[self.body.index("for r in rows:"):]
        self.assertNotIn("frappe.get_all(", loop)
        self.assertNotIn("frappe.db.", loop)

    def test_the_ci_map_is_built_only_when_there_are_invoices_to_name(self):
        # That fetch reads EVERY Commercial Invoice in the company -- on msa
        # that is the biggest table in the module. A window filtered to Payment
        # Entry has no Purchase Invoice to name, so the map buys nothing there;
        # unguarded, opening the payments tab paid for it anyway.
        guard = self.body.index("if pinv_names:")
        self.assertGreater(
            self.body.index('"Commercial Invoice",'), guard,
            "the company-wide CI fetch runs before the pinv_names guard",
        )
        self.assertIn("if imports_on and pi_rows:", self.body)

    def test_the_line_is_named_by_the_ci_number_not_our_docname(self):
        # `CI-2026-00042` is our id; the buyer's paperwork says `HMA-1187`.
        # Falling back to the docname is fine -- silently printing it when the
        # number exists is what the owner asked us to stop doing.
        self.assertIn('r["source_label"] = ci_label_of.get(vno) or ci', self.body)

    def test_ci_link_is_imports_gated_and_column_guarded(self):
        # The CI route is module-guarded in the router; emitting the link on a
        # tenant without imports would dead-end. Pre-imports sites lack the
        # column entirely.
        self.assertIn('has_column("Purchase Invoice", "custom_commercial_invoice")', self.body)
        self.assertIn('module_map_for(company).get("imports")', self.body)

    def test_every_row_carries_the_contract(self):
        for key in ("source_doctype", "source_name", "source_label", "source_route",
                    "voucher_route", "channel"):
            with self.subTest(key=key):
                self.assertIn(f'r["{key}"]', self.body)

    def test_routes_are_spa_paths_not_desk(self):
        self.assertNotIn("/app", self.body)
        for path in ("/imports/commercial-invoices/", "/purchasing/invoices/", "/money/payments/"):
            with self.subTest(path=path):
                self.assertIn(path, self.body)


class LedgerCellTest(unittest.TestCase):
    def setUp(self):
        self.vue = read(VUE)

    def test_row_links_to_the_source_document_form(self):
        self.assertIn(':to="e.source_route"', self.vue)
        self.assertIn("e.source_label", self.vue)

    def test_accounting_voucher_stays_reachable(self):
        # The PInv id is plumbing, but it must never disappear — auditors ask
        # for it. It stays as the muted secondary that opens the drawer.
        self.assertIn('@click="openVoucher(e)"', self.vue)
        self.assertIn("e.source_name !== e.voucher_no", self.vue)

    def test_channel_chip_is_shown(self):
        self.assertIn("e.channel", self.vue)

    def test_no_desk_links(self):
        self.assertNotIn('"/app', self.vue)
        self.assertNotIn("'/app", self.vue)


class RouteExistsTest(unittest.TestCase):
    def test_targets_of_every_emitted_route_are_registered(self):
        router = read(ROUTER)
        for name in ("imports-commercial-invoice", "purchasing-invoice", "money-payment"):
            with self.subTest(name=name):
                self.assertRegex(router, rf'name: "{name}"')


if __name__ == "__main__":
    unittest.main()
