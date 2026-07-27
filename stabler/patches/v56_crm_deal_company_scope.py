"""Add the company scope required by Stabler tender APIs to CRM Deal.

Frappe CRM v2 does not provide a native ``CRM Deal.company`` field. Stabler
uses that field to enforce company-scoped tender reads and writes, so the field
must exist rather than bypassing Frappe's query permission validation.

Existing blank deals are backfilled only when the site has exactly one
non-group company. Multi-company sites require an explicit ownership decision.

The field carries **no** ``default``. Frappe reads a default starting with ``:``
as "fetch this fieldname from that doctype", so ``:Company`` on a field named
``company`` runs ``get_value("Company", …, "company")`` — a column that does not
exist — and every ``frappe.new_doc("CRM Deal")`` dies with error 1054. Standard
ERPNext company fields also ship with no default; the value comes from
``frappe.defaults``. See ``v59_crm_deal_company_default_fix`` for the repair.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	if not frappe.db.exists("DocType", "CRM Deal"):
		return

	if not frappe.db.has_column("CRM Deal", "company"):
		create_custom_fields(
			{
				"CRM Deal": [
					{
						"fieldname": "company",
						"label": "Company",
						"fieldtype": "Link",
						"options": "Company",
						"insert_after": "organization",
						"description": "Company scope used by Stabler tender operations.",
					}
				]
			},
			ignore_validate=True,
		)

	companies = frappe.get_all(
		"Company",
		filters={"is_group": 0},
		pluck="name",
		limit_page_length=2,
	)
	if len(companies) != 1:
		return

	frappe.db.sql(
		"""
		UPDATE `tabCRM Deal`
		SET company = %s
		WHERE COALESCE(company, '') = ''
		""",
		(companies[0],),
	)
