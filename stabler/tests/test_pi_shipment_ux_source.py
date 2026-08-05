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
	tail = src[m.start() :]
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


class DeviationsPageTest(unittest.TestCase):
	"""The user's actual goal: the PI is the agreement, the CI is what shipped —
	and the places they disagree must be REALLY visible, with the metrics."""

	def setUp(self):
		self.vue = read(os.path.join(PAGES, "PiCiDiscrepancies.vue"))

	def test_reads_the_shared_endpoint_not_a_rederivation(self):
		self.assertIn('call("stabler.api.imports.get_ci_pi_discrepancies"', self.vue)

	def test_shows_the_agreement_vs_shipment_metrics(self):
		for metric in (
			"matched_lines",
			"orphan_lines",
			"over_keys",
			"remaining_boxes",
			"price_docs",
			"price_agreed",
		):
			with self.subTest(metric=metric):
				self.assertIn(metric, self.vue)

	def test_rows_link_back_to_both_documents(self):
		self.assertIn("imports-commercial-invoice", self.vue)
		self.assertIn("imports-proforma", self.vue)
		self.assertNotIn('"/app', self.vue)

	def test_route_registered_and_reachable_from_the_flow_board(self):
		router = read(os.path.join(_ROOT, "public", "js", "router.js"))
		self.assertIn('"imports-discrepancies"', router)
		flow = read(os.path.join(PAGES, "ImportsFlow.vue"))
		self.assertIn("/imports/discrepancies", flow)


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

	def test_form_match_panel_uses_the_shared_endpoint(self):
		form = read(os.path.join(PAGES, "ProformaForm.vue"))
		self.assertIn('call("stabler.api.imports.get_ci_pi_discrepancies"', form)
		self.assertIn("subCuts", form)

	def test_compare_stays_removed(self):
		# The user rejected PI-vs-PI comparison; the goal is agreement-vs-
		# shipment (the deviations page). Keep the dead feature dead.
		router = read(os.path.join(_ROOT, "public", "js", "router.js"))
		self.assertNotIn("imports-proformas-compare", router)
		self.assertNotIn("compare_proformas", read(API))
		self.assertFalse(os.path.exists(os.path.join(PAGES, "ProformaCompare.vue")))


if __name__ == "__main__":
	unittest.main()
