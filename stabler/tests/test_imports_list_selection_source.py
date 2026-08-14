"""Source-structure guards for the Imports list selection layer.

Why these assertions exist, one by one:

* A list page that shows score cards AND a footer must sum ONE thing. The moment
  the cards read the selection and the footer keeps reading the whole page, the
  screen contradicts itself and the user cannot tell which number is the answer.
  That is why every total is pinned to `scope` and never to `rows`.
* The row checkbox regressed once already: an `@click` on the surrounding cell
  fired the toggle a second time and cancelled it, so ticking a row did nothing.
  `@click.stop` on the input is what keeps that from coming back.
* Filter select widths are a design contract (150/170/200px). 180px was the
  ad-hoc value that made the four Imports lists look subtly different from each
  other, so it is banned outright rather than merely discouraged.
* `import_pi_group` must survive an edit of a Proforma even though its input is
  gone from the form. Dropping the key from the form state would silently unlink
  the PI from its group on the next save — a data-loss bug with no error message.
* The Container landed-cost table is the ONLY editable surface for container
  cost lines and the LCV chain hangs off it. It was explicitly kept during the
  UI pass; this test makes an accidental "cleanup" fail loudly.

Frappe-free: reads .vue sources as text.
"""

import re
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
PAGES = APP / "public" / "js" / "pages" / "imports"
COMPONENTS = APP / "public" / "js" / "components"

LIST_PAGES = (
	"ProformaInvoices.vue",
	"CommercialInvoices.vue",
	"ImportContainers.vue",
	"ImportTrucks.vue",
)


def read(path: Path) -> str:
	return path.read_text(encoding="utf-8")


class ImportsListSelectionSourceTest(unittest.TestCase):
	def test_every_list_page_wires_the_selection_layer(self):
		"""All four lists share one selection implementation, not four look-alikes."""
		for page in LIST_PAGES:
			src = read(PAGES / page)
			for symbol in ("useListSelection", "SelectionBar", "FilterChips", "StatusIcon"):
				self.assertIn(
					symbol,
					src,
					f"{page} must import {symbol} so selection behaves identically on every Imports list",
				)

	def test_footer_totals_read_the_selection_scope(self):
		"""`tfoot` sums `scope`; a total over `rows` would contradict the cards."""
		for page in LIST_PAGES:
			src = read(PAGES / page)
			match = re.search(r"const totals = computed\((.*?)\n\}?\);", src, re.S)
			self.assertIsNotNone(match, f"{page} must expose a `totals` computed for its footer")
			body = match.group(1)
			self.assertIn(
				"scope.value",
				body,
				f"{page} totals must iterate `scope.value` (the selection, or the page when nothing is ticked)",
			)
			self.assertNotIn(
				"of rows.value",
				body,
				f"{page} totals must not iterate `rows.value` — the footer would disagree with the score cards",
			)

	def test_row_checkbox_stops_click_propagation(self):
		"""Regression lock: the double-fire that made ticking a row a no-op."""
		for page in LIST_PAGES:
			src = read(PAGES / page)
			checkbox = re.search(
				r'<input[^>]*?:checked="isSelected\(r\)".*?/>', src, re.S
			)
			self.assertIsNotNone(checkbox, f"{page} must render a per-row selection checkbox")
			markup = checkbox.group(0)
			self.assertIn("@click.stop", markup, f"{page} row checkbox must carry @click.stop")
			self.assertIn("@change=", markup, f"{page} row checkbox must toggle on @change, not @click")

	def test_filter_selects_use_only_the_three_standard_widths(self):
		"""150 / 170 / 200px is the contract; 180px is the drift it replaced."""
		for page in LIST_PAGES:
			src = read(PAGES / page)
			# Only the filter <Select>s are governed — <th> widths are column
			# layout, a different concern with different constraints.
			widths = set(re.findall(r"<Select\b[^>]*?style=\"width:\s*(\d+)px\"", src, re.S))
			self.assertTrue(widths, f"{page} must have at least one filter Select")
			self.assertFalse(
				widths - {"150", "170", "200"},
				f"{page} filter Selects use off-standard widths: {sorted(widths)}",
			)

	def test_kpi_card_declares_the_selection_props(self):
		"""The cards can only show a selection if KpiCard accepts one."""
		src = read(COMPONENTS / "KpiCard.vue")
		props = re.search(r"defineProps\(\{(.*?)\n\}\);", src, re.S)
		self.assertIsNotNone(props, "KpiCard.vue must declare props with defineProps({...})")
		body = props.group(1)
		for prop in ("selected:", "globalValue:", "globalCount:"):
			self.assertIn(prop, body, f"KpiCard.vue must declare the `{prop.rstrip(':')}` prop")

	def test_proforma_form_drops_the_pi_group_input_but_keeps_the_field(self):
		"""The input goes; the stored field stays — otherwise saving unlinks the group."""
		src = read(PAGES / "ProformaForm.vue")
		self.assertNotIn('t("PI Group")', src, "ProformaForm must no longer render a PI Group input")
		self.assertNotIn("groupOptions", src, "ProformaForm must not keep the orphaned PI group options")
		self.assertNotIn(
			"list_pi_groups",
			src,
			"ProformaForm must not fetch PI groups it no longer offers",
		)
		self.assertIn(
			'import_pi_group: ""',
			src,
			"ProformaForm must keep `import_pi_group` in its form state so an edit round-trips it",
		)

	def test_container_form_keeps_the_landed_cost_table(self):
		"""Deliberately preserved during the UI pass — deleting it breaks the LCV chain."""
		src = read(PAGES / "ImportContainerForm.vue")
		for symbol in ("addCostLine", "removeCostLine", "include_in_landed_cost"):
			self.assertIn(
				symbol,
				src,
				f"ImportContainerForm.vue must keep `{symbol}` — the landed-cost lines have no other editor",
			)


if __name__ == "__main__":
	unittest.main()
