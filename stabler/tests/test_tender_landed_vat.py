"""Source-level guard tests for WP-T1 (recoverable import VAT on tender landed).

Frappe-free: they assert structural properties of api/tender.py that protect the
money-correctness fix — for a VAT-registered company, import VAT is recoverable
input tax and must NOT be capitalized into landed cost. A refactor that silently
re-capitalizes VAT (the very bug this fixes, which makes the board pick the wrong
vendor) fails here.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_tender_landed_vat -v
"""

from __future__ import annotations

import os
import re
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_TENDER = os.path.normpath(os.path.join(_HERE, "..", "api", "tender.py"))


def _read() -> str:
	with open(_TENDER, encoding="utf-8") as f:
		return f.read()


def _func_body(src: str, name: str) -> str:
	m = re.search(rf"^def {name}\(", src, re.M)
	assert m, f"function {name} not found"
	tail = src[m.start() :]
	nxt = re.search(r"\n(?:@frappe\.whitelist\(\)|def )", tail[1:])
	return tail[: nxt.start() + 1] if nxt else tail


class TestTenderLandedVat(unittest.TestCase):
	def setUp(self):
		self.src = _read()

	def test_parse_landed_preserves_recoverable_flag(self):
		body = _func_body(self.src, "_parse_landed")
		self.assertIn(
			"vat_recoverable",
			body,
			"_parse_landed must round-trip the vat_recoverable flag so the "
			"capitalize/exclude decision survives save+reload",
		)
		# Default True: new customs lines exclude VAT from landed cost.
		self.assertRegex(
			body,
			r'vat_recoverable["\']?\s*,?\s*True',
			"vat_recoverable must default True (VAT-registered = recoverable)",
		)

	def test_recoverable_vat_gated_and_reported(self):
		body = _func_body(self.src, "po_landed_charges")
		self.assertIn("recoverable_vat", body, "must surface recoverable_vat total")
		# The tally must be gated on the flag — never sum VAT for lines that are
		# genuinely capitalizing it (non-registered scenario).
		self.assertIn(
			"vat_recoverable",
			body,
			"recoverable_vat must be gated on the vat_recoverable flag",
		)

	def test_hs_rate_lookup_gated_and_effective_dated(self):
		body = _func_body(self.src, "hs_rate_lookup")
		# Gated like every board endpoint.
		self.assertIn("_require_tender", body)
		self.assertIn("_assert_company_scope", body)
		# Latest effective row wins; only rows in force today.
		self.assertIn('"effective_from": ["<=", today()]', body)
		self.assertIn('order_by="effective_from desc"', body)
		# Not-found path returns found=False so the UI keeps manual entry.
		self.assertIn('"found": False', body)

	def test_recoverable_vat_base_includes_excise(self):
		# VAT base = customs value + duty + excise (imports-engine parity).
		body = _func_body(self.src, "po_landed_charges")
		self.assertIn("excise", body)
		self.assertIn("+ duty + excise", body)

	def test_actual_from_voucher_gated_and_scoped(self):
		body = _func_body(self.src, "landed_actual_from_voucher")
		self.assertIn("_require_tender", body)
		self.assertIn("_assert_company_scope", body)
		# Company must match + read permission enforced (the real boundary).
		self.assertIn('get_value(vt, vn, "company") != company', body)
		self.assertIn('frappe.has_permission(vt, "read"', body)
		# Only the three ledger doctypes; base-currency amounts.
		self.assertIn("_ACTUAL_VOUCHER_TYPES", body)
		self.assertIn("base_grand_total", body)
		self.assertIn("base_paid_amount", body)
		self.assertIn("total_debit", body)
		# Not-found path returns found=False so the UI keeps manual entry.
		self.assertIn('"found": False', body)

	def test_actual_voucher_fields_round_trip(self):
		body = _func_body(self.src, "_parse_landed")
		self.assertIn("actual_voucher_type", body)
		self.assertIn("actual_voucher", body)

	def test_landed_split_sums_amount_not_a_recomputed_total(self):
		# The planned/actual landed roll-up must use the stored `amount` (which the
		# frontend already computed as duty-only when recoverable) — NOT re-derive
		# duty+VAT here, which would re-introduce the capitalized-VAT bug.
		body = _func_body(self.src, "_deal_landed_split")
		self.assertIn('c["amount"]', body)
		self.assertNotIn("vat_pct", body)


if __name__ == "__main__":
	unittest.main()
