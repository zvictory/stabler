"""Structural guards for the CI-side hand-linking panel (stabler-iic, W2).

The backend (set_bill_import_refs / clear_bill_import_refs / unlinked_transport_bills)
is already finished and pinned by test_bill_import_refs_source.py; this file pins the
frontend panel in CommercialInvoiceForm.vue that lets staff manually attribute a draft
transport/service bill to a Commercial Invoice — attribution only, never a Container
Cost Line or Landed Cost Voucher (C1, that's W3 and not approved here). Source-text,
like its neighbours: a .vue SFC has no unit harness in this repo.

Run:
    PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_ci_bill_link_panel_source
"""

from __future__ import annotations

import os
import re
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, ".."))
PAGES = os.path.join(_ROOT, "public", "js", "pages", "imports")
VUE = os.path.join(PAGES, "CommercialInvoiceForm.vue")


def read(p):
	with open(p, encoding="utf-8") as fh:
		return fh.read()


def close_at(src, start_idx):
	# Slice to the function/const's OWN closing brace, not the next top-level
	# declaration — a lookahead-to-next-decl slice would sweep in the prose
	# comment sitting between two functions and produce false matches.
	return src[start_idx : src.index("\n}\n", start_idx) + 3]


def func_body(src, name):
	m = re.search(rf"^(?:async )?function {name}\(", src, re.M)
	assert m, f"{name} not found"
	return close_at(src, m.start())


class PanelFailsQuietTest(unittest.TestCase):
	"""C4 / cost-visibility masking: a user without the permission, or a company
	with no configured transport/service supplier groups, must see NOTHING —
	not a red error banner. Backend confirms `configured:False` on the former
	and `_assert_cost_visible()` throws on the latter."""

	def setUp(self):
		self.vue = read(VUE)
		self.fetch = func_body(self.vue, "fetchUnlinkedBills")

	def test_unconfigured_company_hides_the_panel(self):
		self.assertIn("unlinkedBillsHidden.value = !res?.configured;", self.fetch)

	def test_a_thrown_error_also_hides_the_panel_and_only_logs(self):
		catch_block = self.fetch.split("} catch (e) {", 1)[1].split("} finally {", 1)[0]
		self.assertIn("unlinkedBillsHidden.value = true;", catch_block)
		# The whole point of "fail quietly": no toast, no visible error surface —
		# a cost-visibility 403 must look identical to "nothing to show".
		self.assertNotIn("toast.error", catch_block)
		self.assertNotIn("toast.success", catch_block)
		self.assertIn("console.error(", catch_block)

	def test_the_template_gates_on_the_hidden_flag(self):
		self.assertIn('v-else-if="unlinkedBillsRequested && !unlinkedBillsHidden"', self.vue)

	def test_nothing_fetches_before_the_user_asks(self):
		# On-demand: the state starts false and only the trigger button's own
		# click handler calls fetchUnlinkedBills — it must not be reachable from
		# a lifecycle hook, which is how "company-wide query on every page view"
		# regressions happen.
		self.assertIn("const unlinkedBillsRequested = ref(false);", self.vue)
		on_mounted = self.vue[self.vue.index("onMounted(") :]
		on_mounted = on_mounted[: on_mounted.index("\n});") + 4]
		self.assertNotIn("fetchUnlinkedBills", on_mounted)


class SkeletonPlacementTest(unittest.TestCase):
	"""SkeletonRows renders its own <tbody> — wrapping it in a manual <tbody>
	(or a bare spinner instead of it) is the two failure modes CLAUDE.md calls
	out for loading state on list pages."""

	def setUp(self):
		self.vue = read(VUE)
		start = self.vue.index('v-if="loadingUnlinkedBills" class="table-responsive"')
		self.block = self.vue[start : self.vue.index("</table>", start) + 8]

	def test_skeleton_used_not_a_bare_spinner(self):
		self.assertIn("<SkeletonRows", self.block)
		self.assertNotIn("spinner-border", self.block)

	def test_skeleton_is_a_direct_thead_sibling_not_nested_in_a_tbody(self):
		self.assertRegex(self.block, r"</thead>\s*<SkeletonRows")
		self.assertNotIn("<tbody", self.block)


class CappedBannerTest(unittest.TestCase):
	def setUp(self):
		self.vue = read(VUE)

	def test_the_truncation_banner_reads_the_real_summary_fields(self):
		self.assertIn("unlinkedBillsResult?.summary?.capped", self.vue)
		self.assertIn("unlinkedBillsResult.summary.limit", self.vue)
		self.assertIn(
			't("Showing only the first {limit} bills — narrow the picture before assuming a missing bill was never entered.", { limit: unlinkedBillsResult.summary.limit })',
			self.vue,
		)


class LinkOutcomesAreNeverSwallowedTest(unittest.TestCase):
	"""A bulk action over N bills must report N outcomes, not a single boolean —
	one bad row (already CI-supplier, already vouchered) must not hide that the
	other rows succeeded, and vice versa."""

	def setUp(self):
		self.vue = read(VUE)
		self.link = func_body(self.vue, "linkSelectedBills")

	def test_each_bill_gets_its_own_try_catch_not_a_shared_promise_all(self):
		# Promise.all over N whitelisted calls would reject the whole batch on
		# the FIRST failure and silently drop every outcome after it.
		self.assertIn("for (const name of selectedUnlinkedBills.value) {", self.link)
		self.assertNotIn("Promise.all(selectedUnlinkedBills", self.link)

	def test_a_failure_carries_the_servers_verbatim_message(self):
		self.assertIn("results.push({ name, ok: true })", self.link)
		self.assertIn(
			'results.push({ name, ok: false, message: e?.message || t("Failed to link.") })', self.link
		)

	def test_the_call_shape_matches_the_backend_contract(self):
		self.assertIn(
			"importsApi.setBillImportRefs({ purchase_invoice: name, commercial_invoice: docName.value })",
			self.link,
		)

	def test_outcomes_render_with_the_servers_message_on_failure(self):
		self.assertIn(
			"{{ o.ok ? t('Linked.') : o.message }}",
			self.vue,
		)


class UnlinkSurfacesServerRefusalTest(unittest.TestCase):
	def setUp(self):
		self.vue = read(VUE)
		self.unlink = func_body(self.vue, "unlinkBill")

	def test_unlink_calls_the_clear_endpoint_with_just_the_bill_name(self):
		self.assertIn("importsApi.clearBillImportRefs(bill.name)", self.unlink)

	def test_a_server_refusal_reaches_the_user_verbatim(self):
		# clear_bill_import_refs frappe.throw()s on "already vouchered" / "is the
		# CI supplier" / etc — the client must not paraphrase or swallow it.
		self.assertIn('toast.error(e?.message || t("Failed to unlink the bill."))', self.unlink)


class RefetchStaysOnDemandTest(unittest.TestCase):
	"""Both mutations re-fetch (never mutate optimistically), but the candidate
	panel refetch must stay gated on having been opened at least once — an
	Unlink click in the always-visible Supplier bills table must not pop the
	company-wide panel open on its own."""

	def test_both_mutations_guard_the_panel_refetch_the_same_way(self):
		vue = read(VUE)
		for name in ("linkSelectedBills", "unlinkBill"):
			with self.subTest(fn=name):
				blk = func_body(vue, name)
				self.assertIn("const refetches = [fetchCostOverview()];", blk)
				self.assertIn("if (unlinkedBillsRequested.value) refetches.push(fetchUnlinkedBills());", blk)
				self.assertIn("await Promise.all(refetches);", blk)


class UnlinkHintIsDataOnlyTest(unittest.TestCase):
	"""billUnlinkBlockedReason is a UI hint built from data the page already has
	— it must mirror only what clear_bill_import_refs can be predicted from
	client-side, and must never claim to know "vouchered" status, which is not
	present in any response this page fetches. Claiming it anyway would grey
	out a button that the server would actually allow, or the reverse."""

	def setUp(self):
		self.vue = read(VUE)
		self.reason = func_body(self.vue, "billUnlinkBlockedReason")

	def test_the_two_known_gates_are_checked(self):
		self.assertIn("bill.custom_import_expense", self.reason)
		self.assertIn("bill.supplier === form.value.supplier", self.reason)

	def test_vouchered_status_is_never_guessed_client_side(self):
		for forbidden in ("Landed Cost Voucher", "lcv_ref", "vouchered", "Container Cost Line"):
			with self.subTest(forbidden=forbidden):
				self.assertNotIn(forbidden, self.reason)

	def test_the_button_stays_enabled_when_no_hint_fires(self):
		self.assertIn('v-if="!billUnlinkBlockedReason(b)"', self.vue)
		self.assertIn(':disabled="unlinkingBill === b.name"', self.vue)


class NoCapitalizationTest(unittest.TestCase):
	"""C1: attribution only. Isolate the new block so unrelated, pre-existing
	landed-cost code elsewhere on this huge page (GRN / LCV review sections)
	cannot mask a regression introduced here."""

	def setUp(self):
		self.vue = read(VUE)
		start = self.vue.index('t("Bills you can attach")')
		end = self.vue.index('t("Expenses without bills")')
		self.new_template = self.vue[start:end]
		self.new_funcs = "\n".join(
			func_body(self.vue, name)
			for name in ("fetchUnlinkedBills", "linkSelectedBills", "unlinkBill", "billUnlinkBlockedReason")
		)

	def test_no_capitalization_endpoint_or_doctype_is_touched(self):
		for blk_name, blk in (("template", self.new_template), ("functions", self.new_funcs)):
			for forbidden in (
				"create_additional_lcv",
				"Container Cost Line",
				"Landed Cost Voucher",
				"landed_cost",
			):
				with self.subTest(block=blk_name, forbidden=forbidden):
					self.assertNotIn(forbidden, blk)


class DisplayFormattingTest(unittest.TestCase):
	"""CLAUDE.md: money through the file's own display formatter (this panel is
	read-only, so MoneyInput does not apply), dates through formatDate, status
	through the centralized badge map — never a bare number, a raw ISO string,
	or a per-page status dict."""

	def setUp(self):
		self.vue = read(VUE)
		start = self.vue.index('t("Bills you can attach")')
		self.block = self.vue[start : self.vue.index('t("Expenses without bills")')]

	def test_money_goes_through_the_shared_formatter(self):
		self.assertIn("fm(r.grand_total, r.currency)", self.block)
		self.assertIn("fm(r.outstanding_amount, r.currency)", self.block)
		self.assertNotIn("MoneyInput", self.block)

	def test_dates_go_through_format_date_not_raw_interpolation(self):
		self.assertIn("r.posting_date ? formatDate(r.posting_date)", self.block)
		self.assertIn("r.due_date ? formatDate(r.due_date)", self.block)
		self.assertNotIn("{{ r.posting_date }}", self.block)
		self.assertNotIn("{{ r.due_date }}", self.block)

	def test_status_goes_through_the_centralized_badge_map(self):
		self.assertIn("getStatusBadgeClass('Purchase Invoice', r.status)", self.block)
		self.assertIn('import { getStatusBadgeClass } from "../../composables/status.js";', self.vue)


class ButtonAndTableHygieneTest(unittest.TestCase):
	def setUp(self):
		self.vue = read(VUE)
		start = self.vue.index('t("Bills you can attach")')
		self.block = self.vue[start : self.vue.index('t("Expenses without bills")')]

	def test_only_one_primary_button_in_this_regions_visual_scope(self):
		# CLAUDE.md: max one .btn-primary per region. The trigger/refresh button
		# is outline-primary; only "Link N bill(s)" is the solid primary.
		self.assertEqual(self.block.count("btn btn-primary"), 1)
		self.assertIn("btn btn-outline-primary btn-sm", self.block)

	def test_no_manual_table_striped_class(self):
		# Striping is global (stabler.css); a manual class here would either be
		# a no-op or double the effect if the global rule ever changes shape.
		self.assertNotIn("table-striped", self.block)

	def test_the_supplier_bills_table_grew_an_actions_column_correctly(self):
		self.assertIn('<th>{{ t("Actions") }}</th>', self.vue)
		# The empty-state row's colspan must track the real column count, or an
		# empty table renders a visibly misaligned border.
		self.assertIn(
			'<td colspan="8" class="text-center text-secondary py-2">{{ t("No supplier bills linked yet.") }}</td>',
			self.vue,
		)


if __name__ == "__main__":
	unittest.main()
