"""Unit tests for the PR-per-TruckReceipt math (Frappe-free).

Covers PO-rate resolution, the manual-rate override and the unpriced-line block
that stops zero-valued stock from posting, the foreign-currency PO comparison
behind the submit guard, batch naming, the Good-only qty rule, the cold-chain
temperature check, and the Purchase Receipt payload shape.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_receipt_math -v
"""

from __future__ import annotations

import unittest

from stabler.stabler.imports_module import receipt_math as rm


class TestGoodQty(unittest.TestCase):
	def test_only_good_condition_enters_pr(self):
		self.assertEqual(rm.good_qty(1000.0, "Good"), 1000.0)
		self.assertEqual(rm.good_qty(1000.0, "Damaged"), 0.0)
		self.assertEqual(rm.good_qty(1000.0, "Rejected"), 0.0)

	def test_case_insensitive(self):
		self.assertEqual(rm.good_qty(50.0, "good"), 50.0)


class TestTemperatureOk(unittest.TestCase):
	def test_within_range(self):
		self.assertTrue(rm.temperature_ok(-20, -22, -18))

	def test_out_of_range(self):
		self.assertFalse(rm.temperature_ok(-5, -22, -18))
		self.assertFalse(rm.temperature_ok(0, -22, -18))

	def test_no_reading_or_no_range_passes(self):
		self.assertTrue(rm.temperature_ok(None, -22, -18))
		self.assertTrue(rm.temperature_ok("", -22, -18))
		self.assertTrue(rm.temperature_ok(-5, None, None))


class TestBatchName(unittest.TestCase):
	def test_container_prefix(self):
		self.assertEqual(
			rm.batch_name("MSKU1234567", "CI-2026-00001", "BEEF-CUBE", "2026-07-10"),
			"MSKU1234567-BEEF-CUBE-2026-07-10",
		)

	def test_falls_back_to_ci(self):
		self.assertEqual(
			rm.batch_name(None, "CI-2026-00001", "BEEF-CUBE", "2026-07-10"),
			"CI-2026-00001-BEEF-CUBE-2026-07-10",
		)


class TestResolvePoRate(unittest.TestCase):
	def _rows(self):
		return [
			{"purchase_order": "PO-1", "purchase_order_item": "row-a", "item_code": "BEEF", "rate": 4.5},
			{"purchase_order": "PO-1", "purchase_order_item": "row-b", "item_code": "LAMB", "rate": 6.0},
		]

	def test_single_match_resolves_rate_and_linkage(self):
		res = rm.resolve_po_rate("BEEF", self._rows())
		self.assertEqual(res["rate"], 4.5)
		self.assertEqual(res["purchase_order"], "PO-1")
		self.assertEqual(res["purchase_order_item"], "row-a")
		self.assertIsNone(res["warning"])

	def test_missing_item_zero_rate_with_warning(self):
		res = rm.resolve_po_rate("CHICKEN", self._rows())
		self.assertEqual(res["rate"], 0.0)
		self.assertIsNone(res["purchase_order"])
		self.assertIn("No linked Purchase Order line", res["warning"])

	def test_ambiguous_same_rate_uses_rate_no_linkage(self):
		rows = [
			{"purchase_order": "PO-1", "purchase_order_item": "a", "item_code": "BEEF", "rate": 4.5},
			{"purchase_order": "PO-2", "purchase_order_item": "b", "item_code": "BEEF", "rate": 4.5},
		]
		res = rm.resolve_po_rate("BEEF", rows)
		self.assertEqual(res["rate"], 4.5)
		self.assertIsNone(res["purchase_order_item"])
		self.assertIn("same rate", res["warning"])

	def test_ambiguous_diff_rate_zero(self):
		rows = [
			{"purchase_order": "PO-1", "purchase_order_item": "a", "item_code": "BEEF", "rate": 4.5},
			{"purchase_order": "PO-2", "purchase_order_item": "b", "item_code": "BEEF", "rate": 5.0},
		]
		res = rm.resolve_po_rate("BEEF", rows)
		self.assertEqual(res["rate"], 0.0)
		self.assertIn("differing rates", res["warning"])


class TestEffectiveRate(unittest.TestCase):
	"""Which number prices a receipt line, and where it came from."""

	def test_manual_rate_wins_so_a_hand_priced_line_is_never_overwritten_by_the_po(self):
		# The buyer typed 4.75 knowing the PO says 4.50 (renegotiated, or the PO is
		# stale). Silently posting 4.50 would value the truck at a price nobody agreed.
		self.assertEqual(rm.effective_rate(4.75, 4.50), (4.75, rm.RATE_SOURCE_MANUAL))

	def test_po_rate_prices_the_line_when_no_one_typed_one(self):
		self.assertEqual(rm.effective_rate(None, 4.50), (4.50, rm.RATE_SOURCE_PO))

	def test_blank_manual_rate_falls_through_instead_of_wiping_out_the_po_rate(self):
		# An untouched form field is not a price of zero — it is no opinion at all.
		for blank in (None, "", "   "):
			with self.subTest(manual=blank):
				self.assertEqual(rm.effective_rate(blank, 4.50), (4.50, rm.RATE_SOURCE_PO))

	def test_zero_or_negative_manual_rate_falls_through_it_is_not_a_price(self):
		# Zero would book the stock at nothing; a negative rate is data entry damage.
		# Neither may beat a real PO rate.
		for bad in (0, 0.0, "0", -1, -0.5, "-3"):
			with self.subTest(manual=bad):
				self.assertEqual(rm.effective_rate(bad, 4.50), (4.50, rm.RATE_SOURCE_PO))

	def test_neither_rate_is_source_none_so_the_caller_can_refuse_to_post(self):
		# The whole point of the source: 0.0 alone is indistinguishable from a real
		# price of zero, so the caller is told *why* the rate is zero.
		self.assertEqual(rm.effective_rate(None, 0.0), (0.0, rm.RATE_SOURCE_NONE))
		self.assertEqual(rm.effective_rate("", None), (0.0, rm.RATE_SOURCE_NONE))
		self.assertEqual(rm.effective_rate(0, 0), (0.0, rm.RATE_SOURCE_NONE))

	def test_a_negative_po_rate_is_not_a_price_either(self):
		self.assertEqual(rm.effective_rate(None, -4.50), (0.0, rm.RATE_SOURCE_NONE))

	def test_unreadable_input_never_raises_it_degrades_to_no_price(self):
		# Rates arrive from a web form and from PO rows. A float() blowing up inside
		# a submit hook would be an unexplained crash on the warehouse floor; being
		# treated as "no price" gets the operator a message naming the line instead.
		for junk in ("abc", "4,50", [], {}, object(), float("nan"), float("inf")):
			with self.subTest(value=junk):
				self.assertEqual(rm.effective_rate(junk, None), (0.0, rm.RATE_SOURCE_NONE))
				self.assertEqual(rm.effective_rate(None, junk), (0.0, rm.RATE_SOURCE_NONE))

	def test_unreadable_manual_rate_still_falls_through_to_a_good_po_rate(self):
		self.assertEqual(rm.effective_rate("abc", 4.50), (4.50, rm.RATE_SOURCE_PO))

	def test_numeric_strings_are_accepted_because_the_form_posts_strings(self):
		self.assertEqual(rm.effective_rate("4.75", None), (4.75, rm.RATE_SOURCE_MANUAL))

	def test_rate_is_rounded_like_every_other_rate_in_this_module(self):
		self.assertEqual(rm.effective_rate(4.123456, None), (4.1235, rm.RATE_SOURCE_MANUAL))


class TestUnpricedLines(unittest.TestCase):
	"""Lines that would enter the Purchase Receipt with no price at all."""

	def _row(self, idx, item_code, qty, manual_rate=None, po_rate=None):
		return {
			"idx": idx,
			"item_code": item_code,
			"qty": qty,
			"manual_rate": manual_rate,
			"po_rate": po_rate,
		}

	def test_positive_qty_with_no_rate_is_reported_zero_valued_stock_must_not_post(self):
		# The defect: 1000 Kg of beef entering the warehouse at 0.00 understates
		# inventory and inflates the gross profit of the eventual sale by the whole
		# line. It has to come back so the caller can stop the receipt.
		rows = [self._row(1, "BEEF", 1000.0)]
		self.assertEqual([r["item_code"] for r in rm.unpriced_lines(rows)], ["BEEF"])

	def test_zero_qty_line_with_no_rate_is_not_reported_it_never_reaches_the_receipt(self):
		# build_pr_payload drops qty <= 0, so an unpriced damaged/rejected line
		# values nothing. Reporting it would block a truck over stock that is not
		# being received — the block has to stay narrow enough to be obeyed.
		rows = [self._row(1, "BEEF", 0.0), self._row(2, "LAMB", -5.0)]
		self.assertEqual(rm.unpriced_lines(rows), [])

	def test_priced_lines_are_not_reported_whichever_side_priced_them(self):
		rows = [
			self._row(1, "BEEF", 1000.0, po_rate=4.50),
			self._row(2, "LAMB", 500.0, manual_rate=6.00),
			self._row(3, "GOAT", 250.0, manual_rate=7.25, po_rate=0.0),
		]
		self.assertEqual(rm.unpriced_lines(rows), [])

	def test_manual_rate_rescues_a_line_the_purchase_order_could_not_price(self):
		# The escape hatch. PO linkage is missing often by design of the current
		# flow, so the block must be survivable without inventing a Purchase Order.
		rows = [self._row(1, "BEEF", 1000.0, manual_rate=4.75, po_rate=0.0)]
		self.assertEqual(rm.unpriced_lines(rows), [])

	def test_offender_keeps_idx_and_item_code_so_the_message_can_name_the_line(self):
		# A block that says "some line has no rate" on a 40-line truck is a block
		# nobody can act on.
		rows = [self._row(7, "BEEF-CUBE", 1000.0)]
		(offender,) = rm.unpriced_lines(rows)
		self.assertEqual(offender["idx"], 7)
		self.assertEqual(offender["item_code"], "BEEF-CUBE")

	def test_every_offender_comes_back_not_just_the_first(self):
		# Naming one line at a time turns one blocked submit into four.
		rows = [
			self._row(1, "BEEF", 1000.0),
			self._row(2, "LAMB", 500.0, po_rate=6.00),
			self._row(3, "GOAT", 250.0),
			self._row(4, "VEAL", 0.0),
			self._row(5, "CHICKEN", 800.0, manual_rate=""),
		]
		self.assertEqual(
			[(r["idx"], r["item_code"]) for r in rm.unpriced_lines(rows)],
			[(1, "BEEF"), (3, "GOAT"), (5, "CHICKEN")],
		)

	def test_zero_and_negative_rates_count_as_unpriced_not_as_a_price(self):
		rows = [
			self._row(1, "BEEF", 1000.0, manual_rate=0, po_rate=0),
			self._row(2, "LAMB", 500.0, manual_rate=-1, po_rate=-2),
		]
		self.assertEqual([r["idx"] for r in rm.unpriced_lines(rows)], [1, 2])

	def test_unreadable_qty_or_rate_does_not_raise_inside_the_guard(self):
		rows = [
			self._row(1, "BEEF", "1000.0"),
			self._row(2, "LAMB", "not-a-number", manual_rate="junk"),
		]
		self.assertEqual([r["idx"] for r in rm.unpriced_lines(rows)], [1])

	def test_no_rows_is_no_offenders(self):
		self.assertEqual(rm.unpriced_lines([]), [])
		self.assertEqual(rm.unpriced_lines(None), [])


class TestZeroValuedStockCannotReachTheReceipt(unittest.TestCase):
	"""End to end over the two cases where ``resolve_po_rate`` returns 0.

	Both used to be logged as a warning while the Purchase Receipt was built and
	submitted anyway. These tests pin the whole chain: resolve -> effective_rate
	-> unpriced_lines, which is what the submit hook runs.
	"""

	def _rows(self):
		"""Same item on two POs at different rates — the resolver gives up here."""
		return [
			{"purchase_order": "PO-1", "purchase_order_item": "row-a", "item_code": "BEEF", "rate": 4.5},
			{"purchase_order": "PO-2", "purchase_order_item": "row-b", "item_code": "BEEF", "rate": 5.0},
		]

	def _chain(self, item_code, qty, manual_rate=None):
		res = rm.resolve_po_rate(item_code, self._rows())
		row = {
			"idx": 1,
			"item_code": item_code,
			"qty": qty,
			"manual_rate": manual_rate,
			"po_rate": res["rate"],
		}
		return res, rm.unpriced_lines([row])

	def test_item_absent_from_every_po_is_blocked_not_received_at_zero(self):
		res, offenders = self._chain("CHICKEN", 1000.0)
		self.assertEqual(res["rate"], 0.0)  # the resolver's "I don't know" value
		self.assertEqual([r["item_code"] for r in offenders], ["CHICKEN"])

	def test_differing_po_rates_are_blocked_not_received_at_zero(self):
		res, offenders = self._chain("BEEF", 1000.0)
		self.assertEqual(res["rate"], 0.0)
		self.assertIn("differing rates", res["warning"])
		self.assertEqual([r["item_code"] for r in offenders], ["BEEF"])

	def test_a_typed_rate_unblocks_the_same_truck(self):
		# The block ships with an escape hatch or receiving locks up: same
		# ambiguous PO data, one number typed on the line, receipt proceeds.
		res, offenders = self._chain("BEEF", 1000.0, manual_rate=4.80)
		self.assertEqual(offenders, [])
		self.assertEqual(rm.effective_rate(4.80, res["rate"]), (4.80, rm.RATE_SOURCE_MANUAL))

	def test_an_unambiguous_po_still_prices_the_line_by_itself(self):
		# No regression: the common case needs no manual rate.
		rows = [{"purchase_order": "PO-1", "purchase_order_item": "row-a", "item_code": "BEEF", "rate": 4.5}]
		res = rm.resolve_po_rate("BEEF", rows)
		rate, source = rm.effective_rate(None, res["rate"])
		self.assertEqual((rate, source), (4.5, rm.RATE_SOURCE_PO))
		self.assertEqual(
			rm.unpriced_lines(
				[{"idx": 1, "item_code": "BEEF", "qty": 1000.0, "manual_rate": None, "po_rate": res["rate"]}]
			),
			[],
		)

	def test_the_line_a_manual_rate_priced_still_carries_its_po_linkage(self):
		# The manual rate overrides the price only. Dropping the linkage would
		# leave the Purchase Order forever "not received", so billing status lies.
		rows = [{"purchase_order": "PO-1", "purchase_order_item": "row-a", "item_code": "BEEF", "rate": 4.5}]
		res = rm.resolve_po_rate("BEEF", rows)
		rate, source = rm.effective_rate(9.99, res["rate"])
		line = rm.build_pr_line(
			item_code="BEEF",
			qty=1000.0,
			rate=rate,
			warehouse="WH - MSA",
			purchase_order=res["purchase_order"],
			purchase_order_item=res["purchase_order_item"],
			batch_no=None,
		)
		self.assertEqual(source, rm.RATE_SOURCE_MANUAL)
		self.assertEqual(line["rate"], 9.99)
		self.assertEqual(line["purchase_order"], "PO-1")
		self.assertEqual(line["purchase_order_item"], "row-a")


class TestMismatchedCurrencyPos(unittest.TestCase):
	"""Which Purchase Orders make the receipt refuse a rate it cannot label.

	The Purchase Receipt is posted in one fixed currency (``PR_CURRENCY`` in
	``hooks.py``). A rate read off a Purchase Order denominated in another one
	would be posted under the receipt's label without conversion — not wrong by a
	rounding, wrong by an exchange rate. ``hooks._block_foreign_currency_po_rates``
	turns whatever comes back here into the refusal, so every rule of the
	comparison is pinned below.
	"""

	PR_CURRENCY = "USD"

	def _line(self, item_code, qty, source=rm.RATE_SOURCE_PO):
		"""One row of the build path's resolved lines."""
		return {"idx": 1, "item_code": item_code, "qty": qty, "source": source}

	def _po_row(self, purchase_order, item_code, currency, rate=4.5):
		return {
			"purchase_order": purchase_order,
			"purchase_order_item": "row-a",
			"item_code": item_code,
			"rate": rate,
			"currency": currency,
		}

	def _call(self, resolved, po_item_rows):
		return rm.mismatched_currency_pos(resolved, po_item_rows, self.PR_CURRENCY)

	def test_a_foreign_currency_po_that_priced_a_received_line_is_reported(self):
		# The defect this guards: 1000 Kg priced at 4.50 EUR posted as 4.50 USD.
		out = self._call([self._line("BEEF", 1000.0)], [self._po_row("PO-1", "BEEF", "EUR")])
		self.assertEqual(out, [{"purchase_order": "PO-1", "currency": "EUR"}])

	def test_a_po_in_the_receipts_own_currency_is_not_reported(self):
		# The ordinary case. Reporting it would block every truck.
		self.assertEqual(self._call([self._line("BEEF", 1000.0)], [self._po_row("PO-1", "BEEF", "USD")]), [])

	def test_a_foreign_po_that_only_priced_a_zero_qty_line_is_not_reported(self):
		# Damaged/rejected weight is dropped by build_pr_payload, so that rate is
		# never posted and there is nothing to mislabel.
		for qty in (0.0, -5.0):
			with self.subTest(qty=qty):
				self.assertEqual(
					self._call([self._line("BEEF", qty)], [self._po_row("PO-1", "BEEF", "EUR")]), []
				)

	def test_a_foreign_po_whose_line_a_manual_rate_priced_is_not_reported(self):
		# A rate typed on the Truck Receipt is a number in the receipt's currency by
		# definition — the PO's currency never reaches the Purchase Receipt. Blocking
		# here would shut the escape hatch on exactly the operator using it correctly.
		self.assertEqual(
			self._call(
				[self._line("BEEF", 1000.0, source=rm.RATE_SOURCE_MANUAL)],
				[self._po_row("PO-1", "BEEF", "EUR")],
			),
			[],
		)

	def test_an_unpriced_line_is_not_reported_it_never_posts_at_all(self):
		self.assertEqual(
			self._call(
				[self._line("BEEF", 1000.0, source=rm.RATE_SOURCE_NONE)],
				[self._po_row("PO-1", "BEEF", "EUR")],
			),
			[],
		)

	def test_a_blank_po_currency_is_not_reported_there_is_nothing_to_compare(self):
		# Nothing to name in the message either, and an unset currency is not the
		# mislabel this guard is about.
		for blank in (None, ""):
			with self.subTest(currency=blank):
				self.assertEqual(
					self._call([self._line("BEEF", 1000.0)], [self._po_row("PO-1", "BEEF", blank)]), []
				)

	def test_two_lines_from_the_same_offending_po_are_reported_once(self):
		# The message names Purchase Orders, not rows; a 40-line truck off one EUR PO
		# must not print that PO forty times.
		out = self._call(
			[self._line("BEEF", 1000.0), self._line("LAMB", 500.0)],
			[self._po_row("PO-1", "BEEF", "EUR"), self._po_row("PO-1", "LAMB", "EUR")],
		)
		self.assertEqual(out, [{"purchase_order": "PO-1", "currency": "EUR"}])

	def test_several_offending_pos_come_back_deduped_in_a_stable_order(self):
		out = self._call(
			[self._line("LAMB", 500.0), self._line("BEEF", 1000.0), self._line("GOAT", 250.0)],
			[
				self._po_row("PO-9", "LAMB", "TRY"),
				self._po_row("PO-2", "BEEF", "EUR"),
				self._po_row("PO-2", "GOAT", "EUR"),
			],
		)
		self.assertEqual(
			out,
			[
				{"purchase_order": "PO-2", "currency": "EUR"},
				{"purchase_order": "PO-9", "currency": "TRY"},
			],
		)

	def test_a_foreign_po_line_for_an_item_this_receipt_did_not_price_is_ignored(self):
		# The CI's POs cover more items than one truck carries. Only the items whose
		# rate this receipt actually took off a PO can be mislabelled.
		out = self._call(
			[self._line("BEEF", 1000.0)],
			[self._po_row("PO-1", "BEEF", "USD"), self._po_row("PO-2", "CHICKEN", "EUR")],
		)
		self.assertEqual(out, [])

	def test_unreadable_qty_does_not_raise_inside_the_guard(self):
		# Same rule as everywhere else in this module: bad input degrades, it never
		# blows up inside a submit hook.
		self.assertEqual(self._call([self._line("BEEF", "junk")], [self._po_row("PO-1", "BEEF", "EUR")]), [])
		self.assertEqual(
			self._call([self._line("BEEF", "1000")], [self._po_row("PO-1", "BEEF", "EUR")]),
			[{"purchase_order": "PO-1", "currency": "EUR"}],
		)

	def test_nothing_to_compare_is_no_offenders(self):
		self.assertEqual(self._call([], []), [])
		self.assertEqual(self._call(None, None), [])
		self.assertEqual(self._call([self._line("BEEF", 1000.0)], []), [])


class TestBuildPrPayload(unittest.TestCase):
	def _line(self, item, qty, batch=None, po=None, poi=None):
		return rm.build_pr_line(
			item_code=item,
			qty=qty,
			rate=4.5,
			warehouse="WH - MSA",
			purchase_order=po,
			purchase_order_item=poi,
			batch_no=batch,
		)

	def test_zero_qty_lines_dropped(self):
		lines = [self._line("BEEF", 1000.0), self._line("LAMB", 0.0)]
		payload = rm.build_pr_payload(
			company="MSA",
			supplier="IRAN MEAT CO",
			posting_date="2026-07-10",
			currency="USD",
			warehouse="WH - MSA",
			lines=lines,
			truck_receipt_name="TRK-RCV-2026-00001",
		)
		self.assertEqual(len(payload["items"]), 1)
		self.assertEqual(payload["items"][0]["item_code"], "BEEF")
		self.assertEqual(payload["items"][0]["uom"], "Kg")
		self.assertEqual(payload["currency"], "USD")
		self.assertEqual(payload["set_posting_time"], 1)
		self.assertNotIn("docstatus", payload)

	def test_none_when_nothing_receivable(self):
		payload = rm.build_pr_payload(
			company="MSA",
			supplier="IRAN MEAT CO",
			posting_date="2026-07-10",
			currency="USD",
			warehouse="WH - MSA",
			lines=[self._line("BEEF", 0.0)],
			truck_receipt_name="TRK-RCV-2026-00001",
		)
		self.assertIsNone(payload)

	def test_batch_and_po_linkage_carried(self):
		line = self._line("BEEF", 1000.0, batch="B1", po="PO-1", poi="row-a")
		self.assertEqual(line["batch_no"], "B1")
		self.assertEqual(line["purchase_order"], "PO-1")
		self.assertEqual(line["purchase_order_item"], "row-a")
		# No batch -> no batch_no key at all.
		self.assertNotIn("batch_no", self._line("BEEF", 1000.0))


if __name__ == "__main__":
	unittest.main()
