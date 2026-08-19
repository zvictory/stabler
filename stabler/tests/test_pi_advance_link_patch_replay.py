"""v80 must not convert a Payment Entry it has already converted.

The patch exists to move supplier advances off the legacy model — a Payment Entry
Reference row pointing at a Proforma Invoice — and onto a durable header link,
`custom_proforma_invoice`. For a draft it does both halves: stamps the link and
strips the PI reference rows.

The half nobody wrote down is what a *second* run does. The scan asked only
"which Payment Entry Reference rows point at a Proforma Invoice", with no time
bound and no test for work already done, so on a replay it re-selected every
payment it had ever converted plus every one created since — and
`imports_module/hooks.py:50-62` still keeps `Proforma Invoice` a valid reference
doctype for a supplier, so a hand-built advance can be sitting in exactly that
shape right now. For a draft the patch then removed its reference rows and saved
it. A supplier advance in progress loses its PI relationship,
`unallocated_amount` is recomputed, and if it is submitted afterwards the money
sits in the ledger with nothing pointing back at the Proforma.

A patch does not have to be forgotten by Frappe to run twice. `16328bf` is the
measured case: a site whose Patch Log claimed all 94 patches while 206 Custom
Fields were missing, repaired by running modules by hand — and P1's repair path
is live right now. That is the worst moment for a patch to quietly rewrite live
documents, because the operator is mid-incident and is not watching a feature
they did not touch.

So the rule pinned here is the same one the module-flag patches learned: **a row
that already carries the answer is left alone.** Only a payment with no link yet
is work.
"""

from __future__ import annotations

import importlib
import types
import unittest

from stabler.tests.module_sandbox import ModuleSandbox

_SANDBOX = ModuleSandbox()
_PATCH = "stabler.patches.v80_pe_proforma_advance_ref"


class FakeDoc:
	def __init__(self, name, references):
		self.name = name
		self.references = [
			types.SimpleNamespace(reference_doctype=d, reference_name=n) for d, n in references
		]
		self.saved = False

	def get(self, key):
		return getattr(self, key, None)

	def set(self, key, value):
		setattr(self, key, value)

	def save(self, **kwargs):
		self.saved = True


def _run(*, payments, field_exists=True):
	"""Execute v80 against a hand-built `frappe`.

	`payments` maps a Payment Entry name to
	``{"pi": <custom_proforma_invoice or None>, "docstatus": int, "refs": [(doctype, name), ...]}``.
	"""
	ctx = types.SimpleNamespace(writes=[], docs={}, queries=[], created_field=False)

	frappe = types.ModuleType("frappe")

	def _exists(doctype, name=None):
		return field_exists

	def _sql(query, params=None, **kwargs):
		ctx.queries.append(query)
		# Honour the shapes the patch actually issues. The predicate that makes
		# the patch self-cleaning is the one being pinned, so the double reads it
		# out of the query rather than assuming it: drop it from the patch and
		# this fake really does hand back the converted rows again.
		only_unconverted = "custom_proforma_invoice" in query
		rows = []
		for name, p in payments.items():
			if only_unconverted and (p.get("pi") or ""):
				continue
			for doctype, ref in p["refs"]:
				if doctype == "Proforma Invoice":
					rows.append({"parent": name, "reference_name": ref})
		return rows

	def _set_value(doctype, name, field, value, **kwargs):
		ctx.writes.append((name, field, value))
		payments[name]["pi"] = value

	def _get_value(doctype, name, field, **kwargs):
		return payments[name]["docstatus"]

	frappe.db = types.SimpleNamespace(
		exists=_exists,
		sql=_sql,
		set_value=_set_value,
		get_value=_get_value,
		commit=lambda: None,
	)
	frappe.clear_cache = lambda **kwargs: None

	def _get_doc(doctype, name):
		doc = FakeDoc(name, payments[name]["refs"])
		ctx.docs[name] = doc
		return doc

	frappe.get_doc = _get_doc

	custom = types.ModuleType("frappe.custom")
	dt = types.ModuleType("frappe.custom.doctype")
	cf = types.ModuleType("frappe.custom.doctype.custom_field")
	cf_mod = types.ModuleType("frappe.custom.doctype.custom_field.custom_field")

	def _create_custom_field(doctype, spec, **kwargs):
		ctx.created_field = True

	cf_mod.create_custom_field = _create_custom_field

	_SANDBOX.evict(_PATCH, "frappe")
	_SANDBOX.install(
		{
			"frappe": frappe,
			"frappe.custom": custom,
			"frappe.custom.doctype": dt,
			"frappe.custom.doctype.custom_field": cf,
			"frappe.custom.doctype.custom_field.custom_field": cf_mod,
		}
	)
	importlib.import_module(_PATCH).execute()
	return ctx


def tearDownModule():
	_SANDBOX.restore()


class ReplayLeavesConvertedPaymentsAlone(unittest.TestCase):
	def test_a_draft_advance_that_already_carries_its_link_is_not_touched(self):
		"""The damage case: a live supplier advance losing its Proforma.

		The link is set, so the conversion is done. Re-selecting it strips the
		reference rows off a document somebody is still working on — and the
		patch reports nothing, because from its point of view it converted a row.
		"""
		payments = {
			"PE-0001": {"pi": "PI-2026-0009", "docstatus": 0, "refs": [("Proforma Invoice", "PI-2026-0009")]}
		}
		ctx = _run(payments=payments)
		self.assertEqual(ctx.writes, [], "a converted payment must not be written again")
		self.assertEqual(ctx.docs, {}, "a converted payment must not even be loaded, let alone saved")

	def test_a_replay_over_a_fully_converted_site_is_a_no_op(self):
		payments = {
			"PE-0001": {"pi": "PI-1", "docstatus": 0, "refs": []},
			"PE-0002": {"pi": "PI-2", "docstatus": 1, "refs": [("Proforma Invoice", "PI-2")]},
		}
		ctx = _run(payments=payments)
		self.assertEqual(ctx.writes, [])
		self.assertEqual(ctx.docs, {})


class FirstRunStillConverts(unittest.TestCase):
	"""Idempotency must not be bought by making the patch do nothing."""

	def test_an_unconverted_draft_gets_its_link_and_loses_the_legacy_rows(self):
		payments = {"PE-0001": {"pi": None, "docstatus": 0, "refs": [("Proforma Invoice", "PI-2026-0009")]}}
		ctx = _run(payments=payments)
		self.assertEqual(ctx.writes, [("PE-0001", "custom_proforma_invoice", "PI-2026-0009")])
		self.assertTrue(ctx.docs["PE-0001"].saved)
		self.assertEqual(ctx.docs["PE-0001"].references, [])

	def test_a_submitted_legacy_entry_keeps_its_audit_trail(self):
		"""Stamping the link is safe; rewriting a posted document is not."""
		payments = {"PE-0001": {"pi": None, "docstatus": 1, "refs": [("Proforma Invoice", "PI-2026-0009")]}}
		ctx = _run(payments=payments)
		self.assertEqual(ctx.writes, [("PE-0001", "custom_proforma_invoice", "PI-2026-0009")])
		self.assertEqual(ctx.docs, {}, "a submitted entry must be left for Accounts to cancel and amend")

	def test_a_payment_against_two_proformas_is_never_guessed(self):
		payments = {
			"PE-0001": {
				"pi": None,
				"docstatus": 0,
				"refs": [("Proforma Invoice", "PI-1"), ("Proforma Invoice", "PI-2")],
			}
		}
		ctx = _run(payments=payments)
		self.assertEqual(ctx.writes, [])
		self.assertEqual(ctx.docs, {})

	def test_only_proforma_rows_are_legacy(self):
		"""A Purchase Order reference is the supported model, not something to migrate."""
		payments = {"PE-0001": {"pi": None, "docstatus": 0, "refs": [("Purchase Order", "PO-1")]}}
		ctx = _run(payments=payments)
		self.assertEqual(ctx.writes, [])


if __name__ == "__main__":
	unittest.main()
