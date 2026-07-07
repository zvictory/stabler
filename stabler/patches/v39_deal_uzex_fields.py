"""UZEX portal sync fields on CRM Deal (WP-301).

Adds the columns the UZEX poller (WP-302) upserts a lot into and the SPA renders
as a live status chip + countdown (WP-304):

  custom_uzex_lot_no      Data      — portal lot id; UNIQUE → the dedupe key that
                                       makes the poller idempotent (one Deal per lot).
  custom_uzex_portal      Select    — which portal: etender / xarid / dxarid.
  custom_uzex_status      Data      — raw portal status string (mapped centrally,
                                       never rendered inline — see WP-303).
  custom_uzex_deadline    Datetime  — portal bid deadline (drives the countdown).
  custom_uzex_start_price Currency  — lot start / boshlang'ich price.
  custom_uzex_customer_org Data     — buyer organisation name from the portal.
  custom_uzex_last_synced Datetime  — last successful poll; when the portal is
                                       unreachable this is left untouched so the UI
                                       can flag the data as stale (CBU stale-rate pattern).

Populated only by the poller (ignore_permissions db_set), so every field is
read_only + hidden in Desk — the Stabler SPA is the sole surface.

Listed under [post_model_sync] in patches.txt: the CRM Deal DDL is synced first,
so the UNIQUE index on custom_uzex_lot_no lands cleanly. Idempotent: guarded by a
Custom Field existence check on the sentinel field, so a re-run adds nothing.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	if not frappe.db.exists("DocType", "CRM Deal"):
		return
	# Sentinel guard: if the dedupe key already exists the whole set was added.
	if frappe.db.exists("Custom Field", {"dt": "CRM Deal", "fieldname": "custom_uzex_lot_no"}):
		return

	after = "custom_tender_intake" if frappe.db.has_column("CRM Deal", "custom_tender_intake") else "status"
	price_options = "currency" if frappe.db.has_column("CRM Deal", "currency") else None

	create_custom_fields(
		{
			"CRM Deal": [
				{
					"fieldname": "custom_uzex_lot_no",
					"label": "UZEX Lot No",
					"fieldtype": "Data",
					"insert_after": after,
					"unique": 1,
					"read_only": 1,
					"hidden": 1,
					"description": "Portal lot id — unique dedupe key for the UZEX poller.",
				},
				{
					"fieldname": "custom_uzex_portal",
					"label": "UZEX Portal",
					"fieldtype": "Select",
					"options": "\netender\nxarid\ndxarid",
					"insert_after": "custom_uzex_lot_no",
					"read_only": 1,
					"hidden": 1,
				},
				{
					"fieldname": "custom_uzex_status",
					"label": "UZEX Status",
					"fieldtype": "Data",
					"insert_after": "custom_uzex_portal",
					"read_only": 1,
					"hidden": 1,
				},
				{
					"fieldname": "custom_uzex_deadline",
					"label": "UZEX Deadline",
					"fieldtype": "Datetime",
					"insert_after": "custom_uzex_status",
					"read_only": 1,
					"hidden": 1,
				},
				{
					"fieldname": "custom_uzex_start_price",
					"label": "UZEX Start Price",
					"fieldtype": "Currency",
					"options": price_options,
					"insert_after": "custom_uzex_deadline",
					"read_only": 1,
					"hidden": 1,
				},
				{
					"fieldname": "custom_uzex_customer_org",
					"label": "UZEX Customer Org",
					"fieldtype": "Data",
					"insert_after": "custom_uzex_start_price",
					"read_only": 1,
					"hidden": 1,
				},
				{
					"fieldname": "custom_uzex_last_synced",
					"label": "UZEX Last Synced",
					"fieldtype": "Datetime",
					"insert_after": "custom_uzex_customer_org",
					"read_only": 1,
					"hidden": 1,
					"description": "Last successful poll; stale when the portal is unreachable.",
				},
			]
		},
		ignore_validate=True,
	)
