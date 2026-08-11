"""Add MSA Import detail fields to Supplier DocType.

Supports MSA meat import requirements:
- APEDA registration number (India meat exporter registration)
- Manufacturer / Plant name
- Country / Place of Origin
- Brand Name (e.g. Black Gold, Al Super)
- Contract Number, Contract Date, Contract Amount ($ USD)
- Importer Company (MSA / TQFM / Fresh)
- IDN Bank / Intermediary Bank details
- Bank Details, Address, Contact Person, Notes

Idempotent: guarded by Custom Field existence checks. Post-model-sync safe.
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	fields_to_create = []

	field_definitions = [
		{
			"fieldname": "custom_apeda",
			"label": "APEDA Registration No",
			"fieldtype": "Data",
			"insert_after": "tax_id",
		},
		{
			"fieldname": "custom_contact_person",
			"label": "Contact Person",
			"fieldtype": "Data",
			"insert_after": "email_id",
		},
		{
			"fieldname": "custom_manufacturer",
			"label": "Manufacturer / Plant",
			"fieldtype": "Data",
			"insert_after": "custom_contact_person",
		},
		{
			"fieldname": "custom_place_of_origin",
			"label": "Place of Origin",
			"fieldtype": "Data",
			"insert_after": "country",
		},
		{
			"fieldname": "custom_brand",
			"label": "Brand Name",
			"fieldtype": "Data",
			"insert_after": "custom_manufacturer",
		},
		{
			"fieldname": "custom_contract_number",
			"label": "Contract Number",
			"fieldtype": "Data",
			"insert_after": "custom_brand",
		},
		{
			"fieldname": "custom_date_of_contract",
			"label": "Date of Contract",
			"fieldtype": "Date",
			"insert_after": "custom_contract_number",
		},
		{
			"fieldname": "custom_amount_of_contract",
			"label": "Amount of Contract ($ USD)",
			"fieldtype": "Currency",
			"insert_after": "custom_date_of_contract",
		},
		{
			"fieldname": "custom_importer_company",
			"label": "Importer Company",
			"fieldtype": "Select",
			"options": "MSA\nTQFM\nFresh",
			"insert_after": "custom_amount_of_contract",
		},
		{
			"fieldname": "custom_idn_bank",
			"label": "IDN / Intermediary Bank",
			"fieldtype": "Data",
			"insert_after": "custom_importer_company",
		},
		{
			"fieldname": "custom_bank_details",
			"label": "Bank Details",
			"fieldtype": "Small Text",
			"insert_after": "custom_idn_bank",
		},
		{
			"fieldname": "custom_address",
			"label": "Supplier Address",
			"fieldtype": "Small Text",
			"insert_after": "custom_bank_details",
		},
		{
			"fieldname": "custom_notes",
			"label": "Import Notes",
			"fieldtype": "Small Text",
			"insert_after": "custom_address",
		},
	]

	for f in field_definitions:
		if not frappe.db.exists("Custom Field", {"dt": "Supplier", "fieldname": f["fieldname"]}):
			fields_to_create.append(f)

	if fields_to_create:
		create_custom_fields({"Supplier": fields_to_create}, ignore_validate=True)
