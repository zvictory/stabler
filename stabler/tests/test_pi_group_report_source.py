"""Structural guards for the PI Group Container Status report.

Two of these guards memorialize bugs found in the original port: SQL that
selected columns the doctype does not have (the report 500'd on first real
call), and filter parameters accepted in the signature but never applied.
"""

from __future__ import annotations

import json
import os
import re
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, ".."))
API = os.path.join(_ROOT, "api", "reports.py")
VUE = os.path.join(_ROOT, "public", "js", "pages", "reports", "PiGroupContainerStatus.vue")
DOCTYPE = os.path.join(_ROOT, "stabler", "doctype", "import_pi_group", "import_pi_group.json")


def read(p):
	with open(p, encoding="utf-8") as fh:
		return fh.read()


def body(src, name):
	m = re.search(rf"^def {name}\(", src, re.M)
	assert m, f"{name} not found"
	tail = src[m.start() :]
	nxt = re.search(r"\n(?:@frappe\.whitelist\(\)|def |# ---)", tail[1:])
	return tail[: nxt.start() + 1] if nxt else tail


class EndpointTest(unittest.TestCase):
	def setUp(self):
		self.src = read(API)
		self.body = body(self.src, "get_pi_group_container_status_report")

	def test_whitelisted_scoped_and_module_gated(self):
		self.assertRegex(self.src, r"@frappe\.whitelist\(\)\ndef get_pi_group_container_status_report\(")
		self.assertIn("_assert_company_scope(company)", self.body)
		# The route carries module: imports — the endpoint must gate the same.
		self.assertIn('module_map_for(company).get("imports")', self.body)

	def test_read_only(self):
		for token in (".save(", ".insert(", "db_set(", "db.set_value(", "db.commit("):
			with self.subTest(token=token):
				self.assertNotIn(token, self.body)

	def test_every_sql_column_exists_on_the_doctype(self):
		# The original port selected pg.group_title and pg.vendor — neither
		# exists on Import PI Group, so the report 500'd on first real call.
		# Validate every pg.<column> in the SQL against the doctype JSON.
		fields = {f["fieldname"] for f in json.load(open(DOCTYPE))["fields"]}
		fields |= {"name", "creation", "modified", "owner", "docstatus"}
		used = set(re.findall(r"\bpg\.([a-z_]+)", self.body))
		unknown = sorted(used - fields)
		self.assertEqual(unknown, [], f"SQL selects columns Import PI Group does not have: {unknown}")

	def test_no_dead_filters(self):
		# Every filter in the signature must actually narrow the data.
		for token in ('params["pi_group"]', 'params["vendor"]', '"pi_date"', 'pi_filters["status"]'):
			with self.subTest(token=token):
				self.assertIn(token, self.body)

	def test_planned_fcl_comes_from_the_field_not_a_heuristic(self):
		self.assertIn('"Proforma Invoice Item"', self.body)
		self.assertIn('fields=["fcl"]', self.body)
		for fabrication in ("1400", "len(member_pis)\n"):
			with self.subTest(fabrication=fabrication):
				self.assertNotIn(f"or {fabrication}", self.body)

	def test_no_sql_function_in_a_string_select(self):
		# Frappe v16 rejects SQL functions as strings in SELECT fields.
		offenders = re.findall(r'fields=\[[^\]]*"(?:count|sum|avg|min|max)\s*\(', self.body, re.I)
		self.assertEqual(offenders, [], f"SQL function in a string SELECT: {offenders}")

	def test_counts_and_amounts_share_one_bucket_map(self):
		self.assertIn("_pi_group_report", self.body)
		self.assertEqual(self.body.count("pgr.tally("), 2)  # counts + amounts
		self.assertIn("pgr.pending_containers(", self.body)
		self.assertIn("pgr.pending_amount(", self.body)

	def test_pending_is_not_clamped(self):
		self.assertNotIn("max(0", self.body)


class PanelTest(unittest.TestCase):
	def setUp(self):
		self.vue = read(VUE)

	def test_dual_row_grid_renders_the_amounts(self):
		# The spec's defining feature: a second, muted row with the money in
		# the same columns.
		self.assertIn("pgr-amounts", self.vue)
		self.assertIn("(r.amounts || {}).ORIGIN", self.vue)
		self.assertIn("(totals.grand_amounts || {}).DELIVERED", self.vue)

	def test_negative_pending_is_highlighted_not_hidden(self):
		self.assertIn("r.pending_containers < 0", self.vue)
		self.assertIn("r.pending_amount < 0", self.vue)

	def test_csv_exports_both_rows(self):
		self.assertIn("a.ORIGIN || 0", self.vue)
		self.assertIn("r.ci_agreed_total || 0", self.vue)

	def test_formatting_rules(self):
		# Dates through formatDate, money through formatMoney — never raw.
		self.assertIn("formatDate(r.date_min)", self.vue)
		self.assertIn("fm(r.agreed_total, r.currency)", self.vue)

	def test_no_desk_links(self):
		self.assertNotIn('"/app', self.vue)
		self.assertNotIn("'/app", self.vue)


if __name__ == "__main__":
	unittest.main()
