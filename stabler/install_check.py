"""Assert that a site actually carries what its Patch Log claims it ran.

A Frappe patch runs once per site because a Patch Log row says it did. That row
is written whether or not the patch did anything, and on a freshly created site
it can be written for all of them at once — `16328bf` is the measured case: zuma's
Patch Log listed all 94 patches applied while 206 Custom Fields were simply
missing. Nothing in the framework notices, because from its point of view the
work is done.

This module asks the opposite question. It does not look at the Patch Log at all;
it looks for the *artifacts* — the two service Items, the roles, the GL indexes,
the fiscal years, the tax templates — and reports the ones that are not there,
naming the patch that was supposed to create each.

**It creates nothing, and it runs no patch.** That restraint is the point. The
obvious repair — "call every patch module's `execute()` after setup" — is the
single most dangerous instruction anyone could follow here: a patch that rewrites
live documents does so again, which is exactly what `v80` did until it was bounded
and what `v62`/`v63`/`v64`/`v65` did to operator decisions. Read this report, then
run the individual patches you have read, one at a time.

    bench --site <site> execute stabler.install_check.run
"""

from __future__ import annotations

import frappe

# (kind, key, patch, why it matters). `why` is the whole value of the report:
# "Role Stabler Declarant is missing" is not actionable; "no one will ever create
# it, because it appears in no doctype JSON" is.
_EXPECTATIONS: tuple[dict, ...] = (
	{
		"kind": "doc",
		"doctype": "Item",
		"name": "Cross-Border Transport",
		"patch": "v43_cross_border_transport_item",
		"why": "the Import Truck CROSSED_BORDER hook bills against this item; without it the hook cannot cut a Purchase Invoice at all",
	},
	{
		"kind": "doc",
		"doctype": "Item",
		"name": "Import Service",
		"patch": "v45_import_service_item",
		"why": "Import Expense Purchase Invoices have no line item to post against",
	},
	{
		"kind": "doc",
		"doctype": "Role",
		"name": "Stabler Tender Director",
		"patch": "v38_tender_view_roles",
		"why": "the tender role windows resolve to nothing, so the screens open empty for everyone",
	},
	{
		"kind": "doc",
		"doctype": "Role",
		"name": "Stabler Declarant",
		"patch": "v38_tender_view_roles",
		"why": "this name appears in NO doctype JSON, so doctype sync will never create it — on a fresh site nothing else brings it into being",
	},
	{
		"kind": "doc",
		"doctype": "Role",
		"name": "Stabler Logist",
		"patch": "v38_tender_view_roles",
		"why": "same as Stabler Declarant: the tender/logistics queues have no role to gate on",
	},
	{
		"kind": "doc",
		"doctype": "Role",
		"name": "Imports User",
		"patch": "v40_imports_roles",
		"why": "the imports module cannot grant access to anyone",
	},
	{
		"kind": "doc",
		"doctype": "Role",
		"name": "Imports Manager",
		"patch": "v40_imports_roles",
		"why": "the imports module cannot grant approval rights to anyone",
	},
	{
		"kind": "doc",
		"doctype": "Fiscal Year",
		"name": "2024",
		"patch": "v47_bootstrap_fiscal_year",
		"why": "posting into a year with no Fiscal Year row is refused by ERPNext at submit, not at entry",
	},
	{
		"kind": "doc",
		"doctype": "Fiscal Year",
		"name": "2025",
		"patch": "v47_bootstrap_fiscal_year",
		"why": "posting into a year with no Fiscal Year row is refused by ERPNext at submit, not at entry",
	},
	{
		"kind": "doc",
		"doctype": "Fiscal Year",
		"name": "2026",
		"patch": "v47_bootstrap_fiscal_year",
		"why": "posting into a year with no Fiscal Year row is refused by ERPNext at submit, not at entry",
	},
	{
		"kind": "doc",
		"doctype": "Fiscal Year",
		"name": "2027",
		"patch": "v47_bootstrap_fiscal_year",
		"why": "posting into a year with no Fiscal Year row is refused by ERPNext at submit, not at entry",
	},
	{
		"kind": "index",
		"table": "tabGL Entry",
		"name": "stabler_party_balance_idx",
		"patch": "v77_gl_entry_party_indexes",
		"why": "the party-balance scan falls back to a 892-1082 ms plan; nothing breaks, it just gets slow enough to look like a hang",
	},
	{
		"kind": "index",
		"table": "tabGL Entry",
		"name": "stabler_party_voucher_idx",
		"patch": "v77_gl_entry_party_indexes",
		"why": "drift_rows loses its covering index; same shape of failure as the balance index",
	},
	{
		"kind": "per_company",
		"doctype": "Sales Taxes and Charges Template",
		"title": "Uzbekistan NDS 12%",
		"patch": "v05_uzbek_tax_templates",
		"soft": True,
		"why": "no NDS template to select on a sales document",
	},
	{
		"kind": "per_company",
		"doctype": "Sales Taxes and Charges Template",
		"title": "Uzbekistan NDS Exempt",
		"patch": "v05_uzbek_tax_templates",
		"soft": True,
		"why": "no exempt template to select on a sales document",
	},
)


def describe(expectation: dict, company: str | None = None) -> str:
	"""One line naming what is missing, in the words the operator has to search for."""
	if expectation["kind"] == "index":
		return f"index {expectation['name']} on {expectation['table']}"
	if expectation["kind"] == "per_company":
		return f'{expectation["doctype"]} "{expectation["title"]}" for {company}'
	return f'{expectation["doctype"]} "{expectation["name"]}"'


def missing(expectations, present) -> list[dict]:
	"""The expectations `present` does not cover, in declaration order.

	Pure: `present` maps `(kind, identifier)` to a bool. The frappe half only has
	to answer that question — everything about what is worth asking, and what the
	answer means, lives here where it can be read and tested without a site.
	"""
	out = []
	for exp in expectations:
		for company, key in _keys(exp, present):
			if not present.get(key):
				out.append({**exp, "company": company, "label": describe(exp, company)})
	return out


def _keys(exp: dict, present: dict):
	"""(company, key) pairs to look up for one expectation."""
	if exp["kind"] == "per_company":
		for kind, ident, company in [k for k in present if k[0] == "per_company"]:
			if ident == exp["title"]:
				yield company, (kind, ident, company)
		return
	if exp["kind"] == "index":
		yield None, ("index", exp["name"])
		return
	yield None, ("doc", exp["doctype"], exp["name"])


def observe() -> dict:
	"""Ask the site the questions `missing()` needs answered. Read-only."""
	present: dict = {}
	for exp in _EXPECTATIONS:
		if exp["kind"] == "doc":
			present[("doc", exp["doctype"], exp["name"])] = bool(
				frappe.db.exists(exp["doctype"], exp["name"])
			)
		elif exp["kind"] == "index":
			rows = frappe.db.sql(f"SHOW INDEX FROM `{exp['table']}` WHERE Key_name = %s", (exp["name"],))
			present[("index", exp["name"])] = bool(rows)
	companies = frappe.get_all("Company", fields=["name", "abbr"])
	for exp in _EXPECTATIONS:
		if exp["kind"] != "per_company":
			continue
		for company in companies:
			template = f"{exp['title']} - {company['abbr']}"
			present[("per_company", exp["title"], company["name"])] = bool(
				frappe.db.exists(exp["doctype"], template)
			)
	return present


def run() -> dict:
	"""Print the report and return it. Creates nothing, runs no patch."""
	gaps = missing(_EXPECTATIONS, observe())
	site = frappe.local.site
	if not gaps:
		print(f"{site}: every asserted artifact is present.")
		return {"site": site, "missing": []}

	hard = [g for g in gaps if not g.get("soft")]
	soft = [g for g in gaps if g.get("soft")]
	print(f"{site}: {len(gaps)} asserted artifact(s) missing.")
	print("The Patch Log is not evidence — these were asked for directly.\n")
	for gap in hard:
		print(f"  MISSING  {gap['label']}")
		print(f"           from {gap['patch']} — {gap['why']}")
	for gap in soft:
		print(f"  CHECK    {gap['label']}")
		print(f"           from {gap['patch']} — {gap['why']}")
		print(
			"           v05 skips a company with no tax account and only logs it; confirm the account before blaming the patch."
		)
	print("\nDo NOT bulk-run patch modules to repair this. Read the named patch first,")
	print("then run that one. v80 rewrote live Payment Entries the last time a repair")
	print("path re-ran everything.")
	return {"site": site, "missing": [{"label": g["label"], "patch": g["patch"]} for g in gaps]}
