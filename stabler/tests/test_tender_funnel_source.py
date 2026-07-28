"""Structural guards for the tender_funnel endpoint + its SPA panel."""

from __future__ import annotations

import os
import re
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, ".."))
API = os.path.join(_ROOT, "api", "tender.py")
VUE = os.path.join(_ROOT, "public", "js", "pages", "tender", "TenderFunnel.vue")
BOARD = os.path.join(_ROOT, "public", "js", "pages", "tender", "DirectorBoard.vue")


def read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def body(src, name):
    m = re.search(rf"^def {name}\(", src, re.M)
    assert m, f"{name} not found"
    tail = src[m.start():]
    nxt = re.search(r"\n(?:@frappe\.whitelist\(\)|def |# ---)", tail[1:])
    return tail[: nxt.start() + 1] if nxt else tail


class EndpointTest(unittest.TestCase):
    def setUp(self):
        self.src = read(API)
        self.body = body(self.src, "tender_funnel")

    def test_whitelisted_and_gated(self):
        self.assertRegex(self.src, r"@frappe\.whitelist\(\)\ndef tender_funnel\(")
        self.assertIn("_require_tender(company)", self.body)

    def test_respects_document_permissions(self):
        self.assertIn('frappe.has_permission("CRM Deal", "read", doc=deal)', self.body)

    def test_read_only(self):
        for token in (".save(", ".insert(", "db_set(", "db.set_value(", "db.commit("):
            with self.subTest(token=token):
                self.assertNotIn(token, self.body)

    def test_classification_is_delegated_to_the_pure_module(self):
        # The precedence rule must live in _funnel.py where it is exhaustively
        # tested — not re-derived inline where it can drift.
        self.assertIn("_funnel.classify(", self.body)
        self.assertIn("_funnel.summarise(", self.body)
        self.assertIn("_funnel.summarise_so(", self.body)

    def test_quotation_counts_come_from_one_grouped_pass(self):
        self.assertIn("sq_counts", self.body)
        # No per-deal Supplier Quotation query inside the deal loop.
        loop = self.body[self.body.index("for deal in _tender_deal_names"):]
        self.assertNotIn('frappe.get_all(\n\t\t\t"Supplier Quotation"', loop)

    def test_days_window_is_clamped(self):
        self.assertIn("max(7, min(cint(days) or 90, 366))", self.body)


    def test_drill_rows_come_from_the_same_classification_pass(self):
        # The list behind a number must be built in the SAME loop that counted
        # it — a second query could disagree with the box.
        loop = self.body[self.body.index("for deal in _tender_deal_names"):]
        self.assertIn('stage_rows.setdefault(stage', loop)
        self.assertIn('out["rows"] = stage_rows', self.body)
        self.assertIn('out["so_rows"] = so_rows', self.body)

    def test_terminal_drill_lists_match_the_window_rule(self):
        self.assertIn('if stage not in ("won", "lost") or in_window:', self.body)

    def test_guarded_on_missing_columns(self):
        for col in ("custom_crm_deal", "custom_bid_pricing", "custom_board_stage"):
            with self.subTest(col=col):
                self.assertIn(col, self.body)
        self.assertIn("frappe.db.has_column", self.body)


class PanelTest(unittest.TestCase):
    def setUp(self):
        self.vue = read(VUE)

    def test_calls_the_endpoint(self):
        self.assertIn('call("stabler.api.tender.tender_funnel"', self.vue)

    def test_every_stage_navigates_to_its_original_list(self):
        # Dead-end numbers are banned; and no Desk /app links, ever. Deal stages
        # open My Tenders filtered by funnel_stage; execution buckets open the
        # contract board, whose columns are the native list.
        self.assertNotIn('"/app', self.vue)
        self.assertNotIn("'/app", self.vue)
        self.assertIn('query: { funnel_stage: st.key }', self.vue)
        self.assertIn('"/tender/my-tenders"', self.vue)
        self.assertIn('"/tender/board"', self.vue)

    def test_dashboard_is_graphics_only(self):
        # The records live on their original list pages, not under the charts.
        self.assertNotIn("<table", self.vue)

    def test_my_tenders_filters_from_the_same_classification(self):
        # The number and the list must share one source: My Tenders builds its
        # funnel_stage filter from tender_funnel.rows, not from a re-derivation.
        mt = read(os.path.join(_ROOT, "public", "js", "pages", "tender", "MyTenders.vue"))
        self.assertIn("funnel_stage", mt)
        self.assertIn('call("stabler.api.tender.tender_funnel"', mt)
        self.assertIn("funnelDeals.value.has(r.deal)", mt)

    def test_all_user_facing_strings_are_translated(self):
        # Template text nodes must go through t(); catch bare Turkish/English words.
        tpl = self.vue[self.vue.index("<template>"):]
        bare = re.findall(r">\s*([A-Za-zÇĞİÖŞÜçğıöşü][^<{}]{3,40})\s*<", tpl)
        allowed = {"—"}
        offenders = [b.strip() for b in bare if b.strip() and b.strip() not in allowed]
        self.assertEqual(offenders, [], f"untranslated template text: {offenders}")

    def test_mounted_on_the_director_board(self):
        board = read(BOARD)
        self.assertIn("TenderFunnel", board)
        self.assertIn("<TenderFunnel />", board)


if __name__ == "__main__":
    unittest.main()
