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
PURCHASING = os.path.join(_ROOT, "api", "purchasing.py")
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


class SupplierScopeTest(unittest.TestCase):
	"""`list_suppliers` gained an optional imports supplier-group scope.

	Twenty call sites share this one endpoint and only four of them ask for the
	scope, so the no-argument path has to stay the query it has always been —
	otherwise a config row on one tenant silently empties the transporter and
	customs-broker pickers on every other screen. Source-text, not behavioural:
	the module imports frappe at import time and the WHERE is built inline, so
	there is nothing importable to exercise under `make test`.
	"""

	def setUp(self):
		self.body = body(read(PURCHASING), "list_suppliers")

	def test_list_suppliers_keeps_the_unfiltered_identity_path(self):
		# The seed condition is still the bare one: without a scope the query
		# filters exactly what it filtered before.
		self.assertIn('conds = ["disabled = 0"]', self.body)
		# Also pinned by test_master_read_permission.py against the source text.
		self.assertIn('has_permission("Supplier", "read")', self.body)

		lines = self.body.splitlines()
		seed = next(i for i, ln in enumerate(lines) if 'conds = ["disabled = 0"]' in ln)
		seed_indent = len(lines[seed]) - len(lines[seed].lstrip())
		predicates = [i for i, ln in enumerate(lines) if "supplier_group IN" in ln]
		self.assertTrue(predicates, "the supplier-group predicate is gone")
		for i in predicates:
			indent = len(lines[i]) - len(lines[i].lstrip())
			# Deeper than the seed => it lives under a branch, not in the trunk.
			self.assertGreater(indent, seed_indent, "the group predicate is in the trunk")
			guard = [ln for ln in lines[seed:i] if ln.strip().startswith("if ")]
			self.assertTrue(guard, "the group predicate is appended unconditionally")

	def test_group_names_are_bound_never_interpolated(self):
		# Group names come from a config row an admin types; they reach the
		# query as a parameter or not at all.
		self.assertIn("supplier_group IN %(", self.body)
		self.assertNotIn("supplier_group IN ('", self.body)
		self.assertNotIn('supplier_group IN ("', self.body)

	def test_the_client_sends_a_scope_key_not_a_group_list(self):
		# C3: a tenant's group names never travel to the browser. The argument
		# is a key the server resolves against Stabler Settings.
		self.assertIn("supplier_group_scope", self.body)
		self.assertIn("imports_supplier_groups_for", self.body)

	def test_an_unknown_scope_key_is_reported_not_swallowed(self):
		# A typo'd key must read as a failure, not as "no filter, all good".
		self.assertIn("frappe.log_error(", self.body)


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
